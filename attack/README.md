# Lightweight adversarial robustness prototype

## Module goal

This module tests whether a fixed prototype scatter-gather detector remains
stable when a synthetic transaction pattern changes in topology, timing, or
amount distribution. It is a small, seconds-level robustness experiment, not a
production AML system and not a model-training pipeline.

Important scope statements:

- **Thresholds are prototype heuristics.** They are not IBM, regulatory, or
  production AML thresholds.
- **Synthetic detection evasion does not mean successful money laundering.**
- **The AMLSim Java simulator is not used in this prototype.** The synthetic
  baseline borrows only the scatter-gather typology idea.
- Outputs describe suspicious candidates, suspicious patterns, and synthetic
  detection evasion only.

## Dependencies

The prototype uses only three third-party Python packages:

- pandas
- NumPy
- NetworkX

Install them into the lightweight attack environment:

```powershell
cd D:\河套实训\Anti-Money-Laundering
.\.venv\Scripts\Activate.ps1
python -m pip install -r attack\requirements.txt
```

## Run

The team repository already has a GNN entry point at the project root. Run this
prototype from `attack/` so that file remains untouched:

```powershell
cd D:\河套实训\Anti-Money-Laundering
.\.venv\Scripts\Activate.ps1
cd attack
python main.py
```

The complete flow is:

```text
baseline transactions
→ NetworkX MultiDiGraph
→ 2-hop scatter-gather candidate retrieval
→ feature extraction
→ prototype baseline detector
→ controlled mutation
→ rebuild graph
→ re-retrieve and re-detect
→ attack summary
```

## Input

The default input is the explicitly synthetic fixture:

```text
data/mock/base_scatter_gather.csv
```

Required columns:

```text
transaction_id
timestamp
source
target
amount
pattern_id
pattern_type
synthetic_label
```

The mock topology is a 2-hop scatter-gather pattern:

```text
A → B, C, D → X
```

If the fixture is absent, `synthetic_generator.py` recreates it. No AMLSim Java
process or AMLSim Python import is required.

## Output

Each attack writes an independent directory:

```text
outputs/attacks/<attack_id>/
├── base_transactions.csv
├── mutated_transactions.csv
├── attack_summary.json
└── candidate_subgraph.json
```

The JSON summary includes retrieval status, before/after features, stable and
changed features, old-rule results, failed rule conditions, failure stage, and
attack success. It also includes `failure_type` and an evidence-based
`evolution_hint` with `preserve`, `relax_or_reformulate`, and
`recommended_direction`. Downstream modules do not need to read the in-memory
NetworkX graph.

`candidate_subgraph.json` is the cross-module
`ccem.candidate_subgraph/v0.2` interface. It is also emitted for retrieval
failures, using the deterministic mutation scope and explicitly recording
`candidate_source=mutation_scope`; this does not claim that retrieval succeeded.
The summary and Candidate are built from the same mutation record and a mismatch
in their shared fields or edge lineage is a hard failure.

The lightweight parameter sweep writes one aggregate artifact:

```text
outputs/attacks/robustness_profile.json
```

It records actual retrieval, detection, failure type, attack success, and the
observed time span, path depth, or flow-through ratio at each configured sweep
point.

The run also writes `outputs/attacks/artifact_manifest.json` with logical
artifact IDs, paths relative to the manifest, and real SHA-256 values. Candidate
timestamps are relative seconds using `ROUND_HALF_UP`; CSV timestamps remain
timezone-aware ISO values for human inspection.

## Attack definitions

### `temporal_stretch`

Delays downstream transactions while preserving sources, targets, amounts, and
graph topology. It is intended to change `time_span_hours` and
`median_delay_hours`.

### `path_extension`

Replaces each `intermediate → destination` edge with
`intermediate → synthetic relay → destination`. It preserves the direction of
fund flow but changes the path from two hops to three.

### `amount_perturbation`

Applies seeded, controlled noise to synthetic candidate transaction amounts.
Topology and direction remain unchanged, and every resulting amount stays
positive. The mutation can change the flow-through proxy without guaranteeing
detection evasion.

## Failure stages

The prototype always rebuilds the graph and reruns retrieval after mutation. It
therefore distinguishes two failure modes:

- `retrieval`: the mutated pattern is no longer returned by the 2-hop candidate
  retriever, so the old detector cannot evaluate that candidate.
- `detection`: the mutated pattern is still retrieved, but one or more old
  prototype rule conditions fail and it is no longer marked as a suspicious
  candidate.

`failure_stage` is `null` when retrieval and detection both still succeed, or
when the baseline precondition for a successful attack is not met.

## Current verified result

The following result was produced by running `python main.py` with
`configs/attack_config.json`:

```text
Attack               Retrieved Before  Retrieved After  Detected Before  Detected After  Failure Stage  Success
-------------------  ----------------  ---------------  ---------------  --------------  -------------  -------
temporal_stretch     True              True             True             False           detection      True
path_extension       True              False            True             False           retrieval      True
amount_perturbation  True              True             True             True            None           False
```

- `temporal_stretch` produces synthetic detection evasion at the detection
  stage because the mutated time span exceeds the configured prototype
  heuristic.
- `path_extension` produces synthetic detection evasion at the retrieval stage
  because the current retriever intentionally supports only 2-hop
  scatter-gather candidates.
- `amount_perturbation` remains retrieved and detected, so this controlled
  mutation is not a successful attack against the prototype detector.

The code intentionally does not force all mutations to evade the prototype.
