"""Offline pins for the single runtime Director contract module.

No torch, transformers, PEFT, xgrammar, jsonschema, network, credentials or
model download. These tests prove that the serving probe, the SFT packet
builder and the LoRA runner read ONE contract instance instead of keeping
private copies that can drift apart (the 1-2 Nov 2026 five-round GPU loss).
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "scripts/multimedia-director-contract.py"
PROBE_PATH = ROOT / "scripts/probe-multimedia-director-vlm.py"
CONTRACT_MODULE_NAME = "bico_multimedia_director_contract"


def imported(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = imported("bico_contract_probe_consumer", PROBE_PATH)
        # The consumer's loader registers the shared instance; asserting on that
        # object (not on a second private copy) is what makes identity meaningful.
        cls.contract = sys.modules[CONTRACT_MODULE_NAME]

    def test_registry_pins_measured_primary_and_legacy(self):
        contract = self.contract
        self.assertEqual(contract.PRIMARY, "Qwen/Qwen3-VL-4B-Instruct")
        self.assertEqual(contract.LEGACY_2B, "HuggingFaceTB/SmolVLM2-2.2B-Instruct")
        self.assertEqual(contract.ALLOWED_MODELS, {contract.PRIMARY, contract.LEGACY_2B})
        self.assertEqual(contract.EXPECTED_ARCHITECTURES, {
            contract.PRIMARY: {"qwen3_vl"},
            contract.LEGACY_2B: {"idefics3", "smolvlm"},
        })
        self.assertEqual(contract.TARGET_SCHEMA, "botconnector.multimedia-director.v1")
        self.assertEqual(contract.DIRECTOR_TASKS,
                         ("product_photo", "ad_creative", "storyboard", "video_direction"))

    def test_probe_reexports_the_same_objects(self):
        probe, contract = self.probe, self.contract
        self.assertIs(probe.make_prompt, contract.make_prompt)
        self.assertIs(probe.contract_skeleton, contract.contract_skeleton)
        self.assertIs(probe.contract_json_schema, contract.contract_json_schema)
        self.assertIs(probe.EXPECTED_ARCHITECTURES, contract.EXPECTED_ARCHITECTURES)
        self.assertEqual(probe.ALLOWED_MODELS, contract.ALLOWED_MODELS)
        self.assertEqual(probe.PRIMARY, contract.PRIMARY)
        self.assertEqual(probe.LEGACY_2B, contract.LEGACY_2B)

    def test_contract_module_imports_no_heavy_dependency(self):
        code = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('c', {path!r})\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "heavy = ('torch', 'transformers', 'peft', 'xgrammar', 'jsonschema', 'requests')\n"
            "print([name for name in heavy if name in sys.modules])\n"
        ).format(path=str(CONTRACT_PATH))
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
