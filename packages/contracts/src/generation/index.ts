import { z } from 'zod';

import {
  IdentifierSchema,
  TimestampSchema,
  contractFields,
  revisionFields,
  revisionedStrictObject,
} from '../common.js';

export const GenerationStateSchema = z.enum([
  'planning',
  'running',
  'pausing',
  'paused',
  'stopping',
  'stopped',
  'validating',
  'repairing',
  'completed',
  'failed',
]);

export const RenderTransactionStateSchema = z.enum([
  'open',
  'validating',
  'committed',
  'rejected',
]);

export const SteeringControlSchema = z.enum([
  'current',
  'global_rule',
  'future_requirement',
  'pause',
  'resume',
  'stop',
  'reject',
  'regenerate',
]);

export const SteeringPrioritySchema = z.enum([
  'immediate',
  'safe_point',
  'queued',
]);

export const EventFamilySchema = z.enum([
  'generation',
  'plan',
  'focus',
  'frame',
  'section',
  'component',
  'style',
  'asset',
  'transaction',
  'validation',
  'repair',
  'preview',
  'state',
]);

const eventActionSchema = z.enum(['created', 'updated', 'removed']);

export const GenerationEventPayloadSchema = z.discriminatedUnion('family', [
  z.strictObject({
    ...contractFields,
    family: z.literal('generation'),
    run_id: IdentifierSchema,
    state: GenerationStateSchema,
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('plan'),
    plan_id: IdentifierSchema,
    action: z.enum(['created', 'updated', 'approved']),
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('focus'),
    focus_lock_id: IdentifierSchema,
    action: z.enum(['acquired', 'released']),
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('frame'),
    frame_id: IdentifierSchema,
    action: eventActionSchema,
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('section'),
    section_id: IdentifierSchema,
    action: eventActionSchema,
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('component'),
    component_id: IdentifierSchema,
    action: eventActionSchema,
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('style'),
    target_id: IdentifierSchema,
    action: z.literal('updated'),
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('asset'),
    asset_id: IdentifierSchema,
    action: eventActionSchema,
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('transaction'),
    transaction_id: IdentifierSchema,
    state: RenderTransactionStateSchema,
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('validation'),
    validation_result_id: IdentifierSchema,
    outcome: z.enum(['pass', 'fail']),
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('repair'),
    repair_run_id: IdentifierSchema,
    state: z.enum(['queued', 'running', 'completed', 'failed']),
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('preview'),
    preview_id: IdentifierSchema,
    state: z.enum(['preparing', 'ready', 'failed']),
  }),
  z.strictObject({
    ...contractFields,
    family: z.literal('state'),
    state: GenerationStateSchema,
    previous_state: GenerationStateSchema.nullable(),
  }),
]);

export const ActorSchema = z.strictObject({
  type: z.enum(['user', 'agent', 'system']),
  id: IdentifierSchema,
});

export const GenerationRunSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  state: GenerationStateSchema,
  ...revisionFields,
  started_at: TimestampSchema.nullable(),
  ended_at: TimestampSchema.nullable(),
});

export const GenerationEventSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  sequence: z.number().int().nonnegative(),
  project_id: IdentifierSchema,
  correlation_id: IdentifierSchema,
  causation_id: IdentifierSchema.nullable(),
  actor: ActorSchema,
  timestamp: TimestampSchema,
  payload: GenerationEventPayloadSchema,
});

export const SteeringEventSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  generation_run_id: IdentifierSchema,
  control: SteeringControlSchema,
  priority: SteeringPrioritySchema,
  instruction: z.string().min(1).nullable(),
  created_at: TimestampSchema,
});

export const RenderTransactionSchema = revisionedStrictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  generation_run_id: IdentifierSchema,
  state: RenderTransactionStateSchema,
  ...revisionFields,
  candidate_revision: IdentifierSchema,
  last_known_good_revision: IdentifierSchema.nullable(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export function validateGenerationEventSequence(
  input: readonly unknown[],
): GenerationEvent[] {
  const events = input.map((event) => GenerationEventSchema.parse(event));
  for (let index = 1; index < events.length; index += 1) {
    if (events[index].sequence <= events[index - 1].sequence) {
      throw new Error('GenerationEvent sequence must be strictly monotonic');
    }
  }
  return events;
}

export type GenerationRun = z.infer<typeof GenerationRunSchema>;
export type GenerationEventPayload = z.infer<typeof GenerationEventPayloadSchema>;
export type GenerationEvent = z.infer<typeof GenerationEventSchema>;
export type SteeringEvent = z.infer<typeof SteeringEventSchema>;
export type RenderTransaction = z.infer<typeof RenderTransactionSchema>;
