import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const TaskStateSchema = z.enum([
  'draft',
  'approved',
  'queued',
  'active',
  'validating',
  'ready',
  'applying',
  'done',
  'cancelled',
  'failed',
]);

export const PhaseSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  ordinal: z.number().int().nonnegative(),
  name: z.string().min(1),
  active: z.boolean(),
  ...revisionFields,
  created_at: TimestampSchema,
});

export const TaskSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  phase_id: IdentifierSchema,
  title: z.string().min(1),
  state: TaskStateSchema,
  ...revisionFields,
  acceptance_contract_id: IdentifierSchema.nullable(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export const TaskDependencySchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  depends_on_task_id: IdentifierSchema,
  created_at: TimestampSchema,
});

export const FocusLockSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  scope: z.string().min(1),
  owner_id: IdentifierSchema,
  ...revisionFields,
  acquired_at: TimestampSchema,
  expires_at: TimestampSchema.nullable(),
});

export const BacklogItemSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  title: z.string().min(1),
  description: z.string(),
  target_phase: z.string().min(1).nullable(),
  created_at: TimestampSchema,
});

export const AcceptanceCriterionSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  description: z.string().min(1),
  required: z.boolean(),
});

export const AcceptanceContractSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  ...revisionFields,
  criteria: z.array(AcceptanceCriterionSchema).min(1),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export type Phase = z.infer<typeof PhaseSchema>;
export type Task = z.infer<typeof TaskSchema>;
export type TaskDependency = z.infer<typeof TaskDependencySchema>;
export type FocusLock = z.infer<typeof FocusLockSchema>;
export type BacklogItem = z.infer<typeof BacklogItemSchema>;
export type AcceptanceCriterion = z.infer<typeof AcceptanceCriterionSchema>;
export type AcceptanceContract = z.infer<typeof AcceptanceContractSchema>;
