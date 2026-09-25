# Provider route audit — 2026-09-18

The Product Model Registry owns canonical identity, family, capabilities, status, and Cloud/Browser/Device availability. This registry owns only the locked Cloud provider, provider model ID, eligibility evidence, and trusted provider price metadata.

`selectionPolicy=reviewed-static-primary`; pricing drift is `REVIEW_ONLY` and never mutates a route.

BASELINE_PRICE_REVERIFY_REQUIRED_AUDITED=58/58

## Launch acceptance

```text
LAUNCH_ROUTE_COUNT=12
LAUNCH_ROUTE_EXACT_PROVIDER_VERIFIED=12/12
LAUNCH_ROUTE_PRICE_VERIFIED=11/12
LAUNCH_ROUTE_REGION_VERIFIED=1/12
LAUNCH_ROUTE_PROMOTION_STATUS_VERIFIED=3/3
LAUNCH_ROUTE_CACHE_PRICING_VERIFIED=7/12
COMMERCIAL_POLICY_INPUT=PENDING_SEPARATE_INTEGRATION
```

The Xiaomi model/provider identity is verified from Xiaomi's official model API, but its price remains `REVIEW_REQUIRED` because the checked first-party source did not publish a token rate. Region verification is counted only where the first-party source explicitly enumerates the route region. GPT-5.6 Sol is a current promotion with a separate reference rate and is not billable until promotion freshness is rechecked.

## Route table

### deepseek-v4.1-flash [LAUNCH]

MODEL=deepseek-v4.1-flash
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V4.1-Flash
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1048576
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### deepseek-v4-flash-0731

MODEL=deepseek-v4-flash-0731
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V4-Flash-0731
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=together:deepseek-ai/DeepSeek-V4-Flash-0731; novita:deepseek/deepseek-v4-flash-0731
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### deepseek-v4-flash

MODEL=deepseek-v4-flash
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V4-Flash
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### deepseek-v4-pro

MODEL=deepseek-v4-pro
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V4-Pro
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### deepseek-v3.2

MODEL=deepseek-v3.2
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=deepseek/deepseek-v3.2
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models-console/model-detail/deepseek-deepseek-v3.2
VERIFIED_DATE=2026-09-18

### deepseek-v3.1

MODEL=deepseek-v3.1
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V3.1
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### deepseek-v3-0324

MODEL=deepseek-v3-0324
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V3-0324
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### deepseek-v3

MODEL=deepseek-v3
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-V3
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### deepseek-r1-0528

MODEL=deepseek-r1-0528
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=deepseek-ai/DeepSeek-R1-0528
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### deepseek-ocr-2

MODEL=deepseek-ocr-2
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=deepseek/deepseek-ocr-2
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=null

### kimi-k3 [LAUNCH]

MODEL=kimi-k3
PRIMARY_PROVIDER=inference_net
PROVIDER_MODEL_ID=moonshotai/kimi-k3
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1048576
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://inference.net/models/kimi-k3
VERIFIED_DATE=2026-09-18

### kimi-k2.7-code

MODEL=kimi-k2.7-code
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=moonshotai/Kimi-K2.7-Code
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### kimi-k2.6

MODEL=kimi-k2.6
PRIMARY_PROVIDER=chutes
PROVIDER_MODEL_ID=moonshotai/Kimi-K2.6-TEE
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=262144
ALTERNATIVE_OFFERS=deepinfra:moonshotai/Kimi-K2.6
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://chutes.ai/pricing
VERIFIED_DATE=2026-09-18

### kimi-k2.5

MODEL=kimi-k2.5
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=moonshotai/kimi-k2.5
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=null

### kimi-k2-instruct

MODEL=kimi-k2-instruct
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=moonshotai/kimi-k2-instruct
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models/model-detail/moonshotai-kimi-k2-instruct
VERIFIED_DATE=2026-09-18

### qwen3.8-2.4t-a95b

MODEL=qwen3.8-2.4t-a95b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3.8-2.4T-A95B
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### qwen3.8-max

MODEL=qwen3.8-max
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.8-max
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://docs.modelstudio.console.alibabacloud.com/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3.8-flash [LAUNCH]

MODEL=qwen3.8-flash
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.8-flash
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1000000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.alibabacloud.com/help/en/model-studio/qwen3-8-flash
VERIFIED_DATE=2026-09-18

### qwen3.8-27b

