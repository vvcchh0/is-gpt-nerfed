#!/usr/bin/env python3
"""Offline exploratory fingerprint analysis; standard library only.

Reads explicit JSON/JSONL inputs and a bank; never calls a model, reads session
homes, trains a bank, or writes a bank. JSON may be a list or {"records": [...]}.
Local records may use label, effort, language, output, expected_count,
turn_index and thread_alias. Public ModelTrace JSONL fields are also supported.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import statistics
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "plugin/skills/is-gpt-nerfed/scripts/modeltrace_core.py"
DEFAULT_BANK = ROOT / "plugin/assets/modeltrace/unified_bank.json"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_core():
    spec = importlib.util.spec_from_file_location("research_modeltrace_core", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_records(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    if Path(path).suffix.lower() == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = json.loads(text)
        if isinstance(values, dict):
            values = values["records"]
    if not isinstance(values, list) or not all(isinstance(row, dict) for row in values):
        raise ValueError(f"{path}: expected a record list or a records object")
    return values


def normalize(row, index, input_name):
    text = row.get("output", row.get("text", ""))
    if not isinstance(text, str):
        raise ValueError(f"{input_name} record {index}: output/text must be a string")
    expected = int(row.get("expected_count", row.get("requested_count", 0)) or 0)
    if expected < 0:
        raise ValueError("expected_count must be nonnegative")
    language = row.get("language")
    style = row.get("format")
    # These are requested prompt strata, not a claim about output compliance.
    # Public research uses the fixed 12-environment challenge suite.
    condition = row.get("condition_id")
    if row.get("challenge_id") and condition and condition.startswith("environment-"):
        environment = int(condition.rsplit("-", 1)[1])
        language = language or ("zh" if environment in (4, 7, 8, 9, 10, 11, 12) else "en")
        style = style or ("json" if environment in (1, 2, 3, 6) else "prose")
    language = language or "unspecified"
    language = {"chinese": "zh", "english": "en"}.get(str(language).lower(), language)
    split = row.get("split", row.get("purpose", "unspecified"))
    sample_id = row.get("row_id", f"{input_name}:{index}")
    return {"id": sample_id, "input": input_name,
            "label": row.get("label", row.get("model_id", "unspecified")),
            "effort": row.get("effort", row.get("reasoning_effort", "unspecified")),
            "language": language, "format": style or "unspecified", "split": split,
            "condition": condition or "unspecified", "thread_alias": row.get("thread_alias"),
            "group_key": condition or row.get("thread_alias") or "ungrouped",
            "turn_index": row.get("turn_index", row.get("task_index", index)),
            "expected_count": expected, "text": text,
            "response_sha256": row.get("response_sha256"),
            "identity_independently_attested": row.get("identity_independently_attested"),
            "context_id_sha256": row.get("context_id_sha256")}


def unit(values):
    norm = max(math.sqrt(sum(x * x for x in values)), 1e-12)
    return [x / norm for x in values]


def cosine(left, right):
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(unit(left), unit(right)))))


def projected_feature(numbers, bank, core):
    artifact = bank["robust"]["hellinger"]
    raw = core.hellinger_feature(core.count_numbers(numbers))
    standardized = [(v - m) / s for v, m, s in zip(raw, artifact["feature_mean"], artifact["feature_scale"])]
    return unit(core._subtract_basis(standardized, artifact["nuisance_basis"]))


def attribution(records, bank, core):
    result = core.analyze_global_outputs(
        [{"text": row["text"], "expected_count": row["expected_count"]} for row in records], bank)
    ranked = result["results"]
    return {"prediction": result["prediction"], "used_outputs": result["used_outputs"],
            "score_margin": ranked[0]["score"] - ranked[1]["score"],
            "probability_margin": ranked[0]["probability"] - ranked[1]["probability"],
            "closed_set_probability": result["probability"], "calibration": result["calibration"],
            "ranking": [{"model": x["model"], "score": x["score"],
                         "closed_set_probability": x["probability"],
                         "pooled_profile_js_similarity": x["profile_similarity"]} for x in ranked]}


def summary(rows, model_ids):
    usable = [x for x in rows if x.get("accepted", True)]
    evaluable = [x for x in usable if x["label"] in model_ids]
    return {"records": len(rows), "usable": len(usable),
            "prediction_counts": dict(sorted(Counter(x["prediction"] for x in usable).items())),
            "mean_score_margin": statistics.mean(x["score_margin"] for x in usable) if usable else None,
            "in_bank_labeled_records": len(evaluable),
            "top1_correct": sum(x["prediction"] == x["label"] for x in evaluable) if evaluable else None,
            "out_of_bank_labels": sorted({x["label"] for x in usable if x["label"] not in model_ids})}


def stratify(rows, fields, model_ids):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(field, "unspecified") for field in fields)].append(row)
    return [{"stratum": dict(zip(fields, key)), **summary(values, model_ids)}
            for key, values in sorted(groups.items(), key=lambda item: str(item[0]))]


def feature_differences(samples, bank, core):
    accepted = [row for row in samples if row["accepted"]]
    embeddings = {row["id"]: projected_feature(row["numbers"], bank, core) for row in accepted}
    groups = defaultdict(list)
    for row in accepted:
        groups[(row["label"], row["effort"])].append(row)
    centers = {key: unit([statistics.mean(embeddings[row["id"]][i] for row in rows)
                          for i in range(core.DIMENSION)]) for key, rows in groups.items()}
    within = []
    for key, rows in sorted(groups.items()):
        distances = [1 - cosine(embeddings[a["id"]], embeddings[b["id"]])
                     for a, b in itertools.combinations(rows, 2)]
        within.append({"label": key[0], "effort": key[1], "samples": len(rows), "pairs": len(distances),
                       "mean_pairwise_cosine_distance": statistics.mean(distances) if distances else None})
    between = []
    for a, b in itertools.combinations(sorted(groups), 2):
        distances = [1 - cosine(embeddings[left["id"]], embeddings[right["id"]])
                     for left in groups[a] for right in groups[b]]
        between.append({"left": {"label": a[0], "effort": a[1]},
                        "right": {"label": b[0], "effort": b[1]}, "pairs": len(distances),
                        "mean_pairwise_cosine_distance": statistics.mean(distances),
                        "sample_center_cosine": cosine(centers[a], centers[b])})
    model_ids = [m["id"] for m in bank["models"]]
    centroid_rows = bank["robust"]["hellinger"]["centroids"]
    model_pairs = [{"left": model_ids[a], "right": model_ids[b],
                    "cosine": cosine(centroid_rows[a], centroid_rows[b])}
                   for a, b in itertools.combinations(range(len(model_ids)), 2)]
    return {"feature": "355-dimensional standardized nuisance-projected Hellinger; unit vectors",
            "within_label_effort": within, "between_label_effort": between,
            "bank_model_center_cosines": sorted(model_pairs, key=lambda x: x["cosine"], reverse=True),
            "sample_center_model_cosines": [
                {"label": key[0], "effort": key[1], "samples": len(groups[key]),
                 "ranking": sorted([{"model": model, "cosine": cosine(center, centroid)}
                                    for model, centroid in zip(model_ids, centroid_rows)],
                                   key=lambda x: x["cosine"], reverse=True)}
                for key, center in sorted(centers.items())]}


def analyze(paths, bank_path):
    core = load_core()
    bank = core.load_bank(bank_path)
    model_ids = core.bank_model_ids(bank)
    records = []
    for path in paths:
        records.extend(normalize(row, i, Path(path).name) for i, row in enumerate(read_records(path)))
    if not records:
        raise ValueError("no input records")
    if len({row["id"] for row in records}) != len(records):
        raise ValueError("sample ids must be unique across inputs")
    singles = []
    for row in records:
        numbers = core.parse_numbers(row["text"])
        row["numbers"] = numbers
        minimum = core.minimum_numbers(row["expected_count"])
        row["accepted"] = len(numbers) >= minimum
        response_digest = hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
        if row["response_sha256"] and row["response_sha256"] != response_digest:
            raise ValueError(f"response SHA256 mismatch: {row['id']}")
        public = {k: v for k, v in row.items() if k not in ("text", "numbers", "group_key", "response_sha256")}
        public.update(parsed_count=len(numbers), minimum_numbers=minimum,
                      exact_requested_count=len(numbers) == row["expected_count"] if row["expected_count"] else None,
                      text_sha256=response_digest, label_present_in_bank=row["label"] in model_ids)
        if row["accepted"]:
            public.update(attribution([row], bank, core))
        singles.append(public)
    grouped = defaultdict(list)
    for row in records:
        grouped[(row["label"], row["effort"], row["split"], row["input"], row["group_key"])].append(row)
    triples, remainder = [], []
    for key, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        rows.sort(key=lambda row: row["turn_index"])
        for start in range(0, len(rows), 3):
            chunk = rows[start:start + 3]
            if len(chunk) != 3:
                remainder.extend(row["id"] for row in chunk)
                continue
            group = {"sample_ids": [row["id"] for row in chunk], "label": key[0],
                     "effort": key[1], "split": key[2], "group_key": key[4],
                     "language": chunk[0]["language"] if len({x["language"] for x in chunk}) == 1 else "mixed",
                     "format": chunk[0]["format"] if len({x["format"] for x in chunk}) == 1 else "mixed",
                     "label_present_in_bank": key[0] in model_ids,
                     "accepted": all(row["accepted"] for row in chunk)}
            # A three-answer result must contain three usable answers; partial
            # groups are not silently calibrated/reported as three answers.
            if group["accepted"]:
                group.update(attribution(chunk, bank, core))
            triples.append(group)
    contexts = [row["context_id_sha256"] for row in records if row["context_id_sha256"]]
    fields = ("label", "effort", "split", "language", "format")
    return {"schema": "exploratory-fingerprint-report-v1",
            "bank": {"path": str(Path(bank_path)), "sha256": digest(bank_path),
                     "model_count": len(model_ids), "model_ids": model_ids},
            "scorer": {"path": str(CORE_PATH.relative_to(ROOT)), "sha256": digest(CORE_PATH)},
            "inputs": [{"path": str(Path(path)), "sha256": digest(path)} for path in paths],
            "scope": "Explicit offline input analysis; no model invocation, bank fitting, or production-bank writes.",
            "limits": ["Model labels are requested/declared provenance, not independent proof of serving weights.",
                       "Scores and probabilities are closed-set comparisons among bank labels; out-of-bank labels cannot be recognized.",
                       "Small samples and within-thread repeated turns are exploratory; differences do not establish independent fingerprint classes.",
                       "Language/format strata describe requested prompts; public environment mapping follows the pinned challenge suite.",
                       "Distances use Hellinger features only, while attribution also fuses ordered blocks; these are different diagnostics."],
            "grouping": {"rule": "Nonoverlapping chunks of 3, sorted by turn_index, within label/effort/split/input and condition_id or thread_alias; otherwise input order.",
                         "incomplete_group_sample_ids": remainder},
            "integrity": {"response_hashes_checked": sum(bool(row["response_sha256"]) for row in records),
                          "declared_context_ids": len(contexts), "unique_declared_context_ids": len(set(contexts))},
            "single_summary": summary(singles, model_ids), "three_answer_summary": summary(triples, model_ids),
            "single_strata": stratify(singles, fields, model_ids),
            "three_answer_strata": stratify(triples, fields, model_ids),
            "singles": singles, "three_answer_groups": triples,
            "feature_differences": feature_differences(records, bank, core)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True,
                        help="explicit JSON/JSONL sample file; repeat for multiple datasets")
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK,
                        help="read-only fingerprint bank (default: current production bank)")
    parser.add_argument("--output", type=Path, help="write report JSON here; default: stdout")
    args = parser.parse_args()
    if args.output and args.output.resolve() in {args.bank.resolve(), CORE_PATH.resolve(), *(x.resolve() for x in args.input)}:
        parser.error("output must not overwrite the bank, scorer, or inputs")
    try:
        report = analyze(args.input, args.bank)
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.error(str(error))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
        print(json.dumps({"report": str(args.output), "bank_model_count": report["bank"]["model_count"],
                          "single_summary": report["single_summary"],
                          "three_answer_summary": report["three_answer_summary"]}, ensure_ascii=False))
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
