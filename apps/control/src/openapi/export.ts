import { exportOpenApiDocument } from '@botconnector/contracts';
import { writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const outputPath = resolve(__dirname, '../../../schema/openapi.json');

const baseDoc = exportOpenApiDocument();

const phase3Doc = {
  ...baseDoc,
  info: {
    title: 'BotConnector Control API',
    version: '1.0.0',
    description: 'Phase 3: Project / Artifact Control API',
  },
  paths: {
    '/api/v1/health': {
      get: {
        operationId: 'healthCheck',
        summary: 'Health check',
        tags: ['System'],
        responses: {
          '200': { description: 'Healthy' },
        },
      },
    },
    '/api/v1/projects': {
      post: {
        operationId: 'createProject',
        summary: 'Create a project',
        tags: ['Project'],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/CreateProjectRequest' },
            },
          },
        },
        responses: {
          '201': {
            description: 'Project created',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ProjectResponse' },
              },
            },
          },
          '409': { description: 'Idempotency conflict' },
          '422': { description: 'Validation error' },
        },
      },
      get: {
        operationId: 'listProjects',
        summary: 'List projects',
        tags: ['Project'],
        responses: {
          '200': {
            description: 'List of projects',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ProjectListResponse' },
              },
            },
          },
        },
      },
    },
    '/api/v1/projects/{projectId}': {
      get: {
        operationId: 'getProject',
        summary: 'Get a project',
        tags: ['Project'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'Project details',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ProjectResponse' },
              },
            },
          },
          '404': { description: 'Not found' },
        },
      },
      patch: {
        operationId: 'updateProject',
        summary: 'Update a project',
        tags: ['Project'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/UpdateProjectRequest' },
            },
          },
        },
        responses: {
          '200': {
            description: 'Project updated',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ProjectResponse' },
              },
            },
          },
          '409': { description: 'Revision conflict' },
          '404': { description: 'Not found' },
        },
      },
    },
    '/api/v1/projects/{projectId}/artifacts': {
      post: {
        operationId: 'createArtifact',
        summary: 'Create an artifact',
        tags: ['Artifact'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/CreateArtifactRequest' },
            },
          },
        },
        responses: {
          '201': {
            description: 'Artifact created',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ArtifactResponse' },
              },
            },
          },
          '409': { description: 'Idempotency conflict' },
          '422': { description: 'Validation error' },
        },
      },
      get: {
        operationId: 'listArtifacts',
        summary: 'List artifacts in a project',
        tags: ['Artifact'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'List of artifacts',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ArtifactListResponse' },
              },
            },
          },
        },
      },
    },
    '/api/v1/artifacts/{artifactId}': {
      get: {
        operationId: 'getArtifact',
        summary: 'Get an artifact',
        tags: ['Artifact'],
        parameters: [
          { name: 'artifactId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'Artifact details',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ArtifactResponse' },
              },
            },
          },
          '404': { description: 'Not found' },
        },
      },
      patch: {
        operationId: 'updateArtifact',
        summary: 'Update an artifact',
        tags: ['Artifact'],
        parameters: [
          { name: 'artifactId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/UpdateArtifactRequest' },
            },
          },
        },
        responses: {
          '200': {
            description: 'Artifact updated',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ArtifactResponse' },
              },
            },
          },
          '409': { description: 'Revision conflict' },
          '404': { description: 'Not found' },
        },
      },
    },
    '/api/v1/artifacts/{artifactId}/versions': {
      post: {
        operationId: 'createArtifactVersion',
        summary: 'Create an artifact version',
        tags: ['ArtifactVersion'],
        parameters: [
          { name: 'artifactId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/CreateArtifactVersionRequest' },
            },
          },
        },
        responses: {
          '201': {
            description: 'Artifact version created',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ArtifactVersionResponse' },
              },
            },
          },
          '409': { description: 'Idempotency conflict' },
        },
      },
      get: {
        operationId: 'listArtifactVersions',
        summary: 'List artifact versions',
        tags: ['ArtifactVersion'],
        parameters: [
          { name: 'artifactId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'List of artifact versions',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/ArtifactVersionListResponse' },
              },
            },
          },
        },
      },
    },
    '/api/v1/projects/{projectId}/phases': {
      post: {
        operationId: 'createPhase',
        summary: 'Create a phase',
        tags: ['Phase'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/CreatePhaseRequest' },
            },
          },
        },
        responses: {
          '201': {
            description: 'Phase created',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/PhaseResponse' },
              },
            },
          },
        },
      },
      get: {
        operationId: 'listPhases',
        summary: 'List phases',
        tags: ['Phase'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'List of phases',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/PhaseListResponse' },
              },
            },
          },
        },
      },
    },
    '/api/v1/projects/{projectId}/backlog': {
      post: {
        operationId: 'createBacklogItem',
        summary: 'Create a backlog item',
        tags: ['Backlog'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        requestBody: {
          required: true,
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/CreateBacklogItemRequest' },
            },
          },
        },
        responses: {
          '201': {
            description: 'Backlog item created',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/BacklogItemResponse' },
              },
            },
          },
        },
      },
      get: {
        operationId: 'listBacklogItems',
        summary: 'List backlog items',
        tags: ['Backlog'],
        parameters: [
          { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
        ],
        responses: {
          '200': {
            description: 'List of backlog items',
            content: {
              'application/json': {
                schema: { $ref: '#/components/schemas/BacklogItemListResponse' },
              },
            },
          },
        },
      },
    },
  },
  components: {
    ...baseDoc.components,
    schemas: {
      ...baseDoc.components.schemas,
      CreateProjectRequest: {
        type: 'object',
        required: ['name'],
        properties: {
          name: { type: 'string', minLength: 1 },
        },
      },
      UpdateProjectRequest: {
        type: 'object',
        required: ['name', 'revision'],
        properties: {
          name: { type: 'string', minLength: 1 },
          revision: { type: 'integer', minimum: 0 },
        },
      },
      ProjectResponse: {
        type: 'object',
        properties: {
          data: { $ref: '#/components/schemas/Project' },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      ProjectListResponse: {
        type: 'object',
        properties: {
          data: { type: 'array', items: { $ref: '#/components/schemas/Project' } },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      CreateArtifactRequest: {
        type: 'object',
        required: ['type'],
        properties: {
          type: { $ref: '#/components/schemas/ArtifactType' },
        },
      },
      UpdateArtifactRequest: {
        type: 'object',
        required: ['revision'],
        properties: {
          lifecycle: { $ref: '#/components/schemas/ArtifactLifecycle' },
          revision: { type: 'integer', minimum: 0 },
        },
      },
      ArtifactResponse: {
        type: 'object',
        properties: {
          data: { $ref: '#/components/schemas/ArtifactManifest' },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      ArtifactListResponse: {
        type: 'object',
        properties: {
          data: { type: 'array', items: { $ref: '#/components/schemas/ArtifactManifest' } },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      CreateArtifactVersionRequest: {
        type: 'object',
        required: ['source_revision', 'content_hash'],
        properties: {
          source_revision: { type: 'string', minLength: 1 },
          content_hash: { type: 'string', minLength: 1 },
        },
      },
      ArtifactVersionResponse: {
        type: 'object',
        properties: {
          data: { $ref: '#/components/schemas/ArtifactVersion' },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      ArtifactVersionListResponse: {
        type: 'object',
        properties: {
          data: { type: 'array', items: { $ref: '#/components/schemas/ArtifactVersion' } },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      CreatePhaseRequest: {
        type: 'object',
        required: ['name'],
        properties: {
          name: { type: 'string', minLength: 1 },
          ordinal: { type: 'integer', minimum: 0 },
        },
      },
      PhaseResponse: {
        type: 'object',
        properties: {
          data: { $ref: '#/components/schemas/Phase' },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      PhaseListResponse: {
        type: 'object',
        properties: {
          data: { type: 'array', items: { $ref: '#/components/schemas/Phase' } },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      CreateBacklogItemRequest: {
        type: 'object',
        required: ['title'],
        properties: {
          title: { type: 'string', minLength: 1 },
          description: { type: 'string', default: '' },
          target_phase: { type: 'string', nullable: true },
        },
      },
      BacklogItemResponse: {
        type: 'object',
        properties: {
          data: { $ref: '#/components/schemas/BacklogItem' },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      BacklogItemListResponse: {
        type: 'object',
        properties: {
          data: { type: 'array', items: { $ref: '#/components/schemas/BacklogItem' } },
          meta: { $ref: '#/components/schemas/ApiMetadata' },
        },
      },
      ErrorResponse: {
        type: 'object',
        properties: {
          error: {
            type: 'object',
            required: ['code', 'message', 'request_id'],
            properties: {
              code: { type: 'string' },
              message: { type: 'string' },
              request_id: { type: 'string' },
              details: {},
            },
          },
        },
      },
    },
  },
};

writeFileSync(outputPath, JSON.stringify(phase3Doc, null, 2) + '\n');
console.log(`OpenAPI spec written to ${outputPath}`);
