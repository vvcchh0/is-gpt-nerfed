"""Offline research input/grouping contracts, independent of NumPy or sessions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fingerprint_research", ROOT / "tools/analyze_fingerprint_samples.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)
FIXTURE = ROOT / "tests/fixtures/reference_subset.jsonl"


class FingerprintResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = research.read_records(FIXTURE)
        cls.core = research.load_core()
        cls.bank = cls.core.load_bank(research.DEFAULT_BANK)

    def report(self, rows):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "samples.json"
            path.write_text(json.dumps({"records": rows}), encoding="utf-8")
            before = research.digest(research.DEFAULT_BANK)
            result = research.analyze([path], research.DEFAULT_BANK)
            self.assertEqual(before, research.digest(research.DEFAULT_BANK))
            return result

    def local_rows(self, count=3):
        row = self.rows[0]
        return [{"label": "out-of-bank-sol", "effort": "high", "language": language,
                 "output": row["text"], "expected_count": row["requested_count"],
                 "turn_index": index, "thread_alias": "same-thread"}
                for index, language in enumerate(["zh", "en", "zh"][:count])]

    def test_local_mixed_languages_preserve_three_turn_group_and_closed_set_scope(self):
        report = self.report(self.local_rows())
        self.assertEqual(len(report["three_answer_groups"]), 1)
        group = report["three_answer_groups"][0]
        self.assertEqual(group["language"], "mixed")
        self.assertEqual(group["used_outputs"], 3)
        self.assertFalse(group["label_present_in_bank"])
        self.assertIsNone(report["three_answer_summary"]["top1_correct"])

    def test_partial_and_unusable_groups_are_not_three_answer_results(self):
        partial = self.report(self.local_rows(2))
        self.assertEqual(partial["three_answer_groups"], [])
        self.assertEqual(len(partial["grouping"]["incomplete_group_sample_ids"]), 2)
        rows = self.local_rows()
        rows[1]["output"] = "1, 2, 3"
        report = self.report(rows)
        self.assertEqual(report["single_summary"]["usable"], 2)
        self.assertFalse(report["three_answer_groups"][0]["accepted"])
        self.assertEqual(report["three_answer_summary"]["usable"], 0)

    def test_text_hash_is_verified_before_attribution(self):
        rows = self.local_rows(1)
        rows[0]["response_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.report(rows)

    def test_scores_match_existing_scorer_and_margin_contract(self):
        row = self.rows[0]
        report = self.report([row])
        expected = self.core.analyze_global_outputs(
            [{"text": row["text"], "expected_count": row["requested_count"]}], self.bank)
        actual = report["singles"][0]
        self.assertEqual(actual["prediction"], expected["prediction"])
        self.assertAlmostEqual(actual["score_margin"],
                               expected["results"][0]["score"] - expected["results"][1]["score"])
        self.assertEqual([x["score"] for x in actual["ranking"]],
                         [x["score"] for x in expected["results"]])

    def test_feature_differences_count_within_and_between_pairs(self):
        left = self.local_rows()
        right = self.local_rows()
        for row in right:
            row["label"] = "another-declared-label"
            row["thread_alias"] = "other-thread"
        report = self.report(left + right)
        features = report["feature_differences"]
        self.assertEqual([x["pairs"] for x in features["within_label_effort"]], [3, 3])
        self.assertEqual(features["between_label_effort"][0]["pairs"], 9)
        self.assertAlmostEqual(features["between_label_effort"][0]["sample_center_cosine"], 1.0)
        self.assertEqual(len(report["three_answer_groups"]), 2)


if __name__ == "__main__":
    unittest.main()
