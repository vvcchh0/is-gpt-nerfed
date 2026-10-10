"""Offline regression coverage for overlapping fingerprints and passive evidence provenance."""
import contextlib
import copy
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader(
    "fingerprint_resolution_backend", str(ROOT / "plugin/skills/is-gpt-nerfed/scripts/nerfed"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
backend = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(backend)


def analysis(top="gpt-6-astra", expected="gpt-5.6-luna"):
    rows = [{"model": top, "probability": 0.99, "score": 2.0},
            {"model": expected, "probability": 0.01, "score": 0.0}]
    return {"prediction": top, "probability": 0.99, "used_outputs": 3, "results": rows,
            "family_probabilities": [], "diagnostics": [],
            "calibration": {"queries": "3", "beta": 12.0, "cv_accuracy": 1.0}}


class FingerprintResolutionTests(unittest.TestCase):
    def test_exact_version_and_provider_prefix_are_preserved(self):
        self.assertEqual(backend.normalize_model(" OpenAI/GPT-6.1-SOL "), "gpt-6.1-sol")
        self.assertNotEqual(backend.normalize_model("gpt-6.1-sol"), "gpt-6-sol")

    def test_both_overlapping_models_are_neutral(self):
        for expected in ("gpt-6-astra", "gpt-6.1-sol", "openai/gpt-6.1-sol"):
            with self.subTest(expected=expected):
                a = backend.assess(expected, analysis(), [])
                self.assertEqual((a["verdict"], a["fingerprint_verdict"], a["direction"]),
                                 ("AMBIGUOUS", "AMBIGUOUS", None))
                self.assertEqual(a["fingerprint_resolution"], "overlap")
                self.assertEqual(a["fingerprint_group"], ["gpt-6-astra", "gpt-6.1-sol"])
                self.assertIn("cannot reliably distinguish", a["fingerprint_note"])

    def test_unlisted_and_other_models_keep_their_verdicts(self):
        self.assertEqual(backend.assess("gpt-6.1-sol", analysis("gpt-5.6-luna"), [])["verdict"], "UNLISTED")
        self.assertEqual(backend.assess("gpt-7-new", analysis(), [])["verdict"], "UNLISTED")
        self.assertEqual(backend.assess("gpt-5.6-luna", analysis("gpt-5.6-luna"), [])["verdict"], "MATCH")
        self.assertEqual(backend.assess("gpt-6-astra", analysis("gpt-5.6-luna", "gpt-6-astra"), [])["verdict"], "MISMATCH")

    def test_passive_override_preserves_independent_fingerprint(self):
        event = {"kind": "silent_effort_change", "detail": "reasoning effort max → xhigh with no settings change",
                 "ts": "2026-10-01T01:00:00Z", "severity": "hard"}
        a = backend.assess("gpt-6.1-sol", analysis(), [event])
        self.assertEqual((a["verdict"], a["direction"], a["verdict_basis"], a["fingerprint_verdict"]),
                         ("DOWNGRADED!", "hard", "passive", "AMBIGUOUS"))
        self.assertEqual(a["passive_reasons"], [{k: event[k] for k in ("kind", "detail", "ts")}])
        invalid = backend.assess("gpt-6.1-sol", None, [event])
        self.assertEqual((invalid["verdict"], invalid["fingerprint_verdict"], invalid["fingerprint_resolution"]),
                         ("DOWNGRADED!", "INVALID", "unavailable"))

    def test_neutral_finalize_does_not_notify_halt_or_alert(self):
        state = {"turns": 1, "alerts": []}

        @contextlib.contextmanager
        def locked(_):
            yield state

        cfg = {**backend.DEFAULT_CONFIG, "halt_on_mismatch": True, "announce_ok": True, "notify_on_ok": True}
        rec = {"id": "neutral-test", "thread_id": "test-parent", "queries": 3, "ts_start": backend.now()}
        with mock.patch.object(backend.core, "analyze_global_outputs", return_value=analysis()), \
             mock.patch.object(backend, "load_bank", return_value={}), \
             mock.patch.object(backend, "parent_hard_evidence", return_value=([], [])), \
             mock.patch.object(backend, "locked_session", side_effect=locked), \
             mock.patch.object(backend, "write_json"), mock.patch.object(backend, "append_jsonl") as index, \
             mock.patch.object(backend, "log_event"), \
             mock.patch.object(backend, "current_account", return_value={"id": "test-account"}), \
             mock.patch.object(backend, "notify") as notify, mock.patch.object(backend, "play_sound") as sound:
            result = backend.finalize_probe(rec, [{}], "gpt-6.1-sol", [], cfg, quiet=True)
        self.assertEqual(result["verdict"], "AMBIGUOUS")
        self.assertIsNone(result["p_expected"])
        self.assertEqual(state["alerts"], [])
        self.assertNotIn("halt", state)
        notify.assert_not_called()
        sound.assert_not_called()
        self.assertEqual(index.call_args.args[1]["fingerprint_resolution"], "overlap")

    def test_history_is_projected_without_rewriting_the_record(self):
        for expected, verdict in (("gpt-6-astra", "MATCH"), ("gpt-6.1-sol", "UNLISTED"),
                                  ("gpt-6.1-sol", "DOWNGRADED!")):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as directory, \
                 mock.patch.object(backend, "PROBES_DIR", directory):
                rec = {"id": "historical-test", "status": "done", "verdict": verdict,
                       "expected": expected, "prediction": "gpt-6-astra", "probability": 1.0, "used_outputs": 3,
                       "queries": 3, "confidence": "high", "quote": "old attribution"}
                if verdict == "DOWNGRADED!":
                    rec["hard_evidence"] = [{"kind": "silent_model_change", "detail": "model settings changed",
                                             "ts": "2026-10-01T01:00:00Z"}]
                original = copy.deepcopy(rec)
                backend.write_json(backend.probe_path(rec["id"]), rec)
                path = Path(backend.probe_path(rec["id"]))
                before = path.read_bytes()
                summary = backend.probe_summary(rec)
                self.assertEqual(summary["fingerprint_verdict"], "AMBIGUOUS")
                self.assertEqual(summary["verdict"], "DOWNGRADED!" if verdict == "DOWNGRADED!" else "AMBIGUOUS")
                line = backend.probe_line(summary)
                self.assertIn("not distinguishable", line)
                if verdict == "DOWNGRADED!":
                    self.assertIn("fingerprint AMBIGUOUS", line)
                    self.assertIn("silent_model_change", line)
                    self.assertIn("2026-10-01T01:00:00Z", line)
                else:
                    self.assertFalse(summary["is_downgrade"])
                    self.assertIsNone(summary["confidence"])
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(rec, original)

    def test_cli_explain_and_report_include_passive_provenance(self):
        event = {"kind": "silent_effort_change", "detail": "recorded effort change", "ts": "2026-10-01T01:00:00Z"}
        rec = {"id": "explain-test", "status": "done", "verdict": "DOWNGRADED!", "expected": "gpt-6.1-sol",
               "prediction": "gpt-6-astra", "probability": 1.0, "used_outputs": 3, "hard_evidence": [event]}
        with mock.patch.object(backend, "read_json", return_value=rec), contextlib.redirect_stdout(io.StringIO()) as output:
            backend.cmd_explain(type("Args", (), {"method": False, "probe_id": rec["id"]})())
        for value in ("fingerprint verdict: AMBIGUOUS", "overall basis: passive", event["kind"], event["ts"], event["detail"]):
            self.assertIn(value, output.getvalue())
        text = backend.report_text_for("Test", "gpt-6.1-sol", "max", [rec], [])
        self.assertIn(event["kind"], text)
        self.assertIn(event["ts"], text)


if __name__ == "__main__":
    unittest.main()
