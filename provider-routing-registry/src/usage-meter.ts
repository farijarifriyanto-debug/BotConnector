export type ProviderUsagePayload = {
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  prompt_tokens_details?: {
    cached_tokens?: number | null;
    cache_write_tokens?: number | null;
    cache_creation_tokens?: number | null;
    cache_creation?: {
      ephemeral_5m_input_tokens?: number | null;
      ephemeral_1h_input_tokens?: number | null;
    } | null;
  } | null;
  cache_read_input_tokens?: number | null;
  cache_creation_input_tokens?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  input_tokens_details?: {
    cached_tokens?: number | null;
  } | null;
};

export type NormalizedUsage = {
  logicalInputTokens: number;
  freshInputTokens: number;
  cachedInputTokens: number;
  cacheWriteTokens: number;
  outputTokens: number;
  totalLogicalTokens: number;
  cacheHitRate: number;
};

function tokenCount(value: unknown): number {
  if (value == null) return 0;
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw new Error("USAGE_TOKEN_COUNT_INVALID");
  return Number(value);
}

export function normalizeProviderUsage(usage: ProviderUsagePayload): NormalizedUsage {
  const logicalInputTokens = tokenCount(usage.prompt_tokens ?? usage.input_tokens ?? 0);
  const outputTokens = tokenCount(usage.completion_tokens ?? usage.output_tokens ?? 0);

  const cachedInputTokens = tokenCount(
    usage.prompt_tokens_details?.cached_tokens ??
      usage.input_tokens_details?.cached_tokens ??
      usage.cache_read_input_tokens ??
      0,
  );

  const ttlWriteTokens =
    tokenCount(usage.prompt_tokens_details?.cache_creation?.ephemeral_5m_input_tokens ?? 0) +
    tokenCount(usage.prompt_tokens_details?.cache_creation?.ephemeral_1h_input_tokens ?? 0);

  const cacheWriteTokens = tokenCount(
    usage.prompt_tokens_details?.cache_write_tokens ??
      usage.prompt_tokens_details?.cache_creation_tokens ??
      usage.cache_creation_input_tokens ??
      ttlWriteTokens,
  );

  if (cachedInputTokens > logicalInputTokens) {
    throw new Error("CACHED_TOKENS_EXCEED_LOGICAL_INPUT");
  }

  const freshInputTokens = logicalInputTokens - cachedInputTokens;
  const totalLogicalTokens = logicalInputTokens + outputTokens;

  return {
    logicalInputTokens,
    freshInputTokens,
    cachedInputTokens,
    cacheWriteTokens,
    outputTokens,
    totalLogicalTokens,
    cacheHitRate: logicalInputTokens === 0 ? 0 : cachedInputTokens / logicalInputTokens,
  };
}
