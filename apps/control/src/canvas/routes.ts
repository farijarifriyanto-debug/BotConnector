import type { FastifyInstance } from 'fastify';
import { randomUUID } from 'node:crypto';
import {
  DirectEditCommandSchema,
  DirectEditTargetSchema,
  JsonValueSchema,
  SelectionContextSchema,
  UIIRSchema,
  type UIIR,
  type UIIRNode,
} from '@botconnector/contracts';
import { validationError, notFoundError, revisionConflictError } from '../errors/index.js';
import { sendSuccess, sendCreated, sendError } from '../errors/response.js';
import { createRequestContext } from '../request-context/index.js';
import { withTenantTransaction } from '../db/tenant.js';
import { parseIfMatch, assertRevisionMatch, incrementRevision } from '../db/concurrency.js';
import { emitDomainEventForMutation } from '../events/service.js';
import type { PrincipalResolver } from '../index.js';

interface CanvasRow {
  id: string;
  project_id: string;
  artifact_id: string;
  workspace_id: string;
  root_node_id: string;
  nodes: unknown;
  revision: string;
  base_revision: string;
  created_at: Date | string;
  updated_at: Date | string;
}

const CANVAS_COLUMNS = `id, project_id, artifact_id, workspace_id, root_node_id, nodes, revision, base_revision, created_at, updated_at`;

function isoTimestamp(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

function toUiir(row: CanvasRow): UIIR {
  return UIIRSchema.parse({
    version: 1,
    id: row.id,
    project_id: row.project_id,
    artifact_id: row.artifact_id,
    revision: String(row.revision),
    base_revision: String(row.base_revision),
    root_node_id: row.root_node_id,
    nodes: row.nodes,
    created_at: isoTimestamp(row.created_at),
    updated_at: isoTimestamp(row.updated_at),
  });
}

function requireObject(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw validationError(message);
  }
  return value as Record<string, unknown>;
}

function parseNodes(value: unknown): UIIR['nodes'] {
  if (!Array.isArray(value)) {
    throw validationError('nodes is required and must be an array');
  }
  return value as UIIR['nodes'];
}

function parseSelection(value: unknown, canvas: UIIR) {
  const body = requireObject(value, 'selection is required');
  const selectedNodeIds = body.selected_node_ids;
  if (!Array.isArray(selectedNodeIds) || selectedNodeIds.length === 0 || selectedNodeIds.some((id) => typeof id !== 'string')) {
    throw validationError('selection.selected_node_ids must be a non-empty string array');
  }
  if (typeof body.uiir_revision !== 'string' || !/^[0-9]+$/.test(body.uiir_revision)) {
    throw validationError('selection.uiir_revision must be a canonical revision string');
  }

  const nodeIds = new Set(canvas.nodes.map((node) => node.id));
  if (selectedNodeIds.some((id) => !nodeIds.has(id))) {
    throw validationError('selection contains a node that is not present in the canvas');
  }

  const primaryNodeId = body.primary_node_id === null || body.primary_node_id === undefined
    ? null
    : body.primary_node_id;
  if (primaryNodeId !== null && (typeof primaryNodeId !== 'string' || !selectedNodeIds.includes(primaryNodeId))) {
    throw validationError('selection.primary_node_id must be one of selected_node_ids');
  }

  return SelectionContextSchema.parse({
    version: 1,
    id: randomUUID(),
    project_id: canvas.project_id,
    artifact_id: canvas.artifact_id,
    uiir_revision: body.uiir_revision,
    selected_node_ids: selectedNodeIds,
    primary_node_id: primaryNodeId,
    created_at: new Date().toISOString(),
  });
}

function parseEditBody(body: unknown) {
  const value = requireObject(body, 'Request body is required');
  const target = DirectEditTargetSchema.safeParse(value.target);
  if (!target.success) {
    throw validationError('target must be one of: content, layout, style, tokens');
  }
  const path = value.path === undefined ? [] : value.path;
  if (!Array.isArray(path) || path.some((part) => typeof part !== 'string' || !/^[a-z][a-z0-9_-]*$/.test(part))) {
    throw validationError('path must contain lowercase portable identifiers');
  }
  if (target.data === 'content' && path.length > 0) {
    throw validationError('content direct edits do not accept a path');
  }
  if (target.data !== 'content' && path.length === 0) {
    throw validationError(`${target.data} direct edits require a path`);
  }
  const parsedValue = JsonValueSchema.safeParse(value.value);
  if (!parsedValue.success) {
    throw validationError('value must be a JSON value');
  }
  if (target.data === 'content' && parsedValue.data !== null && typeof parsedValue.data !== 'string') {
    throw validationError('content direct edits require a string or null value');
  }
  return { target: target.data, path, value: parsedValue.data };
}

