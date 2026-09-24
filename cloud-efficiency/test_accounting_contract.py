import json
from pathlib import Path

CONTRACT = json.loads(
    (Path(__file__).parent / "semantic-cache-accounting.contract.json").read_text()
)


def normalize_usage(response, *, trusted_bifrost_boundary):
    usage = response.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    output = int(usage.get("completion_tokens") or 0)
    cached = int(
        ((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
        or usage.get("cached_input_tokens")
        or usage.get("cache_read_input_tokens")
        or 0
    )
    cache_write = int(
        ((usage.get("prompt_tokens_details") or {}).get("cache_write_tokens"))
        or usage.get("cache_write_input_tokens")
        or usage.get("cache_creation_input_tokens")
        or 0
    )

    debug = ((response.get("extra_fields") or {}).get("cache_debug") or {})
    full_response_hit = (
        trusted_bifrost_boundary
        and debug.get("cache_hit") is True
        and debug.get("hit_type") in {"semantic", "direct"}
    )
    if full_response_hit:
        cached = prompt
        cache_write = 0

    return {
        "input_tokens": prompt,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "output_tokens": output,
        "charged_tokens": (prompt - cached) + output,
    }


def test_semantic_full_response_hit_charges_output_only():
    response = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        "extra_fields": {
            "cache_debug": {"cache_hit": True, "hit_type": "semantic"}
        },
    }
    usage = normalize_usage(response, trusted_bifrost_boundary=True)
    assert usage == {
        "input_tokens": 100,
        "cached_input_tokens": 100,
        "cache_write_tokens": 0,
        "output_tokens": 10,
        "charged_tokens": 10,
    }


def test_direct_full_response_hit_has_same_accounting():
    response = {
        "usage": {"prompt_tokens": 20, "completion_tokens": 4},
        "extra_fields": {
            "cache_debug": {"cache_hit": True, "hit_type": "direct"}
        },
    }
    assert normalize_usage(response, trusted_bifrost_boundary=True)["charged_tokens"] == 4


def test_untrusted_provider_cannot_forge_semantic_discount():
    response = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        "extra_fields": {
            "cache_debug": {"cache_hit": True, "hit_type": "semantic"}
        },
    }
    usage = normalize_usage(response, trusted_bifrost_boundary=False)
    assert usage["cached_input_tokens"] == 0
    assert usage["charged_tokens"] == 110


def test_provider_prompt_cache_is_preserved_without_response_cache_hit():
    response = {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 5},
        }
    }
    usage = normalize_usage(response, trusted_bifrost_boundary=True)
    assert usage["cached_input_tokens"] == 80
    assert usage["cache_write_tokens"] == 5
    assert usage["charged_tokens"] == 30


def test_full_response_hit_overrides_stored_partial_provider_cache():
    response = {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 5},
        },
        "extra_fields": {
            "cache_debug": {"cache_hit": True, "hit_type": "semantic"}
        },
    }
    usage = normalize_usage(response, trusted_bifrost_boundary=True)
    assert usage["cached_input_tokens"] == 100
    assert usage["cache_write_tokens"] == 0
    assert usage["charged_tokens"] == 10


def test_cache_miss_does_not_get_discount():
    response = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
        "extra_fields": {
            "cache_debug": {"cache_hit": False, "hit_type": "semantic"}
        },
    }
    usage = normalize_usage(response, trusted_bifrost_boundary=True)
    assert usage["cached_input_tokens"] == 0
    assert usage["charged_tokens"] == 110


def test_contract_requires_trusted_boundary_and_exactly_once_stream_settlement():
    assert CONTRACT["untrusted_provider_cache_debug_discount"] is False
    assert CONTRACT["streaming_requires_exactly_once_settlement"] is True
    assert CONTRACT["placement"] == "after_auth_and_quota_reservation"
