import { z } from 'zod';

import {
  IdentifierSchema,
  JsonValueSchema,
  SequenceSchema,
  TimestampSchema,
  contractFields,
} from '../common.js';
import { ActorSchema, GenerationEventSchema } from '../generation/index.js';

export const ChatMessageSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  project_id: IdentifierSchema,
  task_id: IdentifierSchema,
  agent_run_id: IdentifierSchema,
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string().min(1),
  correlation_id: IdentifierSchema,
  causation_id: IdentifierSchema.nullable(),
  created_at: TimestampSchema,
});

export const DomainEventSchema = z.strictObject({
  ...contractFields,
  id: IdentifierSchema,
  type: z.string().min(1),
  sequence: SequenceSchema,
  project_id: IdentifierSchema,
  correlation_id: IdentifierSchema,
  causation_id: IdentifierSchema.nullable(),
  actor: ActorSchema,
  timestamp: TimestampSchema,
  payload: JsonValueSchema,
});

export const EventEnvelopeSchema = z.discriminatedUnion('type', [
  z.strictObject({
    ...contractFields,
    type: z.literal('generation_event'),
    event: GenerationEventSchema,
  }),
  z.strictObject({
    ...contractFields,
    type: z.literal('domain_event'),
    event: DomainEventSchema,
  }),
]);

export const ApiMetadataSchema = z.strictObject({
  ...contractFields,
  request_id: IdentifierSchema,
  timestamp: TimestampSchema,
});

export const ApiResponseEnvelopeSchema = z.strictObject({
  ...contractFields,
  metadata: ApiMetadataSchema,
  data: JsonValueSchema,
});

export const ErrorEnvelopeSchema = z.strictObject({
  ...contractFields,
  metadata: ApiMetadataSchema,
  error: z.strictObject({
    code: z.string().min(1),
    message: z.string().min(1),
    details: JsonValueSchema.nullable(),
  }),
});

export const WebSocketPayloadSchema = EventEnvelopeSchema;

export function validateWebSocketPayload(input: unknown): EventEnvelope {
  return WebSocketPayloadSchema.parse(input);
}

export type EventEnvelope = z.infer<typeof EventEnvelopeSchema>;
export type DomainEvent = z.infer<typeof DomainEventSchema>;
export type ChatMessage = z.infer<typeof ChatMessageSchema>;
export type ApiMetadata = z.infer<typeof ApiMetadataSchema>;
export type ApiResponseEnvelope = z.infer<typeof ApiResponseEnvelopeSchema>;
export type ErrorEnvelope = z.infer<typeof ErrorEnvelopeSchema>;
