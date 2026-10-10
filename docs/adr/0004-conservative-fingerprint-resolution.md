# ADR 0004: expose Astra / Sol 6.1 fingerprint overlap and separate passive findings

Date: 2026-10-10
Status: Accepted; supplements ADR 0001's attribution boundary and ADR 0002's presentation contract.
Source: the user's observed Sol 6.1 → Astra attribution and
[upstream Issue #15](https://github.com/kiyoakii/is-gpt-nerfed/issues/15).

## Evidence and problem

The production bank has 16 classes and no `gpt-6.1-sol`. Its standardized similarity scores and
calibrated softmax rank a closed set; a high percentage cannot reject a model outside that set.
The ModelTrace author acknowledges the Astra / Sol overlap in
[Issue 26](https://github.com/xqy2006/ModelTrace/issues/26). The official Sol documentation describes
near-Astra performance; it does not validate this detector or establish identical weights.

The fixed public [PR 28](https://github.com/xqy2006/ModelTrace/pull/28) experiment was reproduced
offline: candidate Sol three-answer CV is 6/12 and independent holdout groups 1/3; adding the
candidate reduces Astra CV from 12/12 to 9/12. Our separate six high-effort replies from two
user-authorized chats all map to Astra. Three consecutive turns per chat are exploratory samples,
not an enrollment set or independent holdout. Both test chats were archived after collection.

Local history inspection also found passive hard findings overriding fingerprint attribution.
These findings describe recorded model/settings changes and may precede a later probe by hours.
Suppressing them as a side effect of fixing fingerprint overlap would discard a different source
of evidence. Conversely, presenting their combined verdict as confirmed fingerprint identity
misleads the user. See [the reliability report](../FINGERPRINT_RELIABILITY.zh-CN.md) and its linked
hash-checked research artifacts for methods, sources and limits.

## Decision

- Preserve exact model IDs, the production bank, scorer, prompts and default sampling settings.
  Do not alias Sol to Astra or create a synthetic Sol template from Astra's centroid.
- For declared `gpt-6-astra` or `gpt-6.1-sol` with raw top candidate `gpt-6-astra`, return neutral
  fingerprint verdict `AMBIGUOUS`, resolution `overlap`, and group `[gpt-6-astra, gpt-6.1-sol]`.
  The group records a known ambiguity, not a claim that all other possible models are excluded.
- If Sol's raw candidate differs, retain `UNLISTED`. Other unlisted and calibrated models retain
  their existing behavior. This targeted rule is not a general out-of-distribution detector.
- Compute fingerprint verdict independently. Existing hard passive findings retain overall
  `DOWNGRADED!` / `direction=hard` for backend compatibility, with `verdict_basis=passive` and
  `passive_reasons=[{kind, detail, ts}]`. The UI calls these concrete setting/model-change alerts.
- Expose `fingerprint_verdict`, `fingerprint_resolution`, `fingerprint_group`, `fingerprint_note`
  alongside existing raw prediction/probability. `AMBIGUOUS` alone must not alert, notify, sound,
  halt monitoring or announce an exact match.
- Project historical probe records at read time. Preserve raw ledger/probe bytes, passive
  evidence and any original verdict; do not require another billed probe to update interpretation.
- Show declared model, fingerprint resolution and passive findings separately in WPF, Tk and
  textual reports. Label raw percentages as closed-set scores, never serving-weight certainty.

## Alternatives and consequences

Adding PR 28's candidate now sacrifices Astra recognition and has poor Sol holdout performance.
Copying or perturbing Astra's centroid manufactures a distinction absent from the evidence.
Treating all Astra matches as confirmed exact identity keeps the known false assurance. We accept
less specificity for both declared Astra and Sol until independently validated data supports more.

This change fixes overclaiming and presentation, not the mathematical separability problem.
It does not certify actual serving weights, determine model quality or infer distillation lineage.
Existing passive scan rules and evidence lifetime remain unchanged and visible for separate review.

## Acceptance and follow-up

Implementation used GPT-6.1 Sol xhigh without redelegation; the parent integrates and verifies.

| Deliverable | Acceptance |
| --- | --- |
| Independent verdicts | overlap neutral; exact `6.1` retained; other unlisted/listed behavior covered; hard findings preserve standalone fingerprint and timestamps |
| History and actions | stored bytes unchanged; projected old Astra MATCH/Sol UNLISTED; ambiguity does not halt, alert or notify |
| UI and CLI | declared model, neutral overlap, labelled raw scores and concrete timed passive findings coexist; old fields remain readable |
| Research | pinned public inputs/license/hashes, reproduced CV, separate local samples, explicit small-sample/history limits, archived test chats |
| Release | complete isolated suite, compiled portable acceptance, clean-commit package hashes and cross-platform CI recorded in VALIDATION and release notes |

Before adding a production Sol class, collect sufficiently varied independent fresh contexts,
control harness/prompt/effort and account/time effects, predeclare held-out evaluation, and compare
Astra/Sol confusion plus out-of-set false acceptance. A rejection threshold or hierarchical group
classifier needs validation on unknown models as well as known labels; larger softmax margins alone
do not supply it. Prefer an upstream compatible bank/scorer when those checks are met.
