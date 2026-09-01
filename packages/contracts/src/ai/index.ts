import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const AgentRoleSchema = z.enum([
  'planner',
  'designer',
  'coder',
  'researcher',
  'tester',
  'repairer',
  'merger',
]);

export const CapabilityDomainSchema = z.enum([
  'filesystem',
  'runtime',
  'browser',
  'database',
  'deployment',
  'design',
  'research',
]);

export const CapabilityEffectSchema = z.enum([
  'read',
  'write',
  'execute',
  'destructive',
]);

export const CapabilityApprovalSchema = z.enum([
  'automatic',
  'policy',
  'explicit',
]);

export const AgentRunSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  role: AgentRoleSchema,
  state: z.enum(['planned', 'running', 'completed', 'failed', 'cancelled']),
  context_snapshot_id: IdentifierSchema,
  model_route_id: IdentifierSchema,
  ...revisionFields,
  started_at: TimestampSchema.nullable(),
  ended_at: TimestampSchema.nullable(),
});

export const ContextSnapshotSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  project_revision: z.number().int().nonnegative(),
  checkpoint_id: IdentifierSchema.nullable(),
  resource_refs: z.array(z.string().min(1)),
  created_at: TimestampSchema,
});

export const ModelRouteCandidateSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  provider: z.string().min(1),
  model: z.string().min(1),
  priority: z.number().int().nonnegative(),
});

export const ModelRouteSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  selected_candidate_id: IdentifierSchema.nullable(),
  ...revisionFields,
  candidates: z.array(ModelRouteCandidateSchema).min(1),
  created_at: TimestampSchema,
});

export const CapabilitySchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  domain: CapabilityDomainSchema,
  effect: CapabilityEffectSchema,
  approval: CapabilityApprovalSchema,
});

export const AgentRunCapabilitySchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  agent_run_id: IdentifierSchema,
  capability_id: IdentifierSchema,
  granted: z.boolean(),
  approval_reference: IdentifierSchema.nullable(),
});

export type AgentRun = z.infer<typeof AgentRunSchema>;
export type ContextSnapshot = z.infer<typeof ContextSnapshotSchema>;
export type ModelRouteCandidate = z.infer<typeof ModelRouteCandidateSchema>;
export type ModelRoute = z.infer<typeof ModelRouteSchema>;
export type Capability = z.infer<typeof CapabilitySchema>;
export type AgentRunCapability = z.infer<typeof AgentRunCapabilitySchema>;
