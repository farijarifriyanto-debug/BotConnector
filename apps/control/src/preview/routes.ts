import http from 'node:http';
import type { FastifyInstance } from 'fastify';
import { SandboxManagerHttpError, type PreviewInfo, type SandboxManagerClient } from '../sandbox-manager/client.js';
import type { PrincipalResolver } from '../index.js';
import { createRequestContext } from '../request-context/index.js';
import { projectBelongsToWorkspace, projectIdsForWorkspace } from '../authorization/project.js';

export interface PreviewRouteOptions {
  previewProxyUrl: string;
  previewProxySecret: string;
}

function upstreamStatus(err: unknown, fallback = 500): number {
  if (err instanceof SandboxManagerHttpError && err.status >= 400 && err.status <= 599) {
    return err.status;
  }
  return fallback;
}

function toPublicPreview(preview: PreviewInfo) {
  return {
    id: preview.id,
    workspace_id: preview.workspaceId,
    project_id: preview.projectId,
    task_id: preview.taskId,
    container_id: preview.containerId,
    container_ip: preview.containerIp,
    dev_port: preview.devPort,
    state: preview.state,
    created_at: preview.createdAt,
    destroyed_at: preview.destroyedAt,
    last_valid_state: preview.lastValidState,
    detected_stack: preview.detectedStack,
    image: preview.image,
  };
}

