export type Role = 'system' | 'user' | 'assistant' | 'tool';
export interface ClientOptions { baseUrl?: string; apiKey?: string; timeoutMs?: number; }
export interface ChatMessage { role: Role; content: string | null | Array<Record<string, unknown>>; tool_call_id?: string; tool_calls?: Array<Record<string, unknown>>; }
export interface ChatRequest { model: string; messages: ChatMessage[]; temperature?: number; max_tokens?: number; }
export interface ChatChoice { index: number; message?: ChatMessage; delta?: Partial<ChatMessage>; finish_reason?: string | null; }
export interface ChatCompletion { id?: string; object?: string; choices: ChatChoice[]; usage?: Record<string, number>; }
export interface EmbeddingRequest { model: string; input: string | string[]; }
export interface EmbeddingResponse { data: Array<{ index: number; object: string; embedding: number[] }>; model?: string; usage?: Record<string, number>; }
export class BotConnectorError extends Error { status: number; code: string; body: unknown; }
export class BotConnectorClient {
  constructor(options?: ClientOptions);
  models: { list(): Promise<Record<string, unknown>>; get(id: string): Promise<Record<string, unknown>> };
  chat: { create(request: ChatRequest, options?: { signal?: AbortSignal }): Promise<ChatCompletion>; stream(request: ChatRequest, options?: { signal?: AbortSignal }): AsyncGenerator<ChatCompletion> };
  embeddings: { create(request: EmbeddingRequest, options?: { signal?: AbortSignal }): Promise<EmbeddingResponse> };
  runtime: { status(): Promise<{ healthy: boolean; status: string; models: Record<string, unknown> | null }> };
  tools: { list(): Promise<Array<{ name: string; description: string; source: string; permission: string }>> };
}
