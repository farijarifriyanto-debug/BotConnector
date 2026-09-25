import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _pool():
    return json.loads((ROOT / "free-cloud-pool.json").read_text())

def test_ling_has_two_free_provider_routes():
    pool=_pool()
    ling=next(x for x in pool["models"] if x["id"]=="ling-3.0-flash")
    providers={r["provider"] for r in ling["routes"] if r["price_in_per_m"]==0 and r["price_out_per_m"]==0}
    assert providers == {"novita","gmi"}

def test_free_contributing_providers_also_have_payg_models():
    pool=_pool()
    free_providers=set()
    payg_providers=set()
    for model in pool["models"]:
        for route in model["routes"]:
            if route.get("price_in_per_m")==0 and route.get("price_out_per_m")==0:
                free_providers.add(route["provider"])
            else:
                payg_providers.add(route["provider"])
    assert free_providers <= payg_providers

def test_user_selected_model_is_preserved():
    assert _pool()["routing_rules"]["preserve_user_selected_model"] is True
