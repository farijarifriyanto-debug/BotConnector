import { z } from 'zod';

import {
  AgentRunCapabilitySchema,
  AgentRunSchema,
  CapabilitySchema,
  ContextSnapshotSchema,
  ModelRouteCandidateSchema,
  ModelRouteSchema,
} from './ai/index.js';
import { ChangeOperationSchema, ChangesetSchema } from './change/index.js';
import {
  ArtifactManifestSchema,
  ArtifactVersionSchema,
  CheckpointSchema,
  ProjectSchema,
} from './core/index.js';
import { DeploymentSchema } from './deploy/index.js';
import {
  DesignDecisionSchema,
  ProjectMemoryRevisionSchema,
  SelectionContextSchema,
  UIIRNodeSchema,
  UIIRSchema,
} from './design/index.js';
import {
  GenerationEventSchema,
  GenerationRunSchema,
  RenderTransactionSchema,
  SteeringEventSchema,
} from './generation/index.js';
import {
  ApiMetadataSchema,
  ApiResponseEnvelopeSchema,
  ChatMessageSchema,
  DomainEventSchema,
  ErrorEnvelopeSchema,
  EventEnvelopeSchema,
} from './transport/index.js';
import {
  FailureSignatureSchema,
  RepairRunSchema,
  ValidationResultSchema,
  ValidationStageResultSchema,
} from './validation/index.js';
import {
  AcceptanceContractSchema,
  AcceptanceCriterionSchema,
  BacklogItemSchema,
  FocusLockSchema,
  PhaseSchema,
  TaskDependencySchema,
  TaskSchema,
} from './work/index.js';

export const contractSchemas = {
  Project: ProjectSchema,
  ArtifactManifest: ArtifactManifestSchema,
  ArtifactVersion: ArtifactVersionSchema,
  Checkpoint: CheckpointSchema,
  Phase: PhaseSchema,
  Task: TaskSchema,
  TaskDependency: TaskDependencySchema,
  FocusLock: FocusLockSchema,
  BacklogItem: BacklogItemSchema,
  AcceptanceContract: AcceptanceContractSchema,
  AcceptanceCriterion: AcceptanceCriterionSchema,
  GenerationRun: GenerationRunSchema,
  GenerationEvent: GenerationEventSchema,
  SteeringEvent: SteeringEventSchema,
  RenderTransaction: RenderTransactionSchema,
  UIIR: UIIRSchema,
  UIIRNode: UIIRNodeSchema,
  SelectionContext: SelectionContextSchema,
  DesignDecision: DesignDecisionSchema,
  ProjectMemoryRevision: ProjectMemoryRevisionSchema,
  AgentRun: AgentRunSchema,
  ContextSnapshot: ContextSnapshotSchema,
  ModelRoute: ModelRouteSchema,
  ModelRouteCandidate: ModelRouteCandidateSchema,
  Capability: CapabilitySchema,
  AgentRunCapability: AgentRunCapabilitySchema,
  Changeset: ChangesetSchema,
  ChangeOperation: ChangeOperationSchema,
  ValidationResult: ValidationResultSchema,
  ValidationStageResult: ValidationStageResultSchema,
  FailureSignature: FailureSignatureSchema,
  RepairRun: RepairRunSchema,
  Deployment: DeploymentSchema,
  ChatMessage: ChatMessageSchema,
  EventEnvelope: EventEnvelopeSchema,
  DomainEvent: DomainEventSchema,
  ErrorEnvelope: ErrorEnvelopeSchema,
  ApiMetadata: ApiMetadataSchema,
  ApiResponseEnvelope: ApiResponseEnvelopeSchema,
} as const;

export const CONTRACT_COUNT = Object.keys(contractSchemas).length;

function escapeJsonPointerToken(value: string): string {
  return value.replaceAll('~', '~0').replaceAll('/', '~1');
}

function rebaseLocalRefs<T>(value: T, baseRef: string): T {
  if (Array.isArray(value)) {
    return value.map((item) => rebaseLocalRefs(item, baseRef)) as T;
  }
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [
        key,
        key === '$ref' && typeof child === 'string' && child.startsWith('#')
          ? `${baseRef}${child.slice(1)}`
          : rebaseLocalRefs(child, baseRef),
      ]),
    ) as T;
  }
  return value;
}

function exportSchemas(baseRef: (id: string) => string) {
  return Object.fromEntries(
    Object.entries(contractSchemas).map(([id, schema]) => [
      id,
      rebaseLocalRefs(
        z.toJSONSchema(schema, { target: 'draft-2020-12' }),
        baseRef(escapeJsonPointerToken(id)),
      ),
    ]),
  );
}

export function exportJsonSchemaBundle() {
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $defs: exportSchemas((id) => `#/$defs/${id}`),
  };
}

export function exportOpenApiDocument() {
  return {
    openapi: '3.1.0' as const,
    info: {
      title: 'BotConnector Shared Contracts',
      version: '1.0.0',
    },
    paths: {},
    components: {
      schemas: exportSchemas((id) => `#/components/schemas/${id}`),
    },
  };
}
