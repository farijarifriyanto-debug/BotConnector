"""
BotConnector AI Support V3 — Freepool Support Inference Engine.
Inference-only engine with fast local Llama model failover, free-first policy, bounded latency,
and isolated execution (strictly zero shell/workspace/coding execution access).
"""
from __future__ import annotations

import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

FREE_MODELS_FIRST = True
PAID_FALLBACK = False

CONNECT_TIMEOUT_SEC = 2.0
TOTAL_INFERENCE_TIMEOUT_SEC = 6.0

LOCAL_LLAMA_URL = os.environ.get("SUPPORT_AI_LLAMA_URL", "http://botconnector-llama-chat:8080/v1")

@dataclass
class ProviderCandidate:
    id: str
    name: str
    base_url: str
    model: str
    api_key: Optional[str] = None
    is_local: bool = False
    cooldown_until: float = 0.0
    failure_count: int = 0
    success_count: int = 0
    last_latency_ms: Optional[float] = None

class FreepoolSupportInference:
    """
    Production Support AI Inference Engine V3.
    Routes queries across healthy free providers and local llama.cpp server.
    """

    def __init__(self):
        self.providers: List[ProviderCandidate] = [
            # 1. Local High-Speed Llama.cpp Server (Zero cost, isolated, instant response)
            ProviderCandidate(
                id="local-llama",
                name="Local Llama Engine",
                base_url=LOCAL_LLAMA_URL,
                model="qwen2.5-coder-7b-instruct:q4_k_m",
                api_key=None,
                is_local=True
            ),
            # 2. Configurable OpenRouter Free Pool (if API key set in environment)
            ProviderCandidate(
                id="openrouter-free",
                name="OpenRouter Free Router",
                base_url="https://openrouter.ai/api/v1",
                model="openrouter/free",
                api_key=os.environ.get("OPENROUTER_API_KEY", ""),
                is_local=False
            )
        ]

    def get_eligible_models(self) -> List[ProviderCandidate]:
        """Returns active, non-cooled-down free providers."""
        now = time.time()
        eligible = []
        for p in self.providers:
            if not p.is_local and not p.api_key:
                continue
            if p.cooldown_until > now:
                continue
            eligible.append(p)
        return eligible

    def select_model(self) -> Optional[ProviderCandidate]:
        """Select best candidate based on health and availability."""
        eligible = self.get_eligible_models()
        if not eligible:
            local = next((p for p in self.providers if p.is_local), None)
            if local:
                local.cooldown_until = 0.0
                return local
            return None
        return eligible[0]

    def mark_failure(self, provider_id: str, error_reason: str):
        """Mark provider failure and set temporary cooldown."""
        for p in self.providers:
            if p.id == provider_id:
                p.failure_count += 1
                p.cooldown_until = time.time() + 20.0

    def mark_success(self, provider_id: str, latency_ms: float):
        """Record success and clear failure cooldown."""
        for p in self.providers:
            if p.id == provider_id:
                p.success_count += 1
                p.last_latency_ms = latency_ms
                p.cooldown_until = 0.0

    def health(self) -> Dict[str, Any]:
        """Sanitized health inspection without leaking credentials."""
        eligible = self.get_eligible_models()
        return {
            "status": "HEALTHY" if eligible else "DEGRADED",
            "free_models_first": FREE_MODELS_FIRST,
            "paid_fallback": PAID_FALLBACK,
            "provider_pool_count": len(self.providers),
            "eligible_providers": len(eligible),
            "providers": [
                {
                    "id": p.id,
                    "is_local": p.is_local,
                    "model": p.model,
                    "healthy": p.cooldown_until <= time.time(),
                    "success_count": p.success_count,
                    "failure_count": p.failure_count,
                    "last_latency_ms": p.last_latency_ms
                }
                for p in self.providers
            ]
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        temperature: float = 0.15,
        max_tokens: int = 400
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """
        Execute chat completion with automatic provider failover.
        Returns: (response_text, provider_id_used, latency_ms)
        """
        all_messages = [{"role": "system", "content": system_prompt}] + messages
        eligible = self.get_eligible_models()

        if not eligible:
            local = next((p for p in self.providers if p.is_local), None)
            if local:
                eligible = [local]

        for provider in eligible:
            start_t = time.time()
            try:
                payload = {
                    "model": provider.model,
                    "messages": all_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
                data_bytes = json.dumps(payload).encode("utf-8")
                
                headers = {"Content-Type": "application/json"}
                if provider.api_key:
                    headers["Authorization"] = f"Bearer {provider.api_key}"

                req = urllib.request.Request(
                    f"{provider.base_url}/chat/completions",
                    headers=headers,
                    data=data_bytes
                )
                
                with urllib.request.urlopen(req, timeout=TOTAL_INFERENCE_TIMEOUT_SEC) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    text = resp_data["choices"][0]["message"]["content"]
                    latency_ms = (time.time() - start_t) * 1000.0
                    self.mark_success(provider.id, latency_ms)
                    return text.strip(), provider.id, round(latency_ms, 2)

            except Exception as exc:
                self.mark_failure(provider.id, str(exc))
                continue

        # All providers failed
        return None, None, None

# Global singleton runtime
GLOBAL_INFERENCE = FreepoolSupportInference()