MODEL=qwen3.8-27b
PRIMARY_PROVIDER=chutes
PROVIDER_MODEL_ID=Qwen/Qwen3.8-27B-TEE
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=262144
ALTERNATIVE_OFFERS=novita:qwen/qwen3.8-27b
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://chutes.ai/pricing
VERIFIED_DATE=2026-09-18

### qwen3.7-max

MODEL=qwen3.7-max
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.7-max
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://docs.modelstudio.console.alibabacloud.com/en/model-studio/model-pricing
VERIFIED_DATE=null

### qwen3.7-plus

MODEL=qwen3.7-plus
PRIMARY_PROVIDER=together
PROVIDER_MODEL_ID=Qwen/Qwen3.7-Plus
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=alibaba_global:qwen3.7-plus
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.together.ai/pricing
VERIFIED_DATE=2026-09-18

### qwen3.6-35b-a3b

MODEL=qwen3.6-35b-a3b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3.6-35B-A3B
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### qwen3.6-27b

MODEL=qwen3.6-27b
PRIMARY_PROVIDER=chutes
PROVIDER_MODEL_ID=Qwen/Qwen3.6-27B-TEE
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=262144
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://chutes.ai/pricing
VERIFIED_DATE=2026-09-18

### qwen3.5-397b-a17b

MODEL=qwen3.5-397b-a17b
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.5-397b-a17b
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=deepinfra:Qwen/Qwen3.5-397B-A17B; together:Qwen/Qwen3.5-397B-A17B; chutes:Qwen/Qwen3.5-397B-A17B-TEE
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen3-5-397b-a17b
VERIFIED_DATE=2026-09-18

### qwen3.5-122b-a10b

MODEL=qwen3.5-122b-a10b
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.5-122b-a10b
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://docs.modelstudio.console.alibabacloud.com/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3.5-35b-a3b

MODEL=qwen3.5-35b-a3b
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.5-35b-a3b
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://docs.modelstudio.console.alibabacloud.com/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3.5-27b

MODEL=qwen3.5-27b
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.5-27b
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://docs.modelstudio.console.alibabacloud.com/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3.5-9b

MODEL=qwen3.5-9b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3.5-9B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3.5-plus

MODEL=qwen3.5-plus
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.5-plus
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1000000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.alibabacloud.com/help/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3.5-flash

MODEL=qwen3.5-flash
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3.5-flash
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1000000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.alibabacloud.com/help/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3-max-thinking

MODEL=qwen3-max-thinking
PRIMARY_PROVIDER=inference_net
PROVIDER_MODEL_ID=qwen/qwen3-max-thinking
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://inference.net/models
VERIFIED_DATE=null

### qwen3-max

MODEL=qwen3-max
PRIMARY_PROVIDER=alibaba_global
PROVIDER_MODEL_ID=qwen3-max
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=256000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.alibabacloud.com/help/en/model-studio/model-pricing
VERIFIED_DATE=2026-09-18

### qwen3-next-80b-a3b

MODEL=qwen3-next-80b-a3b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-Next-80B-A3B-Instruct
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-coder-480b-a35b

MODEL=qwen3-coder-480b-a35b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-Coder-480B-A35B-Instruct
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-coder-30b-a3b

MODEL=qwen3-coder-30b-a3b
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=qwen/qwen3-coder-30b-a3b-instruct
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models-console/model-detail/qwen-qwen3-coder-30b-a3b-instruct
VERIFIED_DATE=2026-09-18

### qwen3-235b-a22b-thinking-2507

MODEL=qwen3-235b-a22b-thinking-2507
PRIMARY_PROVIDER=fireworks
PROVIDER_MODEL_ID=accounts/fireworks/models/qwen3-235b-a22b-thinking-2507
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=chutes:Qwen/Qwen3-235B-A22B-Thinking-2507-TEE
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://fireworks.ai/models/fireworks/qwen3-235b-a22b-thinking-2507
VERIFIED_DATE=2026-09-18

### qwen3-235b-a22b-instruct-2507

MODEL=qwen3-235b-a22b-instruct-2507
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-235B-A22B-Instruct-2507
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-vl-235b-a22b

MODEL=qwen3-vl-235b-a22b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-VL-235B-A22B-Instruct
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-vl-30b-a3b

MODEL=qwen3-vl-30b-a3b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-VL-30B-A3B-Instruct
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-32b

MODEL=qwen3-32b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-32B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-30b-a3b

MODEL=qwen3-30b-a3b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-30B-A3B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen3-14b

MODEL=qwen3-14b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen3-14B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### qwen2.5-72b

MODEL=qwen2.5-72b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=Qwen/Qwen2.5-72B-Instruct
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### glm-5.3

