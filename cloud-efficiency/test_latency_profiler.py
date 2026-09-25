import json
from latency_profiler import LatencyProfiler, RollingLatencyStore


class FakeClock:
    def __init__(self):
        self.value = 1_000_000_000

    def __call__(self):
        return self.value

    def advance_ms(self, ms):
        self.value += int(ms * 1_000_000)


def test_trace_breakdown_and_server_timing():
    clock = FakeClock()
    profiler = LatencyProfiler(clock_ns=clock)
    trace = profiler.start(request_id="r-1", model="model-a", provider="provider-a")

    clock.advance_ms(10)
    trace.mark("provider_request")
    clock.advance_ms(20)
    trace.mark("first_byte")
    clock.advance_ms(30)
    trace.mark("first_token")
    clock.advance_ms(40)
    trace.finish(status_code=200)

    data = trace.to_dict()
    assert data["timing_ms"]["ingress_to_provider"] == 10.0
    assert data["timing_ms"]["first_byte"] == 30.0
    assert data["timing_ms"]["ttft"] == 60.0
    assert data["timing_ms"]["generation"] == 40.0
    assert data["timing_ms"]["total"] == 100.0
    assert "bc_ttft;dur=60.000" in trace.server_timing_header()


def test_stage_records_only_timing_not_content():
    clock = FakeClock()
    trace = LatencyProfiler(clock_ns=clock).start(request_id="r-2", model="model-a")
    with trace.stage("auth_quota"):
        clock.advance_ms(12)
    trace.finish()
    encoded = trace.to_json()
    assert json.loads(encoded)["timing_ms"]["stages"]["auth_quota"] == 12.0
    for forbidden in ("prompt", "messages", "tool_arguments", "api_key", "response_content"):
        assert forbidden not in encoded


def test_sampling_is_stable_for_same_request_id():
    profiler = LatencyProfiler(sample_rate=0.25)
    first = profiler.should_sample("same-request")
    assert all(profiler.should_sample("same-request") is first for _ in range(10))


def test_rolling_provider_ttft_percentiles():
    clock = FakeClock()
    profiler = LatencyProfiler(clock_ns=clock)
    store = RollingLatencyStore(max_samples=8)
    for idx, ttft in enumerate((100, 200, 300, 400)):
        trace = profiler.start(request_id=f"r-{idx}", model="model-a", provider="provider-a")
        clock.advance_ms(ttft)
        trace.mark("first_token")
        clock.advance_ms(10)
        trace.finish()
        store.observe(trace)
        clock.advance_ms(5)

    snap = store.snapshot("model-a", "provider-a")
    assert snap["samples"] == 4
    assert snap["ttft_ms"]["p50"] == 250.0
    assert snap["ttft_ms"]["p95"] == 385.0


def test_profiler_can_be_disabled_without_losing_request_metadata():
    clock = FakeClock()
    trace = LatencyProfiler(enabled=False, clock_ns=clock).start(
        request_id="r-off", model="model-a", provider="provider-a"
    )
    clock.advance_ms(50)
    trace.mark("first_token")
    trace.finish()
    data = trace.to_dict()
    assert data["sampled"] is False
    assert data["request_id"] == "r-off"
    assert data["timing_ms"]["ttft"] is None
