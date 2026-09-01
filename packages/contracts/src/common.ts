import { z } from 'zod';

export const ContractVersionSchema = z.literal(1);
export const IdentifierSchema = z.string().min(1);
export const TimestampSchema = z.string().datetime({ offset: true });
export const RevisionSchema = z.number().int().nonnegative();

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
        revision: number;
        base_revision: number;
      };
      return revisionedValue.base_revision <= revisionedValue.revision;
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
