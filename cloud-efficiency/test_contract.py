import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _config():
    return json.loads((ROOT / "bifrost" / "semantic-cache.config.example.json").read_text())

def test_semantic_cache_is_model_and_provider_scoped():
    config = _config()
    plugin = next(item for item in config["plugins"] if item["name"] == "semantic_cache")
    assert plugin["enabled"] is True
    assert plugin["config"]["cache_by_model"] is True
    assert plugin["config"]["cache_by_provider"] is True
    assert plugin["config"]["threshold"] >= 0.9

def test_content_logging_is_disabled():
    assert _config()["client"]["disable_content_logging"] is True

def test_semantic_embeddings_are_local_not_paid_provider():
    config = _config()
    plugin = next(item for item in config["plugins"] if item["name"] == "semantic_cache")
    assert plugin["config"]["provider"] == "botconnector_embedding"
    provider = config["providers"]["botconnector_embedding"]
    assert provider["network_config"]["base_url"].startswith("http://embeddings:")
    assert provider["custom_provider_config"]["allowed_requests"]["embedding"] is True
