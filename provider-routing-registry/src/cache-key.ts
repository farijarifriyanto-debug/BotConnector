import { createHash } from "node:crypto";

export type ExactCacheKeyInput = {
  tenantId: string;
  canonicalModelId: string;
  providerId: string;
  providerModelId: string;
  modelVersion?: string | null;
  policyVersion: string;
  responseMode: "stream" | "non-stream";
  messages: unknown;
  tools?: unknown;
  temperature?: number | null;
  topP?: number | null;
  maxTokens?: number | null;
  responseFormat?: unknown;
  reasoning?: unknown;
};

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => [key, canonicalize(item)]);
    return Object.fromEntries(entries);
  }
  return value;
}

function required(value: string, field: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error("CACHE_KEY_FIELD_REQUIRED:" + field);
  return trimmed;
}

export function buildExactResponseCacheKey(input: ExactCacheKeyInput): string {
  const safe = {
    tenantId: required(input.tenantId, "tenantId"),
    canonicalModelId: required(input.canonicalModelId, "canonicalModelId"),
    providerId: required(input.providerId, "providerId"),
    providerModelId: required(input.providerModelId, "providerModelId"),
    modelVersion: input.modelVersion ?? null,
    policyVersion: required(input.policyVersion, "policyVersion"),
    responseMode: input.responseMode,
    messages: input.messages,
    tools: input.tools ?? null,
    temperature: input.temperature ?? null,
    topP: input.topP ?? null,
    maxTokens: input.maxTokens ?? null,
    responseFormat: input.responseFormat ?? null,
    reasoning: input.reasoning ?? null,
  };
  const digest = createHash("sha256").update(JSON.stringify(canonicalize(safe))).digest("hex");
  return "bc:exact:v1:" + digest;
}