function applyEdit(canvas: UIIR, nodeId: string, edit: ReturnType<typeof parseEditBody>): UIIRNode[] {
  const nodes = structuredClone(canvas.nodes) as UIIRNode[];
  const node = nodes.find((candidate) => candidate.id === nodeId);
  if (!node) {
    throw validationError(`Node ${nodeId} is not present in the canvas`);
  }

  if (edit.target === 'content') {
    node.content = edit.value as string | null;
  } else {
    const target = edit.target as 'layout' | 'style' | 'tokens';
    let current = node[target] as Record<string, unknown>;
    for (const part of edit.path.slice(0, -1)) {
      const next = current[part];
      if (next === undefined) {
        current[part] = {};
      } else if (!next || typeof next !== 'object' || Array.isArray(next)) {
        throw validationError(`Cannot edit through non-object path segment: ${part}`);
      }
      current = current[part] as Record<string, unknown>;
    }
    current[edit.path[edit.path.length - 1]] = edit.value;
  }

  return nodes;
}

async function loadCanvas(canvasId: string, workspaceId: string): Promise<UIIR> {
  return withTenantTransaction(workspaceId, async (tx) => {
    const result = await tx.client.query<CanvasRow>(
      `SELECT ${CANVAS_COLUMNS} FROM design.canvases WHERE id = $1`,
      [canvasId],
    );
    if (result.rows.length === 0) {
      throw notFoundError(`Canvas ${canvasId} not found`);
    }
    return toUiir(result.rows[0]);
  });
}

