#!/usr/bin/env python3
"""Microbenchmark the profiler bookkeeping itself; no provider/network calls."""
from pathlib import Path
import json
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from latency_profiler import LatencyProfiler  # noqa: E402


def main():
    profiler = LatencyProfiler()
    samples_us = []
    for i in range(20000):
        start = time.perf_counter_ns()
        trace = profiler.start(request_id=f"bench-{i}", model="fixture", provider="fixture")
        trace.mark("provider_request")
        trace.mark("first_byte")
        trace.mark("first_token")
        trace.finish(status_code=200)
        trace.to_dict()
        samples_us.append((time.perf_counter_ns() - start) / 1000.0)

    ordered = sorted(samples_us)
    result = {
        "iterations": len(samples_us),
        "unit": "microseconds",
        "p50": round(statistics.median(ordered), 3),
        "p95": round(ordered[int(len(ordered) * 0.95) - 1], 3),
        "p99": round(ordered[int(len(ordered) * 0.99) - 1], 3),
        "max": round(max(ordered), 3),
        "note": "Bookkeeping-only benchmark; excludes network/provider latency.",
    }
    out = Path(__file__).with_name("LATENCY_PROFILER_OVERHEAD.json")
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
