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

    def test_valid_dry_run_without_model_download(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(probe.probe(self.args()), 0)
        output = json.loads(out.getvalue())
        self.assertEqual(output['mode'], 'dry_run_only')
        self.assertEqual(output['sample_count'], 1)
        self.assertFalse(output['gpu_started'])
        self.assertFalse(output['model_downloaded'])

    def test_4b_model_requires_explicit_fallback(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                probe.probe(self.args() + ['--model', probe.FALLBACK])
        self.assertEqual(raised.exception.code, 2)

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
