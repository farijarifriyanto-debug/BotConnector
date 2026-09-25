import registryJson from "../config/free-provider-registry.json" with { type: "json" };
import type { ProviderId } from "./model-routing.ts";
import { FREE_PROVIDER_IDS } from "./model-routing.ts";

export type FreeProviderAvailability =
  | "recurring_free"
  | "discovered_free"
  | "authorized_free"
  | "dynamic_free"
  | "limited_time_free";

export type FreeProviderDefinition = {
  id: ProviderId;
  displayName: string;
  enabled: boolean;
  baseUrl: string;
  modelsPath: string;
  chatCompletionsPath: string;
  credentialEnv: string;
  availabilityClass: FreeProviderAvailability;
  discovery: "live";
  notes: string;
};

export type ModelProviderCandidate = {
  canonicalModelId: string;
  provider: ProviderId;
  providerModelId: string;
};

const document = registryJson as {
  schema: string;
  policy: {
    modelSelection: string;
    providerFallback: string;
    autoModelSwitch: boolean;
    credentialStorage: string;
    liveDiscoveryRequired: boolean;
  };
  providers: FreeProviderDefinition[];
};

const byId = new Map(document.providers.map((provider) => [provider.id, provider]));

export function listFreeProviders(): FreeProviderDefinition[] {
  return [...document.providers];
}

export function getFreeProvider(id: ProviderId): FreeProviderDefinition {
  const provider = byId.get(id);
  if (!provider) throw new Error("FREE_PROVIDER_NOT_FOUND:" + id);
  return provider;
}

export function freeProviderCredentialState(
  id: ProviderId,
  env: Record<string, string | undefined> = process.env,
): { configured: boolean; envName: string } {
  const provider = getFreeProvider(id);
  return { configured: Boolean(env[provider.credentialEnv]?.trim()), envName: provider.credentialEnv };
}

export function getFreeProviderRuntimeConfig(
  id: ProviderId,
  env: Record<string, string | undefined> = process.env,
): { id: ProviderId; baseUrl: string; apiKey: string; modelsUrl: string; chatCompletionsUrl: string } {
  const provider = getFreeProvider(id);
  const apiKey = env[provider.credentialEnv]?.trim();
  if (!provider.enabled) throw new Error("FREE_PROVIDER_DISABLED:" + id);
  if (!apiKey) throw new Error("FREE_PROVIDER_CREDENTIAL_MISSING:" + id + ":" + provider.credentialEnv);
  return {
    id,
    baseUrl: provider.baseUrl,
    apiKey,
    modelsUrl: provider.baseUrl + provider.modelsPath,
    chatCompletionsUrl: provider.baseUrl + provider.chatCompletionsPath,
  };
}

export function assertSameModelFallback(
  source: ModelProviderCandidate,
  target: ModelProviderCandidate,
): void {
  if (source.canonicalModelId !== target.canonicalModelId) {
    throw new Error("CROSS_MODEL_FALLBACK_BLOCKED:" + source.canonicalModelId + ":" + target.canonicalModelId);
  }
  if (!FREE_PROVIDER_IDS.has(target.provider)) {
    throw new Error("TARGET_NOT_FREE_PROVIDER:" + target.provider);
  }
}

export function filterExactModelFreeCandidates(
  canonicalModelId: string,
  candidates: ModelProviderCandidate[],
): ModelProviderCandidate[] {
  return candidates.filter(
    (candidate) =>
      candidate.canonicalModelId === canonicalModelId &&
      FREE_PROVIDER_IDS.has(candidate.provider) &&
      byId.get(candidate.provider)?.enabled === true,
  );
}

export const freeProviderPolicy = document.policy;