MODEL=glm-5.3
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=zai-org/GLM-5.3
STATUS=REVIEW_REQUIRED
PRICE_STATUS=PRICE_REVERIFY_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### glm-5.3-flash [LAUNCH]

MODEL=glm-5.3-flash
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=zai-org/GLM-5.3-Flash
STATUS=REVIEW_REQUIRED
PRICE_STATUS=PRICE_REVERIFY_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### glm-5.2 [LAUNCH]

MODEL=glm-5.2
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=zai-org/GLM-5.2
STATUS=REVIEW_REQUIRED
PRICE_STATUS=PRICE_REVERIFY_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=together:zai-org/GLM-5.2; chutes:zai-org/GLM-5.2-TEE
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### glm-5.1

MODEL=glm-5.1
PRIMARY_PROVIDER=chutes
PROVIDER_MODEL_ID=zai-org/GLM-5.1-TEE
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=202752
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://chutes.ai/pricing
VERIFIED_DATE=2026-09-18

### glm-5

MODEL=glm-5
PRIMARY_PROVIDER=inference_net
PROVIDER_MODEL_ID=z-ai/glm-5
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://inference.net/models
VERIFIED_DATE=null

### glm-4.7-flash-nvfp4

MODEL=glm-4.7-flash-nvfp4
PRIMARY_PROVIDER=chutes
PROVIDER_MODEL_ID=zai-org/GLM-4.7-Flash-NVFP4-TEE
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://chutes.ai/agents
VERIFIED_DATE=null

### glm-4.7-bf16

MODEL=glm-4.7-bf16
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=zai-org/glm-4.7
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=null

### glm-4.5-air

MODEL=glm-4.5-air
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=zai-org/glm-4.5-air
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=null

### gemma-4-e4b

MODEL=gemma-4-e4b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-4-e4b-it
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gemma-4-31b-ultra

MODEL=gemma-4-31b-ultra
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-4-31b-it-ultra
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gemma-4-31b-turbo

MODEL=gemma-4-31b-turbo
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-4-31B-it-turbo
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gemma-4-31b

MODEL=gemma-4-31b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-4-31b-it
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gemma-4-26b-a4b

MODEL=gemma-4-26b-a4b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-4-26B-A4B-it
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gemma-3-27b

MODEL=gemma-3-27b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-3-27b-it
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gemma-3-12b

MODEL=gemma-3-12b
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=google/gemma-3-12b-it
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=null

### gemma-3-4b

MODEL=gemma-3-4b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=google/gemma-3-4b-it
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### llama-4-scout

MODEL=llama-4-scout
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=meta-llama/Llama-4-Scout
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### llama-4-maverick

MODEL=llama-4-maverick
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=meta-llama/Llama-4-Maverick
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### llama-guard-4-12b

MODEL=llama-guard-4-12b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=meta-llama/Llama-Guard-4-12B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### llama-3.3-70b-turbo

MODEL=llama-3.3-70b-turbo
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=meta-llama/Llama-3.3-70B-Instruct-Turbo
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### llama-3.1-70b-turbo

MODEL=llama-3.1-70b-turbo
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### llama-3.1-8b-turbo

MODEL=llama-3.1-8b-turbo
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### nemotron-3-nano-omni-30b

MODEL=nemotron-3-nano-omni-30b
PRIMARY_PROVIDER=chutes
PROVIDER_MODEL_ID=nvidia/Nemotron-3-Nano-Omni-30B-TEE
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=131072
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://chutes.ai/pricing
VERIFIED_DATE=2026-09-18

### nemotron-3-nano-30b-a3b

MODEL=nemotron-3-nano-30b-a3b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### nemotron-3-super-120b-a12b

MODEL=nemotron-3-super-120b-a12b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=nvidia/NVIDIA-Nemotron-3-Super-120B-A12B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### nemotron-3-ultra-550b-a55b

MODEL=nemotron-3-ultra-550b-a55b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=2026-09-18

### nemotron-content-safety-3.5

MODEL=nemotron-content-safety-3.5
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=nvidia/Nemotron-Content-Safety-3.5
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### nemotron-3.5-lightning

MODEL=nemotron-3.5-lightning
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=nvidia/Nemotron-3.5-Lightning
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### mistral-nemo

MODEL=mistral-nemo
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=mistralai/Mistral-Nemo-Instruct-2407
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### mistral-small-3.2-24b

MODEL=mistral-small-3.2-24b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=mistralai/Mistral-Small-3.2-24B-Instruct-2506
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### mistral-small-24b-2501

