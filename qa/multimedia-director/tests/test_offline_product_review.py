"""Offline tests for product review GUI's noninteractive safety contract.

No tkinter windows, real ABO photos, network, secrets or GPU are used in CI.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/review-product-images.py"
spec = importlib.util.spec_from_file_location("bico_product_review", SCRIPT)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def make_png(index):
    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xffffffff))
    data = b"\x00" + bytes((index, 128, 180))
    return (bytes.fromhex("89504e470d0a1a0a")
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(data))
            + chunk(b"IEND", b""))


class HumanReviewOfflineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bico-review-test-")
        self.root = Path(self.temp.name)
        self.rows = []
        for idx in range(2):
            path = self.root / ("synthetic-" + str(idx) + ".png")
            blob = make_png(idx)
            path.write_bytes(blob)
            self.rows.append({
                "sku": "SYNTH" + str(idx), "image_sha256": hashlib.sha256(blob).hexdigest(),
                "local_image_path": str(path),
                "source_url": "https://example.org/synthetic/" + str(idx),
                "category": "synthetic", "proposed_split": "train" if idx == 0 else "test",
                "title_metadata_not_visual_fact": "Synthetic fixture, not actual product",
                "commercial_training_approved": False, "training_ready": False,
            })
        self.dataset = self.root / "synthetic-review.jsonl"
        self.save()
        self.state = self.root / "manual-review.json"

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.dataset.write_text(
            "\n".join(json.dumps(r) for r in self.rows) + "\n", encoding="utf-8"
        )

    def decision(self):
        r = self.rows[0]
        return {
            "sku": r["sku"], "image_sha256": r["image_sha256"],
            "source_url": r["source_url"], "status": "candidate",
            "category_corrected": "synthetic", "observed_facts": "synthetic RGB pixel",
            "preservation_rules": "Do not alter image",
            "training_approved": False, "third_party_gpu_allowed": False,
            "annotation_finalized": False,
        }

    def test_synthetic_dataset_loads_without_gui(self):
        rows = review.load_rows(self.dataset)
        self.assertEqual(len(rows), 2)
        self.assertEqual(review.source_image(rows[0]), Path(self.rows[0]["local_image_path"]))

    def test_headless_audit_requires_no_torch_or_tkinter(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.dataset), "--audit"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["source_images_valid"], 2)
        self.assertEqual(data["training_approved"], 0)

    def test_save_button_is_bound_to_real_save_action(self):
        # Tkinter need not initialize on the public CI runner; ensure the UI
        # action is not the previous no-op navigation(0).
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('text="Simpan", command=save_current', source)
        self.assertNotIn('text="Simpan", command=lambda: navigate(0)', source)

    def test_persist_decision_commits_only_after_successful_write(self):
        d = self.decision()
        decisions = {}
        review.persist_decision(self.state, decisions, d)
        self.assertEqual(decisions[d["sku"]], d)
        self.assertEqual(review.read_state(self.state, self.rows)[d["sku"]], d)

    def test_persist_decision_disk_failure_keeps_memory_and_disk_unchanged(self):
        from unittest.mock import patch
        d = self.decision()
        existing = {d["sku"]: d.copy()}
        review.write_state(self.state, existing)
        before = self.state.read_bytes()
        altered = {**d, "status": "needs_check"}
        with patch.object(review, "write_state", side_effect=OSError("simulated disk failure")):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                review.persist_decision(self.state, existing, altered)
        self.assertEqual(existing[d["sku"]]["status"], "candidate")
        self.assertEqual(self.state.read_bytes(), before)

    def test_state_atomic_round_trip(self):
        d = self.decision()
        review.write_state(self.state, {d["sku"]: d})
        result = review.read_state(self.state, self.rows)
        self.assertEqual(result[d["sku"]]["status"], "candidate")
        self.assertFalse(result[d["sku"]]["training_approved"])

    def test_reject_training_approval_in_saved_review(self):
        d = self.decision()
        d["training_approved"] = True
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "never authorize"):
            review.read_state(self.state, self.rows)

    def test_reject_gpu_transfer_in_saved_review(self):
        d = self.decision()
        d["third_party_gpu_allowed"] = True
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "never authorize"):
            review.read_state(self.state, self.rows)

    def test_reject_changed_source_hash(self):
        d = self.decision()
        d["image_sha256"] = "a" * 64
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            review.read_state(self.state, self.rows)

    def test_reject_unknown_source_sku(self):
        d = self.decision()
        d["sku"] = "UNKNOWN"
        review.write_state(self.state, {"UNKNOWN": d})
        with self.assertRaisesRegex(ValueError, "missing or SHA256 mismatch"):
            review.read_state(self.state, self.rows)

    def test_reject_tampered_photo(self):
        photo = Path(self.rows[0]["local_image_path"])
        photo.write_bytes(photo.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            review.source_image(self.rows[0])

    def test_reject_dataset_approved_for_training(self):
        self.rows[0]["training_ready"] = True
        self.save()
        with self.assertRaisesRegex(ValueError, "prematurely approved"):
            review.load_rows(self.dataset)

    def test_reject_duplicate_sku(self):
        self.rows[1]["sku"] = self.rows[0]["sku"]
        self.save()
        with self.assertRaisesRegex(ValueError, "invalid or prematurely approved"):
            review.load_rows(self.dataset)

    def test_exports_decisions_but_not_images_and_no_overwrite(self):
        d = self.decision()
        review.write_state(self.state, {d["sku"]: d})
        target = self.root / "export.jsonl"
        p = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.dataset),
                            "--state", str(self.state), "--export", str(target)],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        payload = json.loads(target.read_text().strip())
        self.assertFalse(payload["training_approved"])
        self.assertNotIn("image_bytes", payload)
        p2 = subprocess.run([sys.executable, str(SCRIPT), "--data", str(self.dataset),
                             "--state", str(self.state), "--export", str(target)],
                            capture_output=True, text=True)
        self.assertEqual(p2.returncode, 2)
        self.assertIn("refusing to overwrite", p2.stderr)

    def test_reject_unsafe_review_status(self):
        d = self.decision()
        d["status"] = "approved_for_training"
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "invalid review status"):
            review.read_state(self.state, self.rows)


    def draft(self, row_index=0):
        row = self.rows[row_index]
        return {
            "schema": review.DRAFT_SCHEMA,
            "item_id": row["sku"],
            "image_sha256": row["image_sha256"],
            "image_source_url": row["source_url"],
            "proposed_split": "train",
            "category_corrected_proposal": "synthetic",
            "annotation_status": "AI_DRAFT_NEEDS_INDEPENDENT_HUMAN_REVIEW",
            "training_approved": False,
            "third_party_gpu_allowed": False,
            "annotation_finalized": False,
            "license_review": "pending",
            "brand_privacy_claims_review": "pending",
            "target": {
                "schema": review.TARGET_SCHEMA, "task": "product_photo",
                "visual": {
                    "observed_facts": ["synthetic RGB source pixels"],
                    "unknowns": ["not a real product"],
                },
                "preservation_rules": ["do not change"],
                "concepts": [
                    {"title": "A", "scene": "studio A", "mood": "soft", "tagline": "a"},
                    {"title": "B", "scene": "studio B", "mood": "warm", "tagline": "b"},
                    {"title": "C", "scene": "studio C", "mood": "contrast", "tagline": "c"},
                ],
            },
        }

    def draft_file(self, items):
        path = self.root / "assistant-drafts.jsonl"
        path.write_text("\n".join(json.dumps(i) for i in items) + "\n",
                        encoding="utf-8")
        return path

    def test_valid_train_only_draft_is_review_hint_not_approval(self):
        draft = self.draft()
        items = review.load_ai_drafts(self.draft_file([draft]), self.rows)
        self.assertIn(self.rows[0]["sku"], items)
        self.assertFalse(items[self.rows[0]["sku"]]["training_approved"])
        self.assertFalse(self.state.exists())

    def test_draft_for_holdout_is_rejected(self):
        draft = self.draft(row_index=1)
        with self.assertRaisesRegex(ValueError, "validation/test holdout"):
            review.load_ai_drafts(self.draft_file([draft]), self.rows)

    def test_draft_with_wrong_image_checksum_is_rejected(self):
        draft = self.draft()
        draft["image_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            review.load_ai_drafts(self.draft_file([draft]), self.rows)

    def test_draft_with_wrong_source_url_is_rejected(self):
        draft = self.draft()
        draft["image_source_url"] = "https://example.org/wrong"
        with self.assertRaisesRegex(ValueError, "provenance"):
            review.load_ai_drafts(self.draft_file([draft]), self.rows)

    def test_draft_with_license_approval_is_rejected(self):
        draft = self.draft()
        draft["training_approved"] = True
        with self.assertRaisesRegex(ValueError, "cannot authorize training"):
            review.load_ai_drafts(self.draft_file([draft]), self.rows)

    def test_draft_with_duplicate_scenes_is_rejected(self):
        draft = self.draft()
        draft["target"]["concepts"][2]["scene"] = draft["target"]["concepts"][1]["scene"]
        with self.assertRaisesRegex(ValueError, "duplicated scenes"):
            review.load_ai_drafts(self.draft_file([draft]), self.rows)

    def test_duplicate_draft_sku_is_rejected(self):
        draft = self.draft()
        with self.assertRaisesRegex(ValueError, "duplicate assistant draft"):
            review.load_ai_drafts(self.draft_file([draft, draft]), self.rows)

    def test_draft_cli_audit_never_writes_review_decisions(self):
        draft_path = self.draft_file([self.draft()])
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--data", str(self.dataset),
             "--drafts", str(draft_path), "--audit"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["ai_drafts_checked"], 1)
        self.assertEqual(data["training_approved"], 0)
        self.assertFalse(self.state.exists())


    def test_readiness_reports_zero_human_reviews_and_training_no_go(self):
        report = review.review_readiness_report(self.rows, {}, {}, verify_images=True)
        self.assertEqual(report["source_original_sha256_verified"], 2)
        self.assertEqual(report["review_status_counts"]["pending"], 2)
        self.assertEqual(report["training_approved"], 0)
        self.assertFalse(report["baseline_eligible"])
        self.assertEqual(report["status"], "NO_GO_UNAPPROVED_DATA")

    def test_readiness_prioritizes_train_draft_but_does_not_mark_approved(self):
        item = self.draft()
        report = review.review_readiness_report(
            self.rows, {}, {item["item_id"]: item}, verify_images=False
        )
        self.assertEqual(report["assistant_draft_total"], 1)
        self.assertEqual(report["assistant_drafts_pending_independent_review"], 1)
        self.assertEqual(report["outstanding_review_queue"][0]["sku"], self.rows[0]["sku"])
        self.assertEqual(report["source_original_sha256_verified"], 0)
        self.assertEqual(report["candidate_visual_review_forms_with_all_fields"], 0)

    def test_readiness_candidate_with_missing_fields_stays_pending(self):
        decision = self.decision()
        report = review.review_readiness_report(
            self.rows, {decision["sku"]: decision}, {}, verify_images=False
        )
        self.assertEqual(report["review_status_counts"]["candidate"], 1)
        self.assertEqual(report["candidate_visual_review_forms_with_all_fields"], 0)
        self.assertEqual(report["outstanding_review_queue"][0]["reason_codes"],
                         ["review_form_missing_fields"])

    def test_complete_candidate_form_is_not_training_rights_approval(self):
        decision = self.decision()
        decision.update({
            "reviewer": "synthetic-reviewer",
            "category_corrected": "synthetic",
            "observed_facts": "synthetic pixel",
            "unknowns": "not a product",
            "preservation_rules": "keep image",
            "concept_1": "studio A", "concept_2": "studio B", "concept_3": "studio C",
            "brand_privacy_notes": "synthetic only",
        })
        report = review.review_readiness_report(
            self.rows, {decision["sku"]: decision}, {}, verify_images=False
        )
        self.assertEqual(report["candidate_visual_review_forms_with_all_fields"], 1)
        self.assertEqual(report["training_approved"], 0)
        self.assertFalse(report["third_party_gpu_allowed"])

    def test_readiness_source_photo_tampering_fails(self):
        source = Path(self.rows[1]["local_image_path"])
        source.write_bytes(source.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            review.review_readiness_report(self.rows, {}, {}, verify_images=True)

    def test_report_refuses_overwrite(self):
        target = self.root / "report.json"
        result = review.review_readiness_report(self.rows, {}, {}, verify_images=False)
        review.write_readiness_report(target, result)
        self.assertTrue(target.exists())
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            review.write_readiness_report(target, result)

    def test_saved_review_cannot_set_annotation_finalized(self):
        d = self.decision()
        d["annotation_finalized"] = True
        review.write_state(self.state, {d["sku"]: d})
        with self.assertRaisesRegex(ValueError, "never authorize"):
            review.read_state(self.state, self.rows)

    def test_saved_review_cannot_set_license_or_privacy_approved(self):
        for key in ("license_approval", "privacy_approval"):
            d = self.decision()
            d[key] = "approved"
            review.write_state(self.state, {d["sku"]: d})
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "never authorize"):
                    review.read_state(self.state, self.rows)

    def test_saved_review_source_url_and_split_must_match(self):
        for key, bad in (("source_url", "https://not-the-source.org"),
                         ("proposed_split", "train" if self.rows[0]["proposed_split"] == "test" else "test")):
            d = self.decision()
            d[key] = bad
            review.write_state(self.state, {d["sku"]: d})
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "source URL or proposed split"):
                    review.read_state(self.state, self.rows)

    def test_cli_readiness_reports_without_ai_labels_or_overwriting(self):
        target = self.root / "readiness-report.json"
        argv = [sys.executable, str(SCRIPT), "--data", str(self.dataset),
                "--readiness-report", str(target)]
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(report["review_status_counts"]["pending"], 2)
        self.assertEqual(report["training_approved"], 0)
        self.assertFalse(report["baseline_eligible"])
        result2 = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result2.returncode, 2)
        self.assertIn("refusing to overwrite", result2.stderr)



    def test_priority_order_shows_train_draft_first_even_if_input_is_reversed(self):
        reversed_rows = list(reversed(self.rows))
        suggestion = {self.rows[0]["sku"]: self.draft()}
        ordered = review.review_priority_order(reversed_rows, {}, suggestion)
        self.assertEqual(reversed_rows[ordered[0]]["sku"], self.rows[0]["sku"])
        self.assertEqual(len(ordered), 2)

    def test_priority_order_excludes_rejected_and_candidate_rows(self):
        decisions = {
            self.rows[0]["sku"]: {"status": "candidate"},
            self.rows[1]["sku"]: {"status": "reject"},
        }
        self.assertEqual(review.review_priority_order(self.rows, decisions, {}), [])

    def test_priority_order_includes_pending_and_needs_check(self):
        decisions = {self.rows[0]["sku"]: {"status": "needs_check"}}
        order = review.review_priority_order(
            self.rows, decisions, {self.rows[0]["sku"]: self.draft()}
        )
        self.assertEqual([self.rows[i]["sku"] for i in order],
                         [self.rows[0]["sku"], self.rows[1]["sku"]])

    def test_priority_order_cannot_make_test_draft_take_priority(self):
        # Train must be prioritized; even malformed caller-provided draft dict
        # cannot schedule an unseen holdout as a train sample.
        reversed_rows = list(reversed(self.rows))
        order = review.review_priority_order(
            reversed_rows, {}, {self.rows[1]["sku"]: {"bogus": "draft"}}
        )
        self.assertEqual(reversed_rows[order[0]]["proposed_split"], "train")

    def test_priority_order_does_not_change_review_decisions(self):
        decisions = {self.rows[0]["sku"]: {"status": "needs_check"}}
        before = json.dumps(decisions, sort_keys=True)
        review.review_priority_order(self.rows, decisions, {})
        self.assertEqual(json.dumps(decisions, sort_keys=True), before)
        self.assertEqual(decisions[self.rows[0]["sku"]]["status"], "needs_check")



if __name__ == "__main__":
    unittest.main()
