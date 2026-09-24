import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def test_semantic_cache_is_model_and_provider_scoped():
    config = json.loads((ROOT / "bifrost" / "semantic-cache.config.example.json").read_text())
    plugin = next(item for item in config["plugins"] if item["name"] == "semantic_cache")
    assert plugin["enabled"] is True
    assert plugin["config"]["cache_by_model"] is True
    assert plugin["config"]["cache_by_provider"] is True
    assert plugin["config"]["threshold"] >= 0.9

def test_content_logging_is_disabled():
    config = json.loads((ROOT / "bifrost" / "semantic-cache.config.example.json").read_text())
    assert config["client"]["disable_content_logging"] is True
