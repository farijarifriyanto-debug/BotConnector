import { z } from 'zod';

export const ContractVersionSchema = z.literal(1);
export const IdentifierSchema = z.string().min(1);
export const TimestampSchema = z.string().datetime({ offset: true });

const NON_NEGATIVE_DECIMAL_RE = /^[0-9]+$/;

export const RevisionSchema = z.string().regex(
  NON_NEGATIVE_DECIMAL_RE,
  'revision must be a canonical non-negative decimal string',
);

export const SequenceSchema = z.string().regex(
  NON_NEGATIVE_DECIMAL_RE,
  'sequence must be a canonical non-negative decimal string',
);

export const contractFields = {
  version: ContractVersionSchema,
} as const;

export const revisionFields = {
  revision: RevisionSchema,
  base_revision: RevisionSchema,
} as const;

export function revisionedStrictObject<
  const Shape extends z.ZodRawShape & typeof revisionFields,
>(shape: Shape) {
  return z.strictObject(shape).refine(
    (value) => {
      const revisionedValue = value as {
        revision: string;
        base_revision: string;
      };
      return BigInt(revisionedValue.base_revision) <= BigInt(revisionedValue.revision);
    },
    {
      path: ['base_revision'],
      message: 'base_revision must not exceed revision',
    },
  );
}

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export const JsonValueSchema: z.ZodType<JsonValue> = z.lazy(() =>
  z.union([
    z.null(),
    z.boolean(),
    z.number(),
    z.string(),
    z.array(JsonValueSchema),
    z.record(z.string(), JsonValueSchema),
  ]),
);
