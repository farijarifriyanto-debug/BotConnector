import { exportOpenApiDocument } from '@botconnector/contracts';
import type { FastifyInstance } from 'fastify';

export function registerOpenApiRoutes(app: FastifyInstance): void {
  app.get('/api/v1/openapi.json', async (_request, reply) => {
    const baseDoc = exportOpenApiDocument();

    const phase3Doc = {
      ...baseDoc,
      info: {
        title: 'BotConnector Control API',
        version: '1.0.0',
        description: 'Phase 3: Project / Artifact Control API',
      },
      paths: {
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
        '/api/v1/projects/{projectId}/canvases': {
          post: {
            operationId: 'createCanvas',
            summary: 'Create a declarative UI-IR canvas',
            tags: ['Canvas'],
            parameters: [
              { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
            ],
            requestBody: {
              required: true,
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/CreateCanvasRequest' },
                },
              },
            },
            responses: {
              '201': { description: 'Canvas created', content: { 'application/json': { schema: { $ref: '#/components/schemas/CanvasResponse' } } } },
              '404': { description: 'Artifact not found' },
              '422': { description: 'Validation error' },
            },
          },
          get: {
            operationId: 'listCanvases',
            summary: 'List canvases in a project',
            tags: ['Canvas'],
            parameters: [
              { name: 'projectId', in: 'path', required: true, schema: { type: 'string' } },
            ],
            responses: {
              '200': { description: 'Canvas list', content: { 'application/json': { schema: { $ref: '#/components/schemas/CanvasListResponse' } } } },
            },
          },
        },
        '/api/v1/canvases/{canvasId}': {
          get: {
            operationId: 'getCanvas',
            summary: 'Get a canvas',
            tags: ['Canvas'],
            parameters: [
              { name: 'canvasId', in: 'path', required: true, schema: { type: 'string' } },
            ],
            responses: {
              '200': { description: 'Canvas', content: { 'application/json': { schema: { $ref: '#/components/schemas/CanvasResponse' } } } },
              '404': { description: 'Not found' },
            },
          },
        },
        '/api/v1/canvases/{canvasId}/selections': {
          post: {
            operationId: 'createCanvasSelection',
            summary: 'Create a revision-bound selection',
            tags: ['Canvas'],
            parameters: [
              { name: 'canvasId', in: 'path', required: true, schema: { type: 'string' } },
            ],
            requestBody: {
              required: true,
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/CreateSelectionRequest' },
                },
              },
            },
            responses: {
              '201': { description: 'Selection created', content: { 'application/json': { schema: { $ref: '#/components/schemas/SelectionResponse' } } } },
              '404': { description: 'Not found' },
              '409': { description: 'Revision conflict' },
              '422': { description: 'Validation error' },
            },
          },
        },
        '/api/v1/canvases/{canvasId}/direct-edits': {
          post: {
            operationId: 'applyCanvasDirectEdit',
            summary: 'Apply a deterministic direct edit',
            tags: ['Canvas'],
            parameters: [
              { name: 'canvasId', in: 'path', required: true, schema: { type: 'string' } },
              { name: 'If-Match', in: 'header', required: true, schema: { type: 'string' } },
            ],
            requestBody: {
              required: true,
              content: {
                'application/json': {
                  schema: { $ref: '#/components/schemas/DirectEditRequest' },
                },
              },
            },
            responses: {
              '200': { description: 'Edit applied', content: { 'application/json': { schema: { $ref: '#/components/schemas/DirectEditResponse' } } } },
              '404': { description: 'Not found' },
              '409': { description: 'Revision conflict' },
              '422': { description: 'Validation error' },
            },
          },
        },
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
          CreateCanvasRequest: {
            type: 'object',
            required: ['artifact_id', 'root_node_id', 'nodes'],
            properties: {
              artifact_id: { type: 'string', minLength: 1 },
              root_node_id: { type: 'string', minLength: 1 },
              nodes: { type: 'array', items: { $ref: '#/components/schemas/UIIRNode' }, minItems: 1 },
            },
            additionalProperties: false,
          },
          CanvasResponse: {
            type: 'object',
            properties: {
              data: { $ref: '#/components/schemas/UIIR' },
              meta: { $ref: '#/components/schemas/ApiMetadata' },
            },
          },
          CanvasListResponse: {
            type: 'object',
            properties: {
              data: { type: 'array', items: { $ref: '#/components/schemas/UIIR' } },
              meta: { $ref: '#/components/schemas/ApiMetadata' },
            },
          },
          CreateSelectionRequest: {
            type: 'object',
            required: ['uiir_revision', 'selected_node_ids'],
            properties: {
              uiir_revision: { type: 'string', pattern: '^[0-9]+$' },
              selected_node_ids: { type: 'array', items: { type: 'string' }, minItems: 1 },
              primary_node_id: { type: 'string', nullable: true },
            },
            additionalProperties: false,
          },
          SelectionResponse: {
            type: 'object',
            properties: {
              data: { $ref: '#/components/schemas/SelectionContext' },
              meta: { $ref: '#/components/schemas/ApiMetadata' },
            },
          },
          DirectEditRequest: {
            type: 'object',
            required: ['selection', 'target', 'value'],
            properties: {
              selection: { $ref: '#/components/schemas/CreateSelectionRequest' },
              target: { type: 'string', enum: ['content', 'layout', 'style', 'tokens'] },
              path: { type: 'array', items: { type: 'string' } },
              value: {},
            },
            additionalProperties: false,
          },
          DirectEditResponse: {
            type: 'object',
            properties: {
              data: {
                type: 'object',
                properties: {
                  canvas: { $ref: '#/components/schemas/UIIR' },
                  selection: { $ref: '#/components/schemas/SelectionContext' },
                  command: { $ref: '#/components/schemas/DirectEditCommand' },
                },
              },
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

    reply.header('Content-Type', 'application/json');
    reply.send(phase3Doc);
  });
}
