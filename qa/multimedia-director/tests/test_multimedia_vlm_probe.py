import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

FILE = Path(__file__).resolve().parents[1] / 'scripts/probe-multimedia-director-vlm.py'
spec = importlib.util.spec_from_file_location('bico_mm_probe', FILE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGO8wyXHwMDAxMDAwMDAAAANGAEIahSdtwAAAABJRU5ErkJggg=='


class ProbeDryRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.asset_root = self.root / 'images'
        self.asset_root.mkdir()
        image_bytes = base64.b64decode(PNG)
        (self.asset_root / 'photo.png').write_bytes(image_bytes)
        self.staged = self.root / 'stage'
        self.staged.mkdir()
        self.row = {
            'schema': 'botconnector.multimedia-dataset.v1',
            'id': 'sample-dry-run', 'split': 'val', 'task': 'product_photo',
            'image_path': 'photo.png',
            'image_sha256': hashlib.sha256(image_bytes).hexdigest(),
            'brief': 'Buat foto produk botol dengan pencahayaan yang baik.'
        }
        (self.staged / 'val.jsonl').write_text(json.dumps(self.row) + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def args(self):
        return ['--staged', str(self.staged), '--assets-root', str(self.asset_root), '--split', 'val']

    def test_make_prompt_states_exact_contract_keys(self):
        prompt = probe.make_prompt(self.row)
        for key in ('"schema"', '"task"', '"visual"', '"observed_facts"', '"unknowns"',
                    '"preservation_rules"', '"concepts"', '"title"', '"scene"', '"mood"', '"tagline"'):
            self.assertIn(key, prompt)
        self.assertIn(probe.TARGET_SCHEMA, prompt)
        # The 1-2 Nov 2026 benchmark showed this ambiguous phrasing made the schema
        # string a JSON KEY (envelope). It must never come back.
        self.assertNotIn('Use schema "', prompt)

    def test_contract_skeleton_matches_benchmark_contract(self):
        parsed = json.loads(probe.contract_skeleton('product_photo'))
        self.assertEqual(parsed['schema'], probe.TARGET_SCHEMA)
        self.assertEqual(parsed['task'], 'product_photo')
        self.assertEqual(sorted(parsed),
                         ['concepts', 'preservation_rules', 'schema', 'task', 'visual'])
        self.assertEqual(sorted(parsed['visual']), ['observed_facts', 'unknowns'])
        self.assertEqual(len(parsed['concepts']), 3)
        self.assertEqual(sorted(parsed['concepts'][0]), ['mood', 'scene', 'tagline', 'title'])
        shots = json.loads(probe.contract_skeleton('storyboard'))
        self.assertEqual(sorted(shots),
                         ['preservation_rules', 'schema', 'shots', 'task', 'visual'])
        self.assertEqual(len(shots['shots']), 2)
        self.assertEqual(sorted(shots['shots'][0]),
                         ['action', 'camera', 'duration_seconds', 'subject_lock'])

    def test_contract_json_schema_matches_scorer_contract(self):
        schema = probe.contract_json_schema('product_photo')
        self.assertEqual(sorted(schema['required']),
                         ['concepts', 'preservation_rules', 'schema', 'task', 'visual'])
        self.assertEqual(schema['properties']['schema']['enum'], [probe.TARGET_SCHEMA])
        self.assertEqual(schema['properties']['task']['enum'], ['product_photo'])
        self.assertEqual(schema['properties']['concepts']['minItems'], 3)
        self.assertEqual(schema['properties']['concepts']['maxItems'], 3)
        self.assertEqual(schema['properties']['visual']['properties']['observed_facts']['minItems'], 1)
        self.assertFalse(schema['additionalProperties'])
        # Schema keys must mirror the prompt skeleton keys exactly (anti-drift).
        parsed = json.loads(probe.contract_skeleton('product_photo'))
        self.assertEqual(sorted(schema['properties']), sorted(parsed))
        self.assertEqual(sorted(schema['properties']['concepts']['items']['properties']),
                         sorted(parsed['concepts'][0]))
        self.assertEqual(sorted(schema['properties']['visual']['properties']),
                         sorted(parsed['visual']))

    def test_contract_json_schema_shot_contract(self):
        schema = probe.contract_json_schema('storyboard')
        self.assertEqual(sorted(schema['required']),
                         ['preservation_rules', 'schema', 'shots', 'task', 'visual'])
        self.assertEqual(schema['properties']['shots']['minItems'], 2)
        self.assertEqual(schema['properties']['shots']['maxItems'], 6)
        duration = schema['properties']['shots']['items']['properties']['duration_seconds']
        self.assertEqual((duration['minimum'], duration['maximum']), (1, 10))

    def test_contract_schema_rejects_unknown_task(self):
        for builder in (probe.contract_skeleton, probe.contract_json_schema):
            with self.assertRaises(ValueError):
                builder('text_only_chat')

    def test_contract_schema_accepts_valid_and_rejects_round6_failures(self):
        # The grammar schema must enforce exactly what the scorer checks: the
        # envelope form and the dot-flat key form from rounds 1-4 both fail.
        try:
            import jsonschema
        except ImportError:
            self.skipTest('jsonschema is not installed in this environment')
        schema = probe.contract_json_schema('product_photo')
        jsonschema.validate(json.loads(probe.contract_skeleton('product_photo')), schema)
        jsonschema.validate(json.loads(probe.contract_skeleton('storyboard')),
                            probe.contract_json_schema('storyboard'))
        envelope = {'botconnector.multimedia-director.v1': {'anything': 1}}
        dot_flat = {'schema': probe.TARGET_SCHEMA, 'task': 'product_photo',
                    'visual.observed_facts': ['botol'], 'visual.unknowns': [],
                    'preservation_rules': ['jaga bentuk'],
                    'concepts': [{'title': 'premium', 'scene': 'meja', 'mood': 'bersih',
                                  'tagline': 'rapi'}]}
        for bad in (envelope, dot_flat):
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)

    def test_constrained_decoding_flag_reported_in_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(probe.probe(self.args() + ['--constrained-decoding']), 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload['constrained_decoding'])
        self.assertFalse(payload['gpu_started'])

    @unittest.skipIf(importlib.util.find_spec('xgrammar') is not None,
                     'xgrammar is installed here, so the fail-closed path cannot be tested')
    def test_constraint_fails_closed_without_xgrammar(self):
        # Never silently decode unconstrained: a missing xgrammar must stop the run.
        with self.assertRaisesRegex(RuntimeError, 'xgrammar'):
            probe.contract_constraint(object(), 'product_photo')

    def test_valid_dry_run_without_model_download(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(probe.probe(self.args()), 0)
        output = json.loads(out.getvalue())
        self.assertEqual(output['mode'], 'dry_run_only')
        self.assertEqual(output['sample_count'], 1)
        self.assertFalse(output['gpu_started'])
        self.assertFalse(output['model_downloaded'])

    def test_primary_model_is_qwen3_vl_4b(self):
        # Model decision 2 Nov 2026: 90% vs 50% contract pass, factsRecall 0.422 vs 0.
        self.assertEqual(probe.PRIMARY, 'Qwen/Qwen3-VL-4B-Instruct')
        self.assertIn(probe.PRIMARY, probe.ALLOWED_MODELS)

    def test_legacy_2b_model_requires_explicit_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                probe.probe(self.args() + ['--model', probe.LEGACY_2B])
        self.assertEqual(raised.exception.code, 2)

    def test_legacy_2b_dry_run_allowed_with_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                probe.probe(self.args() + ['--model', probe.LEGACY_2B, '--allow-2b-legacy']), 0)
        self.assertEqual(json.loads(out.getvalue())['model'], probe.LEGACY_2B)

    def test_run_requires_cost_acknowledgement_and_output(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                probe.probe(self.args() + ['--run'])
        self.assertEqual(raised.exception.code, 2)

    def test_actual_run_rejects_ungated_smoke_dataset(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = probe.probe(self.args() + [
                '--run', '--acknowledge-runtime-cost', '--out', str(self.root / 'predictions.jsonl')
            ])
        self.assertEqual(result, 2)
        self.assertIn('fully gated dataset summary', err.getvalue())

    def test_sha256_mismatch_blocks_dry_run(self):
        self.row['image_sha256'] = 'a' * 64
        (self.staged / 'val.jsonl').write_text(json.dumps(self.row) + '\n', encoding='utf-8')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(probe.probe(self.args()), 2)
        self.assertIn('SHA256 mismatch', err.getvalue())

    def test_path_escape_blocks_dry_run(self):
        self.row['image_path'] = '../photo.png'
        (self.staged / 'val.jsonl').write_text(json.dumps(self.row) + '\n', encoding='utf-8')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(probe.probe(self.args()), 2)
        self.assertIn('unsafe image path', err.getvalue())


if __name__ == '__main__':
    unittest.main()