export async function registerPreviewRoutes(
  app: FastifyInstance,
  resolvePrincipal: PrincipalResolver,
  client: SandboxManagerClient,
  options: PreviewRouteOptions,
): Promise<void> {
  // CREATE preview
  app.post<{
    Body: {
      workspace_id: string;
      project_id: string;
      task_id: string;
      command?: string[];
      dev_port?: number;
    };
  }>('/api/v1/previews', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    const { workspace_id, project_id, task_id, command, dev_port } = request.body as {
      workspace_id: string;
      project_id: string;
      task_id: string;
      command?: string[];
      dev_port?: number;
    };

    if (!workspace_id || !project_id || !task_id) {
      reply.code(400).send({
        error: { code: 'VALIDATION_ERROR', message: 'Missing required fields', request_id: requestCtx.requestId },
      });
      return;
    }

    // The execution workspace has a different ID from the tenant workspace.
    // Authorize through the durable project-to-workspace relationship instead.
    if (!(await projectBelongsToWorkspace(project_id, principal.workspaceId))) {
      reply.code(403).send({
        error: { code: 'FORBIDDEN', message: 'Project is not owned by the caller workspace', request_id: requestCtx.requestId },
      });
      return;
    }

    try {
      const workspace = await client.getWorkspace(workspace_id);
      if (workspace.projectId !== project_id || workspace.taskId !== task_id) {
        reply.code(403).send({
          error: { code: 'FORBIDDEN', message: 'Execution workspace does not belong to the project', request_id: requestCtx.requestId },
        });
        return;
      }

      const result = await client.request<PreviewInfo>('POST', '/internal/v1/previews', {
        workspace_id,
        project_id,
        task_id,
        command,
        dev_port,
      });

      reply.code(201).send({ data: toPublicPreview(result) });
    } catch (err) {
      reply.code(upstreamStatus(err)).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message, request_id: requestCtx.requestId },
      });
    }
  });

  // LIST previews (filtered by caller's workspace)
  app.get('/api/v1/previews', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);

    try {
      const projectIds = await projectIdsForWorkspace(principal.workspaceId);
      const result = await client.request<PreviewInfo[]>('GET', '/internal/v1/previews');
      const filtered = result.filter((preview) => projectIds.has(preview.projectId));

      reply.send({ data: filtered.map(toPublicPreview) });
    } catch (err) {
      reply.code(upstreamStatus(err)).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message, request_id: requestCtx.requestId },
      });
    }
  });

  // GET preview
  app.get<{
    Params: { previewId: string };
  }>('/api/v1/previews/:previewId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    const { previewId } = request.params;

    try {
      const result = await client.request<PreviewInfo>('GET', `/internal/v1/previews/${previewId}`);

      if (!(await projectBelongsToWorkspace(result.projectId, principal.workspaceId))) {
        reply.code(404).send({
          error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found`, request_id: requestCtx.requestId },
        });
        return;
      }

      reply.send({ data: toPublicPreview(result) });
    } catch (err) {
      reply.code(upstreamStatus(err)).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message, request_id: requestCtx.requestId },
      });
    }
  });

  // BROWSER PROXY: Stream preview content to browser
  // GET /api/v1/previews/:previewId/proxy/* → control verifies ownership → proxies to PreviewProxy
  app.all<{
    Params: { previewId: string; '*': string };
    Querystring: { [key: string]: string };
  }>('/api/v1/previews/:previewId/proxy/*', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    const { previewId } = request.params;

    // Verify ownership
    try {
      const preview = await client.request<PreviewInfo>('GET', `/internal/v1/previews/${previewId}`);

      if (!(await projectBelongsToWorkspace(preview.projectId, principal.workspaceId))) {
        reply.code(404).send({
          error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found`, request_id: requestCtx.requestId },
        });
        return;
      }

      if (preview.state !== 'running') {
        reply.code(503).send({
          error: { code: 'PREVIEW_NOT_RUNNING', message: `Preview is in state: ${preview.state}`, request_id: requestCtx.requestId },
        });
        return;
      }
    } catch (err) {
      reply.code(upstreamStatus(err, 502) === 404 ? 404 : 502).send({
        error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found`, request_id: requestCtx.requestId },
      });
      return;
    }

    // Forward to PreviewProxy
    const pathSuffix = request.params['*'] || '';
    const queryIndex = request.url.indexOf('?');
    const query = queryIndex >= 0 ? request.url.slice(queryIndex) : '';
    const targetPath = `/preview/${encodeURIComponent(previewId)}/${pathSuffix}${query}`;
    reply.hijack();
    let proxyResponseStarted = false;
    let proxyRes: http.IncomingMessage | undefined;

    const proxyReq = http.request({
      hostname: new URL(options.previewProxyUrl).hostname,
      port: new URL(options.previewProxyUrl).port,
      path: targetPath,
      method: request.method,
      headers: {
        ...Object.fromEntries(
          Object.entries(request.headers).filter(([key]) => !new Set([
           'authorization', 'cookie', 'x-forwarded-for', 'x-forwarded-proto',
           'x-real-ip', 'x-forwarded-host', 'x-forwarded-port', 'connection',
           'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te',
           'trailer', 'transfer-encoding', 'upgrade',
          ]).has(key.toLowerCase())),
        ),
        host: new URL(options.previewProxyUrl).host,
        authorization: `Bearer ${options.previewProxySecret}`,
      },
    }, (upstreamRes) => {
       proxyRes = upstreamRes;
       // Do not let an untrusted preview set cookies or hop-by-hop headers.
       const filteredHeaders = Object.fromEntries(
          Object.entries(upstreamRes.headers).filter(([key]) => !new Set([
           'set-cookie', 'connection', 'keep-alive', 'proxy-authenticate',
           'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade',
           'x-powered-by',
         ]).has(key.toLowerCase())),
       );
       proxyResponseStarted = true;
       reply.raw.writeHead(upstreamRes.statusCode ?? 502, filteredHeaders);
       upstreamRes.pipe(reply.raw);
       upstreamRes.on('error', (err) => {
         console.error(`[PreviewGateway] Upstream response error for ${previewId}:`, err.message);
         if (!reply.raw.destroyed) reply.raw.destroy(err);
       });
     });

    const abortProxy = () => {
      if (!proxyReq.destroyed) proxyReq.destroy();
      if (proxyRes && !proxyRes.destroyed) proxyRes.destroy();
    };
    request.raw.once('aborted', abortProxy);
    reply.raw.once('close', () => {
      if (!reply.raw.writableEnded) abortProxy();
    });

    proxyReq.on('error', (err) => {
      console.error(`[PreviewGateway] Error proxying to ${previewId}:`, err.message);
       if (!proxyResponseStarted && !reply.raw.headersSent) {
         reply.raw.writeHead(502, { 'Content-Type': 'application/json' });
         reply.raw.end(JSON.stringify({
           error: { code: 'PROXY_ERROR', message: `Failed to connect to preview: ${err.message}`, request_id: requestCtx.requestId },
         }));
      }
    });

    proxyReq.setTimeout(30000, () => {
      proxyReq.destroy();
       if (!proxyResponseStarted && !reply.raw.headersSent) {
         reply.raw.writeHead(504, { 'Content-Type': 'application/json' });
         reply.raw.end(JSON.stringify({
           error: { code: 'PROXY_TIMEOUT', message: 'Preview request timed out', request_id: requestCtx.requestId },
         }));
      }
    });

    // Fastify has already parsed JSON bodies before entering this handler.
    // Re-serialize those bodies so mutation requests are not silently dropped.
    if (request.body !== undefined && request.body !== null) {
      const body = typeof request.body === 'string' ? request.body : JSON.stringify(request.body);
      proxyReq.setHeader('content-length', Buffer.byteLength(body));
      proxyReq.end(body);
    } else {
      proxyReq.end();
    }
  });

  // STOP preview
  app.post<{
    Params: { previewId: string };
  }>('/api/v1/previews/:previewId/stop', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    const { previewId } = request.params;

    try {
      // Verify ownership before stopping
      const preview = await client.request<PreviewInfo>('GET', `/internal/v1/previews/${previewId}`);

      if (!(await projectBelongsToWorkspace(preview.projectId, principal.workspaceId))) {
        reply.code(404).send({
          error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found`, request_id: requestCtx.requestId },
        });
        return;
      }

      await client.request('POST', `/internal/v1/previews/${previewId}/stop`);
      reply.send({ data: { stopped: true } });
    } catch (err) {
      reply.code(upstreamStatus(err)).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message, request_id: requestCtx.requestId },
      });
    }
  });

  // DELETE preview
  app.delete<{
    Params: { previewId: string };
  }>('/api/v1/previews/:previewId', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    const { previewId } = request.params;

    try {
      // Verify ownership before deleting
      const preview = await client.request<PreviewInfo>('GET', `/internal/v1/previews/${previewId}`);

      if (!(await projectBelongsToWorkspace(preview.projectId, principal.workspaceId))) {
        reply.code(404).send({
          error: { code: 'NOT_FOUND', message: `Preview ${previewId} not found`, request_id: requestCtx.requestId },
        });
        return;
      }

      await client.request('DELETE', `/internal/v1/previews/${previewId}`);
      reply.send({ data: { destroyed: true } });
    } catch (err) {
      reply.code(upstreamStatus(err)).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message, request_id: requestCtx.requestId },
      });
    }
  });

  // LIST previews by project
  app.get<{
    Params: { projectId: string };
  }>('/api/v1/projects/:projectId/previews', async (request, reply) => {
    const principal = resolvePrincipal(request.headers);
    const requestCtx = createRequestContext(principal);
    const { projectId } = request.params;

    try {
      if (!(await projectBelongsToWorkspace(projectId, principal.workspaceId))) {
        reply.code(404).send({
          error: { code: 'NOT_FOUND', message: `Project ${projectId} not found`, request_id: requestCtx.requestId },
        });
        return;
      }

      const result = await client.request<PreviewInfo[]>('GET', `/internal/v1/projects/${projectId}/previews`);

      reply.send({ data: result.map(toPublicPreview) });
    } catch (err) {
      reply.code(upstreamStatus(err)).send({
        error: { code: 'PREVIEW_ERROR', message: (err as Error).message, request_id: requestCtx.requestId },
      });
    }
  });
}
