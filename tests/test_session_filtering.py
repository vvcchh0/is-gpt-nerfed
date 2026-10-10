"""Internal Codex source classification regressions; all profiles are temporary and inference is fake."""
import argparse
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from unittest import mock

import test_dgc

dgc = test_dgc.dgc


class SessionFilteringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nerfed sources ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.codex = self.root / "Codex home"
        self.ledger = self.root / "ledger"
        self.codex.mkdir()
        state = {"CODEX_HOME": str(self.codex), "NERFED_HOME": str(self.ledger)}
        filenames = {
            "CONFIG_PATH": "config.json", "EVENTS_PATH": "events.jsonl", "PROBES_INDEX": "probes.jsonl",
            "SESSIONS_DIR": "sessions", "PROBES_DIR": "probes", "ERRORS_PATH": "errors.log",
            "WORKER_LOG": "worker.log", "LOG_PATH": "log.jsonl", "ACCOUNT_PATH": "account.json",
            "HOOKS_STATUS_PATH": "hooks_status.json", "CODEX_VERSIONS_PATH": "codex_versions.json",
            "UPDATE_PATH": "update.json", "STATE_PATH": "state.json",
        }
        state.update({key: str(self.ledger / name) for key, name in filenames.items()})
        patcher = mock.patch.multiple(dgc, **state)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"CODEX_HOME": str(self.codex), "NERFED_HOME": str(self.ledger),
                                           "NERFED_NO_UPDATE_CHECK": "1", "FAKE_CODEX_MODEL": "gpt-6-astra"})
        env.start()
        self.addCleanup(env.stop)
        for key in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_SANDBOX_NETWORK_DISABLED", "NERFED_PROBE_PROCESS"):
            os.environ.pop(key, None)
        dgc.ensure_dirs()
        self.cfg = {**dgc.DEFAULT_CONFIG, "codex_bin": test_dgc.FAKE_CODEX, "frequency": "turns:1",
                    "mode": "auto", "passive": False, "notify": False, "sound": False, "check_updates": False}
        dgc.save_config(self.cfg)

    def database(self, rows, *, optional=True, preview=True):
        self.db = self.codex / "state_123.sqlite"
        fields = {"id": "TEXT PRIMARY KEY", "rollout_path": "TEXT", "thread_source": "TEXT", "cwd": "TEXT",
                  "model": "TEXT", "reasoning_effort": "TEXT", "archived": "INTEGER", "updated_at_ms": "INTEGER",
                  "title": "TEXT", "name": "TEXT", "originator": "TEXT"}
        if optional:
            fields.update(source="TEXT", parent_thread_id="TEXT")
        if preview:
            fields["preview"] = "TEXT"
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("CREATE TABLE threads (" + ", ".join(f"{key} {value}" for key, value in fields.items()) + ")")
            for row in rows:
                record = {"thread_source": "cli", "cwd": str(self.root), "model": "gpt-6-astra",
                          "reasoning_effort": "xhigh", "archived": 0, "updated_at_ms": int(dgc.now() * 1000),
                          "title": "ordinary session", "originator": "Codex Desktop", **row}
                if isinstance(record.get("source"), dict):
                    record["source"] = json.dumps(record["source"])
                values = [record.get(key) for key in fields]
                con.execute("INSERT INTO threads VALUES (" + ", ".join("?" for _ in fields) + ")", values)
        return self.db

    def rollout(self, name, **meta):
        path = self.codex / "sessions" / (name + ".jsonl")
        path.parent.mkdir(exist_ok=True)
        path.write_text(test_dgc.rollout_lines({"type": "session_meta", "payload": {"id": name, **meta}},
                                               test_dgc.turn(1, "gpt-6-astra", "xhigh")), encoding="utf-8")
        return str(path)

    def ledger_session(self, sid, **fields):
        st = dgc.new_session(sid)
        st.update({"kind": "main", "turns": 8, "requested": True, **fields})
        dgc.save_session(st)
        return st

    def test_source_variants_and_unknown_fallback(self):
        variants = ["subagent", "guardian_review", "sub_agent_review", "subAgentReview", "subAgentCompact",
                    "subAgentThreadSpawn", "subAgentOther", {"subagent": {"other": "guardian"}},
                    {"subAgentThreadSpawn": {"parentThreadId": "parent"}}, {"type": "subAgentOther"}]
        for source in variants:
            for encoded in (source, json.dumps(source)):
                with self.subTest(source=encoded):
                    self.assertTrue(dgc.internal_session({"source": encoded}))
        for record in ({}, {"source": "unknown"}, {"source": "cli"}, {"source": "appServer"},
                       {"source": "{broken"}, {"title": "Guardian review", "parent_thread_id": "parent"},
                       {"source": {"other": "guardian"}}):
            with self.subTest(record=record):
                self.assertFalse(dgc.internal_session(record))

    def test_db_lists_filter_all_sources_and_preserve_named_main_and_user_fork(self):
        path = self.rollout("rollout-internal", source={"subagent": {"other": "guardian"}})
        self.database([
            {"id": "legacy", "thread_source": "subagent"}, {"id": "guardian", "thread_source": "guardian_review"},
            {"id": "structured", "source": {"subagent": {"other": "guardian"}}},
            {"id": "api-variant", "thread_source": "subAgentCompact"},
            {"id": "metadata", "thread_source": None, "rollout_path": path},
            {"id": "named-main", "title": "Guardian review"}, {"id": "unknown", "thread_source": "unknown"},
            {"id": "user-fork", "parent_thread_id": "original-main"}, {"id": "archived", "archived": 1},
        ])
        for rows in (dgc.db_recent_main_threads(), dgc.db_recent_threads_detailed(0)):
            self.assertEqual({row["id"] for row in rows}, {"named-main", "unknown", "user-fork"})
            self.assertTrue(all(row["model"] == "gpt-6-astra" and row["reasoning_effort"] == "xhigh" for row in rows))
        self.assertEqual(dgc.db_thread("structured")["source"], '{"subagent": {"other": "guardian"}}')

    def test_old_schema_without_optional_source_or_preview_uses_rollout_metadata(self):
        path = self.rollout("old-guardian", thread_source="guardian_review", parent_thread_id="parent")
        self.database([{"id": "guardian", "rollout_path": path}, {"id": "main", "thread_source": None}],
                      optional=False, preview=False)
        row = dgc.db_thread("main")
        self.assertNotIn("source", row)
        self.assertEqual((row["model"], row["reasoning_effort"]), ("gpt-6-astra", "xhigh"))
        self.assertEqual([row["id"] for row in dgc.db_recent_threads_detailed(0)], ["main"])

    def test_filter_precedes_limits_and_uses_one_read_connection(self):
        stamp = int(dgc.now() * 1000)
        rows = [{"id": f"internal-{i:03}", "source": {"subagent": {"other": "guardian"}},
                 "updated_at_ms": stamp + 500 - i} for i in range(151)]
        rows += [{"id": f"main-{i:03}", "updated_at_ms": stamp - i} for i in range(45)]
        self.database(rows)
        with mock.patch.object(dgc.sqlite3, "connect", wraps=sqlite3.connect) as connect:
            detailed = dgc.db_recent_threads_detailed(0)
        connect.assert_called_once()
        self.assertEqual([row["id"] for row in detailed], [f"main-{i:03}" for i in range(40)])
        self.assertEqual(len(dgc.db_recent_main_threads(25)), 25)
        self.assertEqual(dgc.db_recent_main_thread(str(self.root))["id"], "main-000")
        self.assertEqual(dgc.db_recent_main_threads(0), [])

    def test_link_reclassifies_old_ledger_without_losing_history(self):
        self.database([{"id": "guardian", "thread_source": "guardian_review",
                        "source": {"subagent": {"other": "guardian"}}, "parent_thread_id": "main"}])
        st = self.ledger_session("guardian", probes=["historic-probe"], evidence=[{"detail": "historic finding"}])
        dgc.link_session(st)
        self.assertEqual(st["kind"], "subagent")
        self.assertEqual(st["parent_thread_id"], "main")
        self.assertEqual(st["probes"], ["historic-probe"])
        self.assertEqual(st["evidence"], [{"detail": "historic finding"}])
        self.assertFalse(dgc.probe_due(st, self.cfg, "account"))

    def test_rollout_only_link_classification_preserves_user_forks(self):
        for name, meta, expected in (("guardian", {"source": {"subagent": {"other": "guardian"}}}, "subagent"),
                                     ("fork", {"source": "cli", "parent_thread_id": "main"}, "main")):
            with self.subTest(name=name):
                st = dgc.new_session(name)
                st["transcript_path"] = self.rollout(name, **meta)
                dgc.link_session(st)
                self.assertEqual(st["kind"], expected)

    def test_snapshot_does_not_resurrect_old_main_ledgers_or_delete_history(self):
        path = self.rollout("orphan-rollout", source={"subagent": {"other": "guardian"}})
        self.database([{"id": "guardian", "thread_source": "guardian_review"},
                       {"id": "named-main", "name": "Guardian review", "title": "preserved title"}])
        self.ledger_session("guardian", probes=["historic-probe"])
        self.ledger_session("orphan-source", source={"subagent": {"other": "guardian"}})
        self.ledger_session("orphan-rollout", transcript_path=path)
        self.ledger_session("named-main")
        dgc.append_jsonl(dgc.PROBES_INDEX, {"id": "historic-probe", "thread_id": "guardian", "mode": "fork",
                                          "status": "failed", "account_id": "unknown"})
        before_db, before_rollout = self.db.read_bytes(), Path(path).read_bytes()
        before_index = Path(dgc.PROBES_INDEX).read_bytes()
        with mock.patch.object(dgc, "hooks_status", return_value={}):
            snapshot = dgc.build_snapshot(self.cfg)
        self.assertEqual([row["id"] for row in snapshot["threads"]], ["named-main"])
        self.assertEqual(snapshot["threads"][0]["title"], "Guardian review")
        self.assertEqual(self.db.read_bytes(), before_db)
        self.assertEqual(Path(path).read_bytes(), before_rollout)
        self.assertEqual(Path(dgc.PROBES_INDEX).read_bytes(), before_index)
        self.assertEqual(dgc.load_session("guardian")["probes"], ["historic-probe"])

    def test_hook_stop_reclassifies_old_main_and_does_not_spawn_any_worker(self):
        self.database([{"id": "guardian", "thread_source": "guardian_review"}])
        self.ledger_session("guardian", probes=["historic-probe"])
        dgc.save_config({**self.cfg, "fresh_frequency": "1m"})
        with mock.patch.object(dgc, "spawn_worker") as spawn, mock.patch.object(dgc, "spawn_fresh_worker") as fresh:
            test_dgc.run_hook({"session_id": "guardian", "hook_event_name": "Stop", "cwd": str(self.root)})
        spawn.assert_not_called()
        fresh.assert_not_called()
        st = dgc.load_session("guardian")
        self.assertEqual(st["kind"], "subagent")
        self.assertEqual(st["probes"], ["historic-probe"])

    def test_hook_source_json_without_db_is_internal(self):
        with mock.patch.object(dgc, "spawn_worker") as spawn:
            test_dgc.run_hook({"session_id": "guardian", "hook_event_name": "Stop",
                               "source": {"subagent": {"other": "guardian"}}})
        spawn.assert_not_called()
        self.assertEqual(dgc.load_session("guardian")["kind"], "subagent")

    def test_tick_and_direct_spawn_reject_old_main_guardian(self):
        self.database([{"id": "guardian", "source": {"subagent": {"other": "guardian"}}}])
        self.ledger_session("guardian")
        with mock.patch.object(dgc, "spawn_worker") as spawn, redirect_stdout(io.StringIO()):
            self.assertEqual(dgc.cmd_tick(argparse.Namespace()), 0)
        spawn.assert_not_called()
        with mock.patch.object(dgc.subprocess, "Popen") as popen:
            self.assertFalse(dgc.spawn_worker("guardian", self.cfg))
        popen.assert_not_called()

    def test_manual_modes_queue_and_worker_reject_internal_before_probe_record(self):
        self.database([{"id": "guardian", "thread_source": "guardian_review"}])
        self.ledger_session("guardian", probes=["historic-probe"], requested=False)
        with mock.patch.object(dgc.cas, "probe_thread", side_effect=AssertionError("must not infer")) as infer:
            for mode in ("auto", "fork", "self"):
                with self.subTest(mode=mode):
                    rc, output = test_dgc.run_cli(["probe", "now", "--mode", mode, "--thread", "guardian"],
                                                 {"CODEX_SANDBOX_NETWORK_DISABLED": "1"})
                    self.assertIn("internal Codex session", str(rc))
                    self.assertNotIn("Queued", output)
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(dgc.cmd_worker(argparse.Namespace(thread="guardian", queries=1)), 0)
            self.assertIn("worker aborted", output.getvalue())
        infer.assert_not_called()
        self.assertEqual(list(Path(dgc.PROBES_DIR).glob("*.json")), [])
        self.assertFalse(Path(dgc.PROBES_INDEX).exists())
        st = dgc.load_session("guardian")
        self.assertEqual(st["kind"], "subagent")
        self.assertFalse(st["requested"])
        self.assertEqual(st["probes"], ["historic-probe"])

    def test_direct_fork_and_self_entrypoints_also_reject_internal(self):
        self.ledger_session("guardian", source='{"subagent":{"other":"guardian"}}')
        for call in (lambda: dgc.run_fork_probe("guardian", self.cfg),
                     lambda: dgc.start_self_probe("guardian", None, self.cfg, "gpt-6-astra"),
                     lambda: dgc.start_self_probe(None, "guardian", self.cfg, "gpt-6-astra")):
            with self.assertRaisesRegex(SystemExit, "internal Codex session"):
                call()
        self.assertEqual(list(Path(dgc.PROBES_DIR).glob("*.json")), [])

    def test_recent_hook_resolution_skips_internal_and_selects_main(self):
        self.database([{"id": "guardian", "thread_source": "guardian_review"}, {"id": "main"}])
        for sid in ("main", "guardian"):
            dgc.append_jsonl(dgc.EVENTS_PATH, {"ts": dgc.iso(), "event": "Stop", "sid": sid, "cwd": os.getcwd()})
        self.assertEqual(dgc.resolve_thread(None), ("main", "recent-hook-event"))

    def test_named_main_with_parent_remains_probeable_using_fake_codex(self):
        self.database([{"id": "named-main", "title": "Guardian review", "parent_thread_id": "original-main"}])
        rc, output = test_dgc.run_cli(["probe", "now", "--mode", "fork", "--thread", "named-main", "--queries", "1"])
        self.assertEqual(rc, 0, output)
        rows = list(dgc.iter_jsonl(dgc.PROBES_INDEX))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["thread_id"], rows[0]["verdict"]), ("named-main", "AMBIGUOUS"))

    def test_audit_default_excludes_internal_and_flag_includes_them(self):
        self.rollout("guardian", thread_source="guardian_review")
        self.rollout("subagent", thread_source="subagent")
        self.rollout("structured", source=json.dumps({"subagent": {"other": "guardian"}}))
        self.rollout("main", source="cli", title="Guardian review", parent_thread_id="parent")
        self.rollout("unknown", source="unknown")
        for include, expected in ((False, 2), (True, 5)):
            with self.subTest(include=include), redirect_stdout(io.StringIO()) as output:
                dgc.cmd_audit(argparse.Namespace(days=1, include_subagents=include))
            self.assertIn(f"audit: scanned {expected} rollouts", output.getvalue())


if __name__ == "__main__":
    unittest.main()