MODEL=mistral-small-24b-2501
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=mistralai/Mistral-Small-24B-Instruct-2501
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gpt-oss-120b

MODEL=gpt-oss-120b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=openai/gpt-oss-120b
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=novita:openai/gpt-oss-120b; together:openai/gpt-oss-120b
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### gpt-oss-20b

MODEL=gpt-oss-20b
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=openai/gpt-oss-20b
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### phi-4

MODEL=phi-4
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=microsoft/phi-4
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://deepinfra.com/
VERIFIED_DATE=null

### minimax-m3 [LAUNCH]

MODEL=minimax-m3
PRIMARY_PROVIDER=deepinfra
PROVIDER_MODEL_ID=MiniMaxAI/MiniMax-M3
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=together:MiniMaxAI/MiniMax-M3
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.together.ai/pricing
VERIFIED_DATE=2026-09-18

### minimax-m2.7

MODEL=minimax-m2.7
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=minimax/minimax-m2.7
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=null

### ling-3.0-flash-vl

MODEL=ling-3.0-flash-vl
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=inclusionAI/Ling-3.0-Flash-VL
STATUS=PROMOTIONAL_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=256000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=2026-09-18

### ling-3.0-flash-sante

MODEL=ling-3.0-flash-sante
PRIMARY_PROVIDER=novita
PROVIDER_MODEL_ID=inclusionAI/Ling-3.0-Flash-Sante
STATUS=REVIEW_REQUIRED
PRICE_STATUS=PRICE_REVERIFY_REQUIRED
REGION=global
CONTEXT=256000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://novita.ai/models
VERIFIED_DATE=2026-09-18

### ternary-bonsai-27b

MODEL=ternary-bonsai-27b
PRIMARY_PROVIDER=together
PROVIDER_MODEL_ID=Prism-ML/Ternary-Bonsai-27B
STATUS=REVIEW_REQUIRED
PRICE_STATUS=PRICE_REVERIFY_REQUIRED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.together.ai/models/prism-ml-ternary-bonsai-27b
VERIFIED_DATE=2026-09-18

### mimo-v2.5 [LAUNCH]

MODEL=mimo-v2.5
PRIMARY_PROVIDER=xiaomi_mimo
PROVIDER_MODEL_ID=mimo-v2.5
STATUS=REVIEW_REQUIRED
PRICE_STATUS=REVIEW_REQUIRED
REGION=global
CONTEXT=1000000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://mimo.mi.com/docs/en-US/api/model/list-models
VERIFIED_DATE=null

### gpt-5.6-luna [LAUNCH]

MODEL=gpt-5.6-luna
PRIMARY_PROVIDER=openai_direct
PROVIDER_MODEL_ID=gpt-5.6-luna
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1050000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://developers.openai.com/api/docs/models/gpt-5.6-luna
VERIFIED_DATE=2026-09-18

### gpt-5.6-terra [LAUNCH]

MODEL=gpt-5.6-terra
PRIMARY_PROVIDER=openai_direct
PROVIDER_MODEL_ID=gpt-5.6-terra
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=1050000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://developers.openai.com/api/docs/models/gpt-5.6-terra
VERIFIED_DATE=2026-09-18

### gpt-5.6-sol [LAUNCH]

MODEL=gpt-5.6-sol
PRIMARY_PROVIDER=openai_direct
PROVIDER_MODEL_ID=gpt-5.6-sol
STATUS=REVIEW_REQUIRED
PRICE_STATUS=PRICE_REVERIFY_REQUIRED
REGION=global
CONTEXT=1050000
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://developers.openai.com/api/docs/models/gpt-5.6-sol
VERIFIED_DATE=2026-09-18

### claude-sonnet-5 [LAUNCH]

MODEL=claude-sonnet-5
PRIMARY_PROVIDER=anthropic_direct
PROVIDER_MODEL_ID=claude-sonnet-5
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.anthropic.com/news/claude-sonnet-5
VERIFIED_DATE=2026-09-18

### claude-opus-5 [LAUNCH]

MODEL=claude-opus-5
PRIMARY_PROVIDER=anthropic_direct
PROVIDER_MODEL_ID=claude-opus-5
STATUS=VERIFIED_PRIMARY
PRICE_STATUS=TRUSTED
REGION=global
CONTEXT=unknown
ALTERNATIVE_OFFERS=—
RATIONALE=Locked reviewed-static-primary route; provider changes require explicit evidence review.
SOURCE=https://www.anthropic.com/news/claude-opus-5
VERIFIED_DATE=2026-09-18

