import { describe, expect, it } from 'vitest';

import {
  CONTRACT_COUNT,
  ChatMessageSchema,
  DeploymentSchema,
  ErrorEnvelopeSchema,
  FailureSignatureSchema,
  RepairRunSchema,
  ValidationResultSchema,
  ValidationStageSchema,
  exportJsonSchemaBundle,
  exportOpenApiDocument,
  validateWebSocketPayload,
} from '../src/index.js';
import { parseBackendProject } from './fixtures/backend-consumer.js';
import { parseFrontendProject } from './fixtures/frontend-consumer.js';

const timestamp = '2026-09-01T00:00:00.000Z';

const generationEvent = {
  version: 1,
  id: 'event-1',
  sequence: 1,
  project_id: 'project-1',
  correlation_id: 'correlation-1',
  causation_id: null,
  actor: { type: 'system', id: 'control-plane' },
  timestamp,
  payload: {
    version: 1,
    family: 'state',
    state: 'running',
    previous_state: 'planning',
  },
};

function collectRefs(value: unknown, refs: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) collectRefs(item, refs);
  } else if (value !== null && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (key === '$ref' && typeof child === 'string') refs.push(child);
      else collectRefs(child, refs);
    }
  }
  return refs;
}

function resolveLocalRef(document: unknown, ref: string): unknown {
  if (!ref.startsWith('#/')) return undefined;
  return ref
    .slice(2)
    .split('/')
    .map((part) => part.replaceAll('~1', '/').replaceAll('~0', '~'))
    .reduce<unknown>((current, part) => {
      if (current === null || typeof current !== 'object') return undefined;
      return (current as Record<string, unknown>)[part];
    }, document);
}

describe('validation and deployment contracts', () => {
  it('exports every locked validation stage', () => {
    expect(ValidationStageSchema.options).toEqual([
      'parse',
      'typecheck',
      'build',
      'runtime',
      'browser',
      'console',
      'accessibility',
      'regression',
    ]);
  });

  it('validates nested validation results, failures, and repairs', () => {
    expect(
      ValidationResultSchema.parse({
        version: 1,
        id: 'validation-1',
        project_id: 'project-1',
        task_id: 'task-1',
        changeset_id: 'changeset-1',
        outcome: 'pass',
        revision: '1',
        base_revision: '0',
        stages: [
          {
            version: 1,
            id: 'stage-1',
            stage: 'typecheck',
            outcome: 'pass',
            duration_ms: 120,
            message: null,
          },
        ],
        created_at: timestamp,
        updated_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      FailureSignatureSchema.parse({
        version: 1,
        id: 'failure-1',
        stage: 'typecheck',
        code: 'TS2322',
        fingerprint: 'sha256:value',
        message: 'Type mismatch',
        created_at: timestamp,
      }),
    ).toBeDefined();
    expect(
      RepairRunSchema.parse({
        version: 1,
        id: 'repair-1',
        project_id: 'project-1',
        task_id: 'task-1',
        failure_signature_id: 'failure-1',
        changeset_id: null,
        state: 'queued',
        revision: '1',
        base_revision: '0',
        started_at: null,
        ended_at: null,
      }),
    ).toBeDefined();
  });

  it('validates a Deployment contract without implementing deployment', () => {
    expect(
      DeploymentSchema.parse({
        version: 1,
        id: 'deployment-1',
        project_id: 'project-1',
        artifact_id: 'artifact-1',
        artifact_version_id: 'artifact-version-1',
        environment: 'production',
        state: 'planned',
        revision: '1',
        base_revision: '0',
        created_at: timestamp,
        updated_at: timestamp,
      }),
    ).toBeDefined();
  });
});

describe('transport contracts', () => {
  it('validates WebSocket event envelopes', () => {
    const envelope = {
      version: 1,
      type: 'generation_event',
      event: generationEvent,
    };
    expect(validateWebSocketPayload(envelope)).toEqual(envelope);
  });

  it('validates ErrorEnvelope and rejects missing errors', () => {
    const envelope = {
      version: 1,
      metadata: {
        version: 1,
        request_id: 'request-1',
        timestamp,
      },
      error: {
        code: 'INVALID_CONTRACT',
        message: 'Payload rejected',
        details: { path: 'project.name' },
      },
    };
    expect(ErrorEnvelopeSchema.parse(envelope)).toEqual(envelope);
    const { error: _error, ...invalid } = envelope;
    expect(ErrorEnvelopeSchema.safeParse(invalid).success).toBe(false);
  });

  it('keeps ChatMessage distinct from task and run contracts', () => {
    const message = {
      version: 1,
      id: 'message-1',
      project_id: 'project-1',
      task_id: 'task-1',
      agent_run_id: 'agent-run-1',
      role: 'assistant',
      content: 'Contracts validated',
      correlation_id: 'correlation-1',
      causation_id: null,
      created_at: timestamp,
    };
    expect(ChatMessageSchema.parse(message)).toEqual(message);
  });
});

describe('schema exports', () => {
  it('exports all canonical contracts as deterministic JSON Schema', () => {
    const first = exportJsonSchemaBundle();
    const second = exportJsonSchemaBundle();
    expect(CONTRACT_COUNT).toBe(38);
    expect(Object.keys(first.$defs)).toHaveLength(CONTRACT_COUNT);
    expect(first.$defs.Project.additionalProperties).toBe(false);
    expect(JSON.stringify(first.$defs.UIIRNode)).toContain('propertyNames');
    expect(JSON.stringify(first.$defs.UIIRNode)).toContain('pattern');
    expect(JSON.stringify(first.$defs.ChangeOperation)).toContain('pattern');
    expect(JSON.stringify(first)).toBe(JSON.stringify(second));
    for (const ref of collectRefs(first)) {
      expect(resolveLocalRef(first, ref), `dangling JSON Schema ref: ${ref}`).toBeDefined();
    }
  });

  it('exports OpenAPI 3.1-compatible schema components', () => {
    const document = exportOpenApiDocument();
    expect(document.openapi).toBe('3.1.0');
    expect(Object.keys(document.components.schemas)).toHaveLength(CONTRACT_COUNT);
    expect(document.components.schemas.ErrorEnvelope).toBeDefined();
    for (const ref of collectRefs(document)) {
      expect(resolveLocalRef(document, ref), `dangling OpenAPI ref: ${ref}`).toBeDefined();
    }
  });

  it('supports the same canonical import for frontend and backend consumers', () => {
    const project = {
      version: 1,
      id: 'project-1',
      name: 'Shared contract',
      revision: '1',
      base_revision: '0',
      created_at: timestamp,
      updated_at: timestamp,
    };
    expect(parseFrontendProject(project)).toEqual(project);
    expect(parseBackendProject(project)).toEqual(project);
  });
});
