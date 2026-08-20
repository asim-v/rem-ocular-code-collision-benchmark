# Background Collision Rates of Ocular Codes in REM EOG

Open and reproducible measurement of accidental ocular-code matches in
continuous electrooculography from spontaneous REM sleep.

## Primary question

At equal recovery of prespecified synthetic engineering signals, how often do
different prearranged ocular patterns collide with spontaneous REM eye
activity?

The first-stage Donders data audit is complete. The release contains readable raw PSG
but no event annotations, event sidecars, or epoch-level sleep scoring. It
therefore cannot independently reconstruct or validate the published
question-response trials. See [the audit findings](docs/data-audit-findings.md).
The [prior-art boundary](docs/prior-art-boundary.md) records why automatic LRLR
detection by itself would not be a novel claim.

The active pilot is now a separate negative-corpus benchmark using Sleep-EDF
Expanded. Its protocol, codebook, participant split and file checksums were
committed before any development waveform was analyzed. See the
[prespecified pilot protocol](docs/ocular-code-pilot-protocol.md).

The development analysis and one-shot sealed pilot test are complete. The
rhythmic `sync8_c0` marker directionally replicated its lower collision rate,
while the paired `sync8_c1` symbol did not. See the
[sealed pilot results](docs/test-pilot-results.md) and the explicitly
exploratory [development results](docs/development-pilot-results.md).

The confirmatory Sleep-EDF sleep-cassette analysis is complete. At matched 90%
synthetic engineering recovery, `sync8_c0` produced 1.823 background events per
eligible REM hour and the isochronous control produced 1.694. The clustered
interval did not support lower collision for the synchronized code, and its
practical advancement gate failed. See the
[confirmatory results](docs/confirmatory-results.md), the
[prespecified protocol](docs/confirmatory-study-protocol.md), and the
[amendment log](docs/amendments.md).

The untouched sleep-telemetry and CAP corpora remain unopened. Because the
primary test failed, they will not be interpreted as secondary confirmation
under the original sequence. A crossing of the descriptive FROC curves at 95%
recovery motivates a new external protocol that must be frozen before those
signals are accessed.

## Analysis sequence

1. Preserve a reproducible audit of the Donders release.
2. Do not infer response labels from the same waveforms used for evaluation.
3. Run a continuous-time benchmark using independently staged public REM as
   negative exposure.
4. Compare prespecified ocular codebooks by false detections per REM hour and by
   robustness to prespecified synthetic perturbations.
5. Reserve claims about human sensitivity and communication capacity for a
   future independently labeled dataset.

## Data sources

The source archive is the CC BY 4.0
[Dream Database from Donders](https://doi.org/10.6084/m9.figshare.21388722.v2).
It is not tracked by Git. See [data/README.md](data/README.md) for provenance
and retrieval instructions.

The collision pilot uses the ODC-By 1.0
[Sleep-EDF Expanded](https://physionet.org/content/sleep-edfx/1.0.0/) release.
The frozen manifest selects one night from 12 distinct participants, with six
for development and six reserved for a sealed pilot test.

The confirmatory manifests add every available night from the 66 remaining
sleep-cassette participants, both nights from 22 sleep-telemetry participants
with placebo and temazepam identified in advance, and CAP normal controls
`n1` through `n15`. CAP `n16` was excluded from EDF header metadata because it
contains no EOG channel. All source files remain untracked.

## Reproduce the audit

The complete run downloads a 2.17 GB archive and extracts approximately 4.16
GB of source files. From PowerShell:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./scripts/run_audit.ps1 -Python ./.venv/Scripts/python.exe
```

Expected summary: seven readable EDF files, zero EDF read errors, and zero
embedded annotations. The scripts verify the published archive MD5 before
analysis.

## Reproduce the ocular-code pilot

Install the pinned environment and verify the data-independent code design:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe scripts/design_codebook.py
./.venv/Scripts/python.exe -m pytest -q
```

Run development without downloading the reserved files:

```powershell
./.venv/Scripts/python.exe scripts/fetch_sleep_edf.py --split development
./.venv/Scripts/python.exe scripts/run_ocular_code_benchmark.py --split development
```

Commit the unchanged implementation together with
`outputs/ocular-code-pilot/development/thresholds.json`. Only then fetch and
run the sealed pilot test:

```powershell
./.venv/Scripts/python.exe scripts/fetch_sleep_edf.py --split test
./.venv/Scripts/python.exe scripts/run_ocular_code_benchmark.py --split test
```

The test command refuses to run if the worktree is dirty, thresholds are not
tracked, or any configuration or implementation hash differs from the
development run.

## Reproduce the confirmatory preparation

Rebuild both manifests from checksum-verified official metadata and compare
them with the frozen copies:

```powershell
./.venv/Scripts/python.exe scripts/build_confirmatory_manifests.py --check
./.venv/Scripts/python.exe -m pytest -q
```

The manifest builder reads inventories, checksum lists and subject tables. It
does not download or open physiological recordings.

After the protocol and implementation are committed, retrieve and run only
the primary cohort:

```powershell
./.venv/Scripts/python.exe scripts/fetch_confirmatory_data.py --cohort sc
./.venv/Scripts/python.exe scripts/run_confirmatory_benchmark.py --cohort sc
./.venv/Scripts/python.exe scripts/analyze_confirmatory_froc.py
```

The same frozen SC files can be fetched faster from PhysioNet's official
public S3 mirror without changing the manifest or its SHA256 checks:

```powershell
./.venv/Scripts/python.exe scripts/fetch_confirmatory_data.py --cohort sc `
  --base-url https://physionet-open.s3.amazonaws.com/sleep-edfx/1.0.0/sleep-cassette
```

This transport-only addition is recorded in
[`docs/amendments.md`](docs/amendments.md).

The long runner keeps per-record checkpoints tied to the frozen revision and
can safely resume with `--resume`. It stores every background candidate from
the minimum score floor, allowing the full matched-recovery FROC analysis
without rescanning the signals.

Sleep-telemetry remains inaccessible to the runner until the sleep-cassette
threshold file has been committed. CAP remains inaccessible until its separate
analysis gate has been committed. These gates prevent accidental peeking across
the ordered validation stages.

## Scientific boundary

The existing recordings concern communication through ordinary sensory input
and physiological output. They cannot test telepathy or information transfer
without a physical channel.
