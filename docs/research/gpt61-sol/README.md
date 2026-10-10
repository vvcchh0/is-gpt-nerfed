# GPT-6.1 Sol exploratory fingerprint review

This research does **not** establish an independent GPT-6.1 Sol fingerprint. The fixed public experiment reproduces substantial overlap with GPT-6 Astra; adding its candidate class also reduces Astra's cross-validation results. Neither requested model labels nor fingerprint attribution prove the actual serving weights. No production bank is trained, replaced, or extended by this work.

## Sources and attribution

- Public contribution: [xqy2006/ModelTrace PR 28](https://github.com/xqy2006/ModelTrace/pull/28), from [7and1/ModelTrace at `1369ca7afca83db354eac5752d1e23f51bafd1b5`](https://github.com/7and1/ModelTrace/tree/1369ca7afca83db354eac5752d1e23f51bafd1b5/data/research/gpt-6.1-sol-2026-10-02). The contributor is 7and1; the retained upstream MIT license attributes Copyright (c) 2026 xqy2006.
- The author reports collection through official Codex CLI 0.159.1, requested `gpt-6.1-sol`, effort `low`, one ephemeral process per prompt. Those are external author declarations, **not samples collected on this machine**. The original rows explicitly set `response_model: null` and `identity_independently_attested: false`; host/Codex instructions remained, and challenge system text used developer instructions.
- All 15 downloaded files are retained byte-for-byte under [upstream/](upstream/). [provenance.json](provenance.json) records each fixed raw URL, source commit, size, and SHA-256. [upstream/LICENSE](upstream/LICENSE) preserves the full MIT notice. The large baseline reference files are needed by the original integrity-checked CV reproducer.
- The source baseline is ModelTrace `d4131b30243dfa05e70180b5eedde742103f1d73`: 17 classes / 612 reference replies. This project's current production bank has 16 classes; it omits `claude-sonnet-5-5`. Both banks exclude `gpt-6.1-sol`.

Key original hashes:

| File | SHA-256 |
| --- | --- |
| enrollment.jsonl | `cb30f94f7e075b636c1cf1092b2238e4282c7aa8493f2f84fd144a52bbf23f1c` |
| holdout.jsonl | `faaa5e11c58051fd4a6558117e6c8904922a4dace99fb9d9eca21d386905aa31` |
| 17-class baseline bank | `e514c76928ea38d23bc0f14d3935f23c97b1efb6d96b18a19bdc88ad2d830536` |

## Original offline reproduction

The downloaded `validate.py` and its imported `bank_builder.py`, `fingerprint.py`, and `challenge_suite.py` were inspected before execution. The validator checks fixed baseline/source hashes, response hashes, prompt coverage, holdout isolation, and the failed/retry relationship, then builds the candidate **in memory**. It does not invoke models or access the network. The bank builder's file-writing CLI is guarded by `__main__` and is not invoked.

The default Python 3.11.2 had no NumPy. Codex's existing bundled Python 3.12.14 had NumPy, so no dependency was installed. Running the original validator under that runtime returned exit code 0 in 151.234 seconds, `integrity: PASS`, and `active_banks_unchanged: true`. [upstream-reproduction.json](upstream-reproduction.json) retains the actual command, stdout, stderr, elapsed time, and validator hash.

| Original candidate experiment | Reproduced result |
| --- | --- |
| Sol single-reply CV | 20/36 |
| Sol two-reply CV | 24/36 |
| Sol three-reply CV | 6/12 |
| Sol independent holdout, singles | 5/9 |
| Sol independent holdout, three-reply groups | 1/3 |
| Astra three-reply CV, before → after candidate addition | 12/12 → 9/12 |

These are the upstream candidate's results, not results from activating Sol in this project. To repeat them in an existing Python/NumPy environment, run from the project root:

```powershell
python -B docs/research/gpt61-sol/upstream/data/research/gpt-6.1-sol-2026-10-02/validate.py
```

## Existing-bank analysis of public samples

[tools/analyze_fingerprint_samples.py](../../../tools/analyze_fingerprint_samples.py) uses this project's existing pure Python scorer and needs only the standard library. It accepts public JSONL and explicit local JSON `records` containing `label`, `effort`, `language`, `output`, `expected_count`, `turn_index`, and `thread_alias`.

Reports include input/bank/scorer hashes, strict count gates, response hash verification, every class score and top-two margin, pooled-profile JS similarity, and single/three-answer results stratified by label, effort, split, language, and requested format. Three-answer groups use nonoverlapping chunks within a public condition or local thread; incomplete groups are disclosed, and a group with an unusable answer is not reported as a usable three-answer result. Closed-set probabilities are identified as such; an out-of-bank label receives no correctness/accuracy claim.

All 45 selected public replies passed the strict gate, all 45 supplied text hashes matched, and all 45 declared context hashes were unique. The author retained a separate first failed response and its replacement; the original validator checked that relationship. Both existing banks give the same top-1 counts: 41 Astra, 3 GPT-5.6 Sol, 1 GPT-6 Luna; all 15 three-answer condition groups give Astra. The 17-class baseline stratification is:

| Split / requested language / format | Singles | Top-1 counts |
| --- | ---: | --- |
| Enrollment / English / JSON | 12 | Astra 10, GPT-5.6 Sol 1, GPT-6 Luna 1 |
| Enrollment / English / prose | 3 | Astra 3 |
| Enrollment / Chinese / prose | 21 | Astra 20, GPT-5.6 Sol 1 |
| Holdout / English / JSON | 3 | Astra 2, GPT-5.6 Sol 1 |
| Holdout / English / prose | 3 | Astra 3 |
| Holdout / Chinese / prose | 3 | Astra 3 |

Results: [public-baseline17-report.json](public-baseline17-report.json), [public-production16-report.json](public-production16-report.json). Reproduce without NumPy:

```powershell
python -B tools/analyze_fingerprint_samples.py --input docs/research/gpt61-sol/upstream/data/research/gpt-6.1-sol-2026-10-02/enrollment.jsonl --input docs/research/gpt61-sol/upstream/data/research/gpt-6.1-sol-2026-10-02/holdout.jsonl --bank docs/research/gpt61-sol/upstream/data/unified_bank.json --output docs/research/gpt61-sol/public-baseline17-report.json
python -B tools/analyze_fingerprint_samples.py --input docs/research/gpt61-sol/upstream/data/research/gpt-6.1-sol-2026-10-02/enrollment.jsonl --input docs/research/gpt61-sol/upstream/data/research/gpt-6.1-sol-2026-10-02/holdout.jsonl --output docs/research/gpt61-sol/public-production16-report.json
```

## Separate local exploratory samples

The parent task supplied [six local samples](../2026-10-10-codex-probes/samples.json): three continuous turns in one user-authorized Sol chat and three in one Astra chat, all requested effort `high`, with Chinese 300 / English 300 / Chinese 320 number prompts. These are separate from the external `low` data. All six have the exact requested parsed counts. Both the 16-class production bank and the fixed 17-class baseline assign every single and each of the two three-answer groups to Astra.

| Local three-answer group | Production 16-class score margin | Baseline 17-class score margin |
| --- | ---: | ---: |
| Declared Sol / high | 0.859571 | 0.920750 |
| Declared Astra / high | 0.726489 | 0.810705 |

The descriptive feature diagnostics use standardized nuisance-projected 355-dimensional Hellinger unit vectors; the attribution scorer additionally fuses ordered-block features. Under the production bank, the within-label mean pairwise cosine distances are 0.771772 (Sol; 3 pairs) and 0.926387 (Astra; 3 pairs). Between the labels the mean is 0.860599 (9 dependent pairs), and the two sample-center cosine is 0.323529. Corresponding 17-class values are 0.779162, 0.934161, 0.867194, and 0.311920. The between-label distance lies between the two within-label values. With only three replies per label, shared thread history, mixed prompt languages, and no independent holdout, these values do not establish separability or a recognition accuracy. No candidate bank is fitted to these samples.

Results: [local-production16-report.json](local-production16-report.json), [local-baseline17-report.json](local-baseline17-report.json).

```powershell
python -B tools/analyze_fingerprint_samples.py --input docs/research/2026-10-10-codex-probes/samples.json --output docs/research/gpt61-sol/local-production16-report.json
python -B tools/analyze_fingerprint_samples.py --input docs/research/2026-10-10-codex-probes/samples.json --bank docs/research/gpt61-sol/upstream/data/unified_bank.json --output docs/research/gpt61-sol/local-baseline17-report.json
python -B -m unittest tests.test_fingerprint_research -v
```

The five research tests pass. They verify the existing scorer contract, hash rejection, thread grouping across languages, handling of incomplete/unusable three-answer groups, pair-count accounting, and unchanged bank contents. `--help` and all four report-generation commands also completed successfully. These checks support offline reproducibility and honest reporting; they do not validate a new production class.
