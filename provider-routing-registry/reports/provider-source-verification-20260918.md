# First-party provider source verification — 2026-09-18

Only current first-party pages were used for `verified=true`. Comparative or stale values remain `REVIEW_REQUIRED`.

| Provider / models | Evidence | Registry result |
|---|---|---|
| DeepInfra: DeepSeek V4.1 Flash, GLM 5.3/5.3 Flash, GLM 5.2, MiniMax M3 | [DeepInfra model pages](https://deepinfra.com/), [MiniMax M3](https://deepinfra.com/MiniMaxAI/MiniMax-M3) | DeepSeek verified list; GLM discounts recorded as promotions; MiniMax exact route and current price verified. |
| Inference.net: Kimi K3 | [Kimi K3 model page](https://inference.net/models/kimi-k3) | Exact model ID, availability, context, tools, vision, cache-read and current price verified. |
| Alibaba Model Studio: Qwen3.8 Flash | [Qwen3.8 Flash model info](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-flash), [pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing) | Global route verified with explicit Beijing, Singapore, Hong Kong, Frankfurt, Tokyo, and Virginia prices plus cache dimensions. |
| Alibaba Model Studio: selected Qwen3.5/Qwen3 tiers | [Model pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing) | Tier values refreshed where exact first-party evidence was available; route remains static. |
| Novita: DeepSeek V3.2, Ling VL/Sante | [Novita model library](https://novita.ai/models) | DeepSeek verified; Ling promotions recorded as time-limited. VL has published 2026-09-23 expiry; Sante remains reverify-required because expiry is not published. |
| OpenAI: GPT-5.6 Luna/Terra/Sol | [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [GPT-5.6 pricing announcement](https://openai.com/index/gpt-5-6/) | Exact IDs, model availability, current rates, cache policy, and Sol reference rate recorded. Sol remains promotion/reverify-required. |
| Anthropic: Claude Sonnet 5, Claude Opus 5 | [Sonnet 5](https://www.anthropic.com/news/claude-sonnet-5), [Opus 5](https://www.anthropic.com/news/claude-opus-5) | Exact IDs and current input/output rates verified; cache dimensions remain explicit unknown/null where the checked source did not publish exact values. |
| Xiaomi MiMo V2.5 | [Official model list](https://mimo.mi.com/docs/en-US/api/model/list-models), [release](https://mimo.mi.com/docs/en-US/news/latest/v2.5-open-sourced) | Exact direct model ID and 1M context verified; no trusted token price recorded from the checked first-party sources. |
| Together, Chutes, remaining Novita/DeepInfra/Inference.net offers | Provider official pricing/model pages where available | Competing offers were retained or added only when exact evidence was available; unsupported selected values remain `REVIEW_REQUIRED`. |

## Safety decisions

- `actualProviderPrice` is used for trusted estimation and settlement metadata.
- `standardReferencePrice` is not actual provider cost and is never substituted into settlement.
- Cache read/write rates are null unless the provider source explicitly publishes them.
- A promotion with unknown expiry is not trusted for production billing.
- No provider key, funding action, production database, deployment, or route migration was performed.

## Explicit primary route change

```text
OLD_PROVIDER=together
NEW_PROVIDER=deepinfra
MODEL=minimax-m3
ELIGIBILITY=exact DeepInfra model page, available, 1M context
COST_PROFILE=DeepInfra actual $0.28/M input, $1.10/M output, cache read $0.056/M
CAPABILITY_MATCH=multimodal/reasoning evidence on provider model page; tools remains unknown
REGION=global metadata; no unsupported region claim
PRIVACY=provider page indicates hosted model/ZDR metadata; registry does not promote it to a canonical product privacy guarantee
OFFICIAL_SOURCES=https://deepinfra.com/MiniMaxAI/MiniMax-M3
REASON_FOR_CHANGE=launch route requires DeepInfra and exact first-party evidence exists; Together offer remains as a non-primary alternative
```
