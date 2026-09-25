export type Role = 'system' | 'user' | 'assistant' | 'tool';
export interface ClientOptions { baseUrl?: string; apiKey?: string; timeoutMs?: number; }
export interface ChatMessage { role: Role; content: string | null | Array<Record<string, unknown>>; tool_call_id?: string; tool_calls?: Array<Record<string, unknown>>; }
export interface ChatRequest { model: string; messages: ChatMessage[]; temperature?: number; max_tokens?: number; }
export interface ChatChoice { index: number; message?: ChatMessage; delta?: Partial<ChatMessage>; finish_reason?: string | null; }
export interface ChatCompletion { id?: string; object?: string; choices: ChatChoice[]; usage?: Record<string, number>; }
export interface EmbeddingRequest { model: string; input: string | string[]; }
export interface EmbeddingResponse { data: Array<{ index: number; object: string; embedding: number[] }>; model?: string; usage?: Record<string, number>; }
export interface CloudProviderState { provider: string; state: string; successEma: number; latencyEmaMs: number | null; four29Rate: number; five00Rate: number; circuitOpen: boolean; openUntil: number | null; }
export interface CloudModel { modelId: string; provider: string; displayName?: string; capabilities?: string[]; context?: number | null; modality?: string; pricing?: { inputPerMillion: number | null; cachedInputPerMillion?: number | null; outputPerMillion: number | null; source?: string } | null; availability?: string; stale?: boolean; fetchedAt?: string; }
export interface CloudUsageSummary { requests: number; totals: { inputTokens: number; outputTokens: number }; byProvider: Record<string, number>; estimatedCost: number; unknownCostRecords: number; }
export class BotConnectorError extends Error { status: number; code: string; body: unknown; }
export class BotConnectorClient {
  constructor(options?: ClientOptions);
  models: { list(): Promise<Record<string, unknown>>; get(id: string): Promise<Record<string, unknown>> };
  chat: { create(request: ChatRequest, options?: { signal?: AbortSignal }): Promise<ChatCompletion>; stream(request: ChatRequest, options?: { signal?: AbortSignal }): AsyncGenerator<ChatCompletion> };
  embeddings: { create(request: EmbeddingRequest, options?: { signal?: AbortSignal }): Promise<EmbeddingResponse> };
  runtime: { status(): Promise<{ healthy: boolean; status: string; models: Record<string, unknown> | null }> };
  tools: { list(): Promise<Array<{ name: string; description: string; source: string; permission: string }>> };
  cloud: {
    status(): Promise<{ configured: boolean; credentials: Record<string, { configured: boolean; source: string; envName: string | null }>; health: Record<string, CloudProviderState>; catalog: { total: number; overlap: number; unique: number }; commercialLaunchApproved: boolean }>;
    providers(): Promise<Record<string, Record<string, unknown>>>;
    models(options?: { refresh?: boolean; provider?: string }): Promise<{ models: CloudModel[]; stale?: boolean; fetchedAt?: string | null; count?: number; refresh?: Record<string, unknown> }>;
    usage(options?: { limit?: number }): Promise<{ summary: CloudUsageSummary; recent: Record<string, unknown>[] }>;
    routing(): Promise<Record<string, unknown>>;
    chat(request: ChatRequest): Promise<ChatCompletion & { _meta?: Record<string, unknown> }>;
  };
}
