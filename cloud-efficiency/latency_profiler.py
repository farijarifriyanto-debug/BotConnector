"""Low-overhead request latency profiling for BotConnector cloud.

The profiler intentionally records timing metadata only. It never stores prompts,
messages, tool arguments, API keys, or response content.
"""
from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
import time
from typing import Callable, Deque, Dict, Iterable, Iterator, Mapping, Optional

Clock = Callable[[], int]


def _ms(delta_ns: int) -> float:
    return round(delta_ns / 1_000_000.0, 3)


def _percentile(values: Iterable[float], q: float) -> Optional[float]:
    data = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return round(data[0], 3)
    pos = (len(data) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return round(data[lo], 3)
    return round(data[lo] + (data[hi] - data[lo]) * (pos - lo), 3)


@dataclass
class LatencyTrace:
    request_id: str
    model: str
    provider: Optional[str] = None
    route: Optional[str] = None
    cache_status: Optional[str] = None
    sampled: bool = True
    clock_ns: Clock = time.perf_counter_ns
    started_ns: int = field(init=False)
    ended_ns: Optional[int] = field(default=None, init=False)
    marks_ns: Dict[str, int] = field(default_factory=dict, init=False)
    stages_ms: Dict[str, float] = field(default_factory=dict, init=False)
    status_code: Optional[int] = None
    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None

    def __post_init__(self) -> None:
        self.started_ns = self.clock_ns()

    def mark(self, name: str) -> None:
        if self.sampled and name not in self.marks_ns:
            self.marks_ns[name] = self.clock_ns()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if not self.sampled:
            yield
            return
        start = self.clock_ns()
        try:
            yield
        finally:
            self.stages_ms[name] = _ms(self.clock_ns() - start)

    def finish(self, *, status_code: Optional[int] = None) -> None:
        if status_code is not None:
            self.status_code = status_code
        if self.ended_ns is None:
            self.ended_ns = self.clock_ns()

    def _elapsed_from_start(self, mark: str) -> Optional[float]:
        value = self.marks_ns.get(mark)
        return None if value is None else _ms(value - self.started_ns)

    def to_dict(self) -> Dict[str, object]:
        if self.ended_ns is None:
            self.finish()
        first_token = self.marks_ns.get("first_token")
        generation_ms = (
            None if first_token is None or self.ended_ns is None
            else _ms(self.ended_ns - first_token)
        )
        payload: Dict[str, object] = {
            "schema": "botconnector.latency.v1",
            "request_id": self.request_id,
            "model": self.model,
            "provider": self.provider,
            "route": self.route,
            "cache_status": self.cache_status,
            "status_code": self.status_code,
            "sampled": self.sampled,
            "timing_ms": {
                "ingress_to_provider": self._elapsed_from_start("provider_request"),
                "first_byte": self._elapsed_from_start("first_byte"),
                "ttft": self._elapsed_from_start("first_token"),
                "generation": generation_ms,
                "total": _ms(self.ended_ns - self.started_ns) if self.ended_ns else None,
                "stages": dict(sorted(self.stages_ms.items())),
            },
            "usage": {
                "input_tokens": self.input_tokens,
                "cached_input_tokens": self.cached_input_tokens,
                "output_tokens": self.output_tokens,
            },
        }
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    def server_timing_header(self) -> str:
        timing = self.to_dict()["timing_ms"]
        assert isinstance(timing, Mapping)
        items = []
        for key in ("ingress_to_provider", "first_byte", "ttft", "generation", "total"):
            value = timing.get(key)
            if isinstance(value, (int, float)):
                items.append(f"bc_{key.replace('_', '-')};dur={value:.3f}")
        return ", ".join(items)


class LatencyProfiler:
    """Factory for deterministic sampled traces.

    Hash-based sampling keeps the same request_id decision stable across retries.
    """

    def __init__(self, *, enabled: bool = True, sample_rate: float = 1.0, clock_ns: Clock = time.perf_counter_ns):
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")
        self.enabled = enabled
        self.sample_rate = sample_rate
        self.clock_ns = clock_ns

    def should_sample(self, request_id: str) -> bool:
        if not self.enabled or self.sample_rate <= 0:
            return False
        if self.sample_rate >= 1:
            return True
        bucket = int.from_bytes(hashlib.blake2s(request_id.encode(), digest_size=8).digest(), "big")
        return bucket / float(2**64 - 1) < self.sample_rate

    def start(self, *, request_id: str, model: str, provider: Optional[str] = None, route: Optional[str] = None) -> LatencyTrace:
        return LatencyTrace(
            request_id=request_id,
            model=model,
            provider=provider,
            route=route,
            sampled=self.should_sample(request_id),
            clock_ns=self.clock_ns,
        )


class RollingLatencyStore:
    """Bounded in-memory p50/p95/p99 rollups keyed by model/provider.

    This store is intentionally process-local and is suitable for routing telemetry,
    not durable billing/accounting.
    """

    def __init__(self, max_samples: int = 1024):
        if max_samples < 1:
            raise ValueError("max_samples must be positive")
        self.max_samples = max_samples
        self._ttft: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=max_samples))
        self._total: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=max_samples))

    @staticmethod
    def key(model: str, provider: Optional[str]) -> str:
        return f"{model}::{provider or 'unknown'}"

    def observe(self, trace: LatencyTrace) -> None:
        data = trace.to_dict()
        timing = data["timing_ms"]
        assert isinstance(timing, Mapping)
        key = self.key(trace.model, trace.provider)
        ttft = timing.get("ttft")
        total = timing.get("total")
        if isinstance(ttft, (int, float)):
            self._ttft[key].append(float(ttft))
        if isinstance(total, (int, float)):
            self._total[key].append(float(total))

    def snapshot(self, model: str, provider: Optional[str]) -> Dict[str, object]:
        key = self.key(model, provider)
        ttft = list(self._ttft[key])
        total = list(self._total[key])
        return {
            "model": model,
            "provider": provider,
            "samples": max(len(ttft), len(total)),
            "ttft_ms": {
                "p50": _percentile(ttft, 0.50),
                "p95": _percentile(ttft, 0.95),
                "p99": _percentile(ttft, 0.99),
            },
            "total_ms": {
                "p50": _percentile(total, 0.50),
                "p95": _percentile(total, 0.95),
                "p99": _percentile(total, 0.99),
            },
        }
