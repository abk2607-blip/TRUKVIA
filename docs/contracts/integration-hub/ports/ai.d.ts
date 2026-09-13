/**
 * TRUKVIA · AIPort — LLM completion / embedding / chat.
 * Providers: Emergent LLM (default via emergentintegrations), OpenAI,
 * Anthropic, Gemini.
 *
 * DOCUMENTATION ARTEFACT ONLY.
 */
import type { IntegrationContext, Result } from "./common";

export interface AICompleteRequest {
  readonly system?: string;
  readonly prompt: string;
  readonly model_hint?: string;             // "text-fast" | "text-long" | "vision"
  readonly max_tokens?: number;
  readonly temperature?: number;
  readonly cache_key?: string;              // when present → hub caches result
}
export interface AICompleteResult {
  readonly content: string;
  readonly model: string;
  readonly usage: { readonly input_tokens: number; readonly output_tokens: number };
  readonly cached: boolean;
}

export interface AIChatMessage {
  readonly role: "system" | "user" | "assistant";
  readonly content: string;
}
export interface AIChatRequest {
  readonly session_id: string;
  readonly messages: readonly AIChatMessage[];
  readonly model_hint?: string;
}
export interface AIChatResult {
  readonly assistant: AIChatMessage;
  readonly model: string;
  readonly usage: { readonly input_tokens: number; readonly output_tokens: number };
}

export interface AIEmbedRequest {
  readonly text: string;
  readonly model_hint?: string;
}
export interface AIEmbedResult {
  readonly vector: readonly number[];
  readonly model: string;
}

export interface AIPort {
  complete(req: AICompleteRequest, ctx: IntegrationContext): Promise<Result<AICompleteResult>>;
  chat(req: AIChatRequest, ctx: IntegrationContext): Promise<Result<AIChatResult>>;
  embed(req: AIEmbedRequest, ctx: IntegrationContext): Promise<Result<AIEmbedResult>>;
}
