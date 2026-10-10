#!/usr/bin/env python3
"""Standard-library, offline timing of the public ModelTrace probe workload.

Prints JSON to stdout. Never starts a real Codex binary, imports the nerfed CLI,
reads private sessions, or changes the caller's CODEX_HOME / NERFED_HOME.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "plugin" / "skills" / "is-gpt-nerfed" / "scripts"
BANK = ROOT / "plugin" / "assets" / "modeltrace" / "unified_bank.json"
FIXTURE = ROOT / "tests" / "fixtures" / "reference_subset.jsonl"


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline_cli_functions():
    """Compile only named definitions/constants; no CLI import or home lookup.

    Direction classification intentionally uses an empty model catalog. This
    isolates computation, so it does not time real catalog I/O or CLI delivery.
    """
    names = {
        "now", "iso", "normalize_model", "effort_idx", "model_version",
        "model_size", "model_profile", "compare_models", "classify_change",
        "assess", "new_scan_state", "scan_rollout", "scan_full",
    }
    constants = {"DEFAULT_CONFIG", "EFFORTS", "SIZE_TAGS", "MARGIN_SIGMA"}
    path = SCRIPTS / "nerfed"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    namespace = {"re": re, "json": json, "os": os, "dt": dt, "time": time,
                 "load_catalog": lambda: {}}
    definitions = []
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            definitions.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in constants:
                    namespace[target.id] = ast.literal_eval(node.value)
    missing = (names - found) | (constants - namespace.keys())
    if missing:
        raise RuntimeError("offline extraction needs updating: " + ", ".join(sorted(missing)))
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def measure(action, repeats, warmup, batch=1):
    for _ in range(warmup):
        action()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        for _ in range(batch):
            action()
        samples.append((time.perf_counter_ns() - started) / batch / 1_000_000)
    ordered = sorted(samples)
    return {"median_ms": round(statistics.median(samples), 6),
            "p95_ms": round(ordered[math.ceil(len(ordered) * .95) - 1], 6),
            "min_ms": round(ordered[0], 6), "samples": repeats,
            "iterations_per_sample": batch, "warmup_calls": warmup}


def read_fixture():
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped = {}
    for row in rows:
        grouped.setdefault(row["model_id"], []).append(row)
    selected = next((group[:3] for group in grouped.values() if len(group) >= 3), None)
    if selected is None:
        raise RuntimeError("public fixture needs three answers for one model")
    return rows, selected


def fixture_rollout(rows):
    """A small public fixture-derived JSONL stream, not a private/real rollout.

    Each reference text appears exactly once. Stable synthetic metadata avoids
    timing catalog I/O and evidence growth caused by changing fixture labels.
    """
    records = [{"type": "session_meta", "payload": {"originator": "offline-benchmark"}}]
    for i, row in enumerate(rows):
        records.append({"type": "turn_context", "payload": {
            "turn_id": str(i), "model": "fixture-model", "reasoning_effort": "high"}})
        records.append({"type": "response_item", "payload": {
            "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": row["text"]}]}})
    return ("\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n").encode("utf-8"), len(records)


def clean_child_env(temp_root):
    # Marker variables in the caller must never trigger fake-server failures or
    # writes. Only child processes receive these temporary home values.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CODEX_", "NERFED_", "FAKE_CODEX_"))}
    env.update(CODEX_HOME=str(temp_root / "codex"), NERFED_HOME=str(temp_root / "nerfed"),
               NERFED_NO_UPDATE_CHECK="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=101, help="samples per in-process metric (default: 101)")
    parser.add_argument("--warmup", type=int, default=5, help="untimed calls per in-process metric (default: 5)")
    parser.add_argument("--process-repeats", type=int, default=21, help="samples per fresh Python process metric (default: 21; 0 disables)")
    parser.add_argument("--fake-repeats", type=int, default=21, help="fake app-server setup samples (default: 21; 0 disables)")
    args = parser.parse_args()
    if args.repeats < 1 or min(args.warmup, args.process_repeats, args.fake_repeats) < 0:
        parser.error("repeats must be positive; other counts must be nonnegative")

    core = import_file("benchmark_modeltrace_core", SCRIPTS / "modeltrace_core.py")
    cli = offline_cli_functions()
    bank = core.load_bank(BANK)
    rows, selected = read_fixture()
    outputs = [{"text": row["text"], "expected_count": row["requested_count"]} for row in selected]
    numbers = [core.parse_numbers(out["text"]) for out in outputs]
    counts = [core.count_numbers(ns) for ns in numbers]
    analysis = core.analyze_global_outputs(outputs, bank)
    expected = selected[0]["model_id"]
    mismatched_expected = next(model["id"] for model in bank["models"] if model["id"] != analysis["prediction"])
    metrics = {}

    def record(name, action, batch=1):
        metrics[name] = measure(action, args.repeats, args.warmup, batch)

    record("bank_load_json", lambda: core.load_bank(BANK))
    record("parse_three_answers", lambda: [core.parse_numbers(out["text"]) for out in outputs], 10)
    record("features_three_preparsed_answers", lambda: [
        (core.hellinger_feature(cs), core.ordered_block_feature(ns)) for ns, cs in zip(numbers, counts)], 10)
    record("score_three_preparsed_answers", lambda: [core.robust_score_numbers(ns, bank) for ns in numbers])
    for n in (1, 2, 3):
        record(f"analyze_{n}_answers", lambda n=n: core.analyze_global_outputs(outputs[:n], bank))
    record("assess_match_precomputed_analysis", lambda: cli["assess"](analysis["prediction"], analysis, []), 100)
    record("assess_mismatch_precomputed_analysis_empty_catalog", lambda: cli["assess"](mismatched_expected, analysis, []), 100)
    record("analyze_and_assess_three_answers", lambda: cli["assess"](
        expected, core.analyze_global_outputs(outputs, bank), []))

    data, record_count = fixture_rollout(rows)
    with tempfile.TemporaryDirectory(prefix="nerfed-offline-benchmark-") as directory:
        temp_root = Path(directory)
        rollout = temp_root / "public-fixture-rollout.jsonl"
        rollout.write_bytes(data)
        record("scan_full_public_fixture_stream", lambda: cli["scan_full"](str(rollout), hidden=frozenset()))
        state, evidence = cli["scan_full"](str(rollout), hidden=frozenset())
        record("scan_incremental_no_new_bytes", lambda: cli["scan_rollout"](str(rollout), state), 100)
        tail = data.rfind(b"\n", 0, len(data) - 1) + 1

        def scan_tail():
            # Fresh state per iteration, already positioned before the last
            # public response_item; this measures an appended record's decode.
            cursor_state = cli["new_scan_state"]()
            cursor_state["cursor"] = tail
            return cli["scan_rollout"](str(rollout), cursor_state)

        record("scan_incremental_one_public_answer", scan_tail, 10)
        child_env = clean_child_env(temp_root)
        if args.process_repeats:
            def run_python(code, *values):
                subprocess.run([sys.executable, "-I", "-B", "-c", code, *map(str, values)],
                               env=child_env, check=True, capture_output=True, timeout=30)

            metrics["new_python_process_empty"] = measure(lambda: run_python("pass"), args.process_repeats, 0)
            code = ("import importlib.util,sys; "
                    "s=importlib.util.spec_from_file_location('core',sys.argv[1]); "
                    "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                    "m.load_bank(sys.argv[2])")
            metrics["new_python_process_core_import_and_bank_load"] = measure(
                lambda: run_python(code, SCRIPTS / "modeltrace_core.py", BANK), args.process_repeats, 0)
        if args.fake_repeats:
            sys.path.insert(0, str(SCRIPTS))
            try:
                cas = import_file("benchmark_codex_appserver", SCRIPTS / "codex_appserver.py")

                def fake_setup():
                    # Hardcoded public fake: deliberately no codex path option,
                    # no turn/start, no model inference, no real thread lookup.
                    app = cas.AppServer(str(ROOT / "tests" / "fake_codex.py"), env=child_env)
                    try:
                        app.initialize()
                        thread = cas.read_thread(app, "offline-public-fixture")
                        turn = cas.last_turn(app, thread["id"])
                        for _ in range(3):
                            cas.fork_ephemeral(app, thread, turn["id"])
                    finally:
                        app.close()

                metrics["fake_appserver_initialize_read_list_three_forks_close_no_inference"] = measure(
                    fake_setup, args.fake_repeats, 1)
            finally:
                sys.path.pop(0)

    sources = [SCRIPTS / "nerfed", SCRIPTS / "modeltrace_core.py", SCRIPTS / "codex_appserver.py", BANK, FIXTURE]
    result = {
        "schema_version": 1,
        "benchmark": "offline public fixture; no real Codex inference",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                        "platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count()},
        "dataset": {"bank_bytes": BANK.stat().st_size, "bank_models": len(bank["models"]),
                    "fixture_bytes": FIXTURE.stat().st_size, "fixture_rows": len(rows),
                    "fixture_models": len({r["model_id"] for r in rows}),
                    "selected_public_row_ids": [r["row_id"] for r in selected],
                    "selected_requested_counts": [r["requested_count"] for r in selected],
                    "selected_parsed_counts": list(map(len, numbers)),
                    "selected_text_characters": [len(r["text"]) for r in selected],
                    "scan_stream_bytes": len(data), "scan_stream_records": record_count,
                    "scan_stream_fixture_texts": len(rows), "scan_tail_bytes": len(data) - tail,
                    "scan_full_evidence_records": len(evidence)},
        "calibration": bank["calibration"],
        "statistics": {"clock": "perf_counter_ns", "unit": "milliseconds per operation",
                       "p95": "nearest rank ceil(0.95 * samples)",
                       "batch_note": "fast operations use batch means; p95 is across those means",
                       "process_note": "fresh Python processes with warm OS file cache, not cold machine boots"},
        "metrics": metrics,
        "source_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "limitations": ["No inference, network latency, queueing, first-token, or history-prefill measurement.",
                        "Fixture-derived scan stream is not a production rollout; no real catalog, ledger, hooks, or UI delivery is timed.",
                        "Fake-server setup is Python JSON-RPC plumbing, not real Codex startup or server-side fork cost.",
                        "Timing stages overlap in work and must not be summed as an end-to-end decomposition."],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