export async function registerCanvasRoutes(app: FastifyInstance, resolvePrincipal: PrincipalResolver): Promise<void> {
  app.post<{
    Params: { projectId: string };
    Body: { artifact_id: string; root_node_id: string; nodes: unknown[] };
  }>('/api/v1/projects/:projectId/canvases', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const body = requireObject(request.body, 'Request body is required');
      if (typeof body.artifact_id !== 'string' || typeof body.root_node_id !== 'string') {
        throw validationError('artifact_id and root_node_id are required strings');
      }
      const nodes = parseNodes(body.nodes);
      const canvasId = randomUUID();
      const now = new Date().toISOString();
       const parsedCanvas = UIIRSchema.safeParse({
         version: 1,
        id: canvasId,
        project_id: request.params.projectId,
        artifact_id: body.artifact_id,
        revision: '0',
        base_revision: '0',
        root_node_id: body.root_node_id,
        nodes,
         created_at: now,
         updated_at: now,
       });
       if (!parsedCanvas.success) {
         throw validationError('Canvas UI-IR is invalid', parsedCanvas.error.issues);
       }
       const canvas = parsedCanvas.data;

      const result = await withTenantTransaction(principal.workspaceId, async (tx) => {
        const artifact = await tx.client.query(
          `SELECT id FROM core.artifacts WHERE id = $1 AND project_id = $2`,
          [canvas.artifact_id, canvas.project_id],
        );
        if (artifact.rows.length === 0) {
          throw notFoundError(`Artifact ${canvas.artifact_id} not found in project ${canvas.project_id}`);
        }

        await tx.client.query(
          `INSERT INTO design.canvases
             (id, project_id, artifact_id, workspace_id, root_node_id, nodes, revision, base_revision, created_at, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, '0', '0', $7, $7)`,
          [canvas.id, canvas.project_id, canvas.artifact_id, principal.workspaceId, canvas.root_node_id, JSON.stringify(canvas.nodes), now],
        );
        await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
          projectId: canvas.project_id,
          eventType: 'canvas.created',
          aggregateType: 'canvas',
          aggregateId: canvas.id,
          payload: { canvas_id: canvas.id, artifact_id: canvas.artifact_id, revision: '0' },
        });
        return canvas;
      });

      sendCreated(reply, requestCtx, result, { revision: result.revision });
    } catch (error) {
      sendError(reply, requestCtx, error);
    }
  });

  app.get<{ Params: { projectId: string } }>('/api/v1/projects/:projectId/canvases', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    try {
      const rows = await withTenantTransaction(principal.workspaceId, async (tx) => {
        const result = await tx.client.query<CanvasRow>(
          `SELECT ${CANVAS_COLUMNS} FROM design.canvases WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100`,
          [request.params.projectId],
        );
        return result.rows.map(toUiir);
      });
      sendSuccess(reply, requestCtx, rows);
    } catch (error) {
      sendError(reply, requestCtx, error);
    }
  });

  app.get<{ Params: { canvasId: string } }>('/api/v1/canvases/:canvasId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    try {
      const canvas = await loadCanvas(request.params.canvasId, principal.workspaceId);
      sendSuccess(reply, requestCtx, canvas, { revision: canvas.revision });
    } catch (error) {
      sendError(reply, requestCtx, error);
    }
  });

  app.post<{
    Params: { canvasId: string };
    Body: { selected_node_ids: string[]; primary_node_id?: string | null; uiir_revision: string };
  }>('/api/v1/canvases/:canvasId/selections', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    try {
      const selection = await withTenantTransaction(principal.workspaceId, async (tx) => {
        const result = await tx.client.query<CanvasRow>(
          `SELECT ${CANVAS_COLUMNS} FROM design.canvases WHERE id = $1 FOR SHARE`,
          [request.params.canvasId],
        );
        if (result.rows.length === 0) {
          throw notFoundError(`Canvas ${request.params.canvasId} not found`);
        }
        const canvas = toUiir(result.rows[0]);
        const parsedSelection = parseSelection(request.body, canvas);
        assertRevisionMatch(canvas.revision, parsedSelection.uiir_revision, 'Canvas');
        await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
          projectId: canvas.project_id,
          eventType: 'canvas.selection_created',
          aggregateType: 'canvas',
          aggregateId: canvas.id,
          payload: {
            canvas_id: canvas.id,
            selection_id: parsedSelection.id,
            selected_node_ids: parsedSelection.selected_node_ids,
            primary_node_id: parsedSelection.primary_node_id,
            revision: parsedSelection.uiir_revision,
          },
        });
        return parsedSelection;
      });
      sendCreated(reply, requestCtx, selection);
    } catch (error) {
      sendError(reply, requestCtx, error);
    }
  });

  app.post<{
    Params: { canvasId: string };
    Body: {
      selection: { selected_node_ids: string[]; primary_node_id?: string | null; uiir_revision: string };
      target: 'content' | 'layout' | 'style' | 'tokens';
      path?: string[];
      value: unknown;
    };
  }>('/api/v1/canvases/:canvasId/direct-edits', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    try {
      const canvas = await loadCanvas(request.params.canvasId, principal.workspaceId);
      const selection = parseSelection(request.body && request.body.selection, canvas);
      assertRevisionMatch(canvas.revision, selection.uiir_revision, 'Canvas');
      if (!selection.primary_node_id) {
        throw validationError('Direct edits require selection.primary_node_id');
      }
      const edit = parseEditBody(request.body);
      const ifMatchRevision = parseIfMatch(request.headers['if-match'] as string | undefined);
      assertRevisionMatch(canvas.revision, ifMatchRevision, 'Canvas');

      const nodes = applyEdit(canvas, selection.primary_node_id, edit);
      const newRevision = incrementRevision(canvas.revision);
      const parsedUpdated = UIIRSchema.safeParse({
        ...canvas,
        nodes,
        revision: newRevision,
        base_revision: newRevision,
        updated_at: new Date().toISOString(),
      });
      if (!parsedUpdated.success) {
        throw validationError('Direct edit would produce invalid Canvas UI-IR', parsedUpdated.error.issues);
      }
      const updated = parsedUpdated.data;
      const command = DirectEditCommandSchema.parse({
        version: 1,
        id: randomUUID(),
        canvas_id: canvas.id,
        selection_id: selection.id,
        uiir_revision: selection.uiir_revision,
        node_id: selection.primary_node_id,
        target: edit.target,
        path: edit.path,
        value: edit.value,
      });

       await withTenantTransaction(principal.workspaceId, async (tx) => {
         const result = await tx.client.query<CanvasRow>(
          `UPDATE design.canvases
              SET nodes = $1::jsonb, revision = $2::bigint, base_revision = $2::bigint, updated_at = $3
            WHERE id = $4 AND revision = $5::bigint
            RETURNING ${CANVAS_COLUMNS}`,
          [JSON.stringify(updated.nodes), newRevision, updated.updated_at, canvas.id, ifMatchRevision],
        );
         if (result.rows.length === 0) {
           throw revisionConflictError(`Canvas ${canvas.id} revision changed during direct edit`);
         }
         await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
           projectId: canvas.project_id,
           eventType: 'canvas.selection_created',
           aggregateType: 'canvas',
           aggregateId: canvas.id,
           payload: {
             canvas_id: canvas.id,
             selection_id: command.selection_id,
             selected_node_ids: selection.selected_node_ids,
             primary_node_id: selection.primary_node_id,
             revision: selection.uiir_revision,
           },
         });
         await emitDomainEventForMutation(tx, principal, requestCtx.requestId, {
          projectId: canvas.project_id,
          eventType: 'canvas.direct_edit_applied',
          aggregateType: 'canvas',
          aggregateId: canvas.id,
          payload: {
            canvas_id: canvas.id,
            selection_id: command.selection_id,
            node_id: command.node_id,
            target: command.target,
            path: command.path,
            revision: newRevision,
          },
        });
      });

      sendSuccess(reply, requestCtx, { canvas: updated, selection, command }, { revision: newRevision });
    } catch (error) {
      sendError(reply, requestCtx, error);
    }
  });
}
