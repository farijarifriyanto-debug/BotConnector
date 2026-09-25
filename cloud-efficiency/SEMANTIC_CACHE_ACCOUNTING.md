# Semantic Cache Accounting Contract

Status: **required before authenticated live-provider cutover**

## Placement

Bifrost semantic response caching MUST NOT sit in front of the BotConnector authentication/quota gateway.

Required logical order:

```
authenticated request
  -> BotConnector auth/privacy checks
  -> quota/billing reservation
  -> existing exact-cache fast path
  -> trusted semantic-cache boundary
  -> selected provider/model
  -> cache-aware settlement
```

The user-selected model remains immutable.

## Why

BotConnector already performs cache-aware settlement:

```
charged_tokens = logical_input_tokens - cached_input_tokens + output_tokens
```

Cache-read input is telemetry but is not charged a second time. Cache-write input remains uncached input.

Bifrost semantic response-cache hits currently expose the hit in:

```
extra_fields.cache_debug.cache_hit = true
extra_fields.cache_debug.hit_type = "semantic" | "direct"
```

A Bifrost full response-cache hit still carries the original OpenAI-compatible
`usage.prompt_tokens` and `usage.completion_tokens`. It does not expose that
full response-cache hit as `usage.cached_input_tokens`.

Therefore a naive BotConnector OpenAI-compatible client would charge the
logical prompt as uncached even though Bifrost did not call the model provider.

## Trusted normalization rule

Only at a BotConnector-owned Bifrost boundary:

- if `cache_debug.cache_hit == true` and `hit_type` is `semantic` or `direct`:
  - `logical_input_tokens = usage.prompt_tokens`
  - `cached_input_tokens = usage.prompt_tokens`
  - `cache_write_tokens = 0`
  - `output_tokens = usage.completion_tokens`
- otherwise preserve provider-reported cache fields unchanged.

Example:

```
Bifrost full response-cache hit
prompt_tokens=100
completion_tokens=10
cache_hit=true

=> settle:
input_tokens=100
cached_input_tokens=100
cache_write_tokens=0
output_tokens=10

=> allowance debit = 10
```

Output remains counted. This is consistent with the existing BotConnector
cache-aware quota contract; only input known to have avoided provider inference
is discounted.

## Security boundary

Do not add a generic rule that trusts `extra_fields.cache_debug` from arbitrary
external OpenAI-compatible providers. A malicious or misconfigured upstream
could otherwise falsify cache accounting.

The normalization must be scoped to a BotConnector-owned internal Bifrost route
or a dedicated gateway client type whose upstream identity is configuration-
trusted.

## Required tests before live cutover

1. Bifrost miss: input and output settle normally.
2. Semantic hit: all logical input is reported as cached; output remains charged.
3. Direct response-cache hit: same rule as semantic hit.
4. Provider prompt-cache hit without Bifrost response hit: preserve the
   provider's partial cached-input count.
5. Bifrost full response hit whose stored original response already had partial
   provider caching: full logical input is cached because no provider call is
   made on replay.
6. Untrusted provider with forged `cache_debug.cache_hit=true`: no semantic
   accounting discount.
7. Streaming semantic hit: cache metadata and final usage settle exactly once.
8. Request ID/user binding and reserve/settle/release idempotency remain intact.

## Current blocker

The accepted production gateway source is a provenance snapshot of a dirty
historical worktree and does not currently have a canonical Git repository with
the exact deployed source hash. Do not patch an older worktree or the running
container to work around this.

Promote the accepted gateway snapshot into a canonical repository first, then
implement this contract there and build it through CI.
