import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const ValidationStageSchema = z.enum([
  'parse',
  'typecheck',
  'build',
  'runtime',
  'browser',
  'console',
  'accessibility',
  'regression',
]);

export const ValidationStageResultSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  stage: ValidationStageSchema,
  outcome: z.enum(['pass', 'fail', 'skipped']),
  duration_ms: z.number().int().nonnegative(),
  message: z.string().nullable(),
});

export const ValidationResultSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  changeset_id: IdentifierSchema,
  outcome: z.enum(['pass', 'fail']),
  ...revisionFields,
  stages: z.array(ValidationStageResultSchema).min(1),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export const FailureSignatureSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  stage: ValidationStageSchema,
  code: z.string().min(1),
  fingerprint: z.string().min(1),
  message: z.string().min(1),
  created_at: TimestampSchema,
});

export const RepairRunSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  failure_signature_id: IdentifierSchema,
  changeset_id: IdentifierSchema.nullable(),
  state: z.enum(['queued', 'running', 'completed', 'failed']),
  ...revisionFields,
  started_at: TimestampSchema.nullable(),
  ended_at: TimestampSchema.nullable(),
});

export type ValidationStageResult = z.infer<typeof ValidationStageResultSchema>;
export type ValidationResult = z.infer<typeof ValidationResultSchema>;
export type FailureSignature = z.infer<typeof FailureSignatureSchema>;
export type RepairRun = z.infer<typeof RepairRunSchema>;
