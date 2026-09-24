# BotConnector Cloud Efficiency Stack

This public build bundle reduces cloud-provider cost and latency without changing the AI model selected by the user.

## Invariant

If a user selects model A, the request stays on model A. Cache, compression, prompt-cache hints, and MCP tool discovery may reduce work, but never silently switch models.

## Layers

1. Existing exact response cache
2. Bifrost semantic cache, scoped by model and provider
3. LLMLingua-2 context compression
4. lazy-tool MCP discovery to avoid injecting every tool schema
5. Provider-native prompt caching/sticky sessions where supported

## Safety

Semantic cache must also be tenant/policy scoped at integration time. Do not serve semantic hits across tenants, models, providers, or different system policies.

Do not compress the active system/security policy, latest user instruction, tool arguments, IDs, amounts, dates, or exact structured values. Initial compression targets are old history, long RAG passages, and verbose read-only tool output.

This repository builds the reusable components in GitHub Actions. It contains no provider keys and does not deploy to production.
