# Data provenance

## Source

- Title: Dream Database from Donders
- Figshare article: `21388722`, version 2
- DOI: <https://doi.org/10.6084/m9.figshare.21388722.v2>
- File ID: `41037542`
- Published archive name: `Dream Database from Donders.rar`
- Expected size: `2,173,512,831` bytes
- Expected MD5: `7ae6b141f7ecbf29a8b51f75bcdb9b65`
- License: CC BY 4.0

The Figshare description reports seven samples from six participants across
three projects. Study code 0 is the real-time lucid-dream dialogue experiment.
The archive also contains motor-decoding and other dream EEG recordings, so
file inclusion must be determined from the released metadata rather than from
the paper-level sample size.

## Retrieval

From PowerShell at the repository root:

```powershell
./scripts/fetch_figshare.ps1
```

The script downloads into `data/raw/`, supports resuming an interrupted
transfer, and rejects a file whose size or MD5 does not match Figshare.

## Sleep-EDF Expanded ocular-code pilot

- Source: Sleep-EDF Database Expanded, version 1.0.0
- PhysioNet record: <https://physionet.org/content/sleep-edfx/1.0.0/>
- Release directory: `sleep-cassette/`
- License: Open Data Commons Attribution License v1.0
- Local destination: `data/sleep-edf/sleep-cassette/`

The frozen manifest at `config/sleep_edf_pilot_manifest.csv` records the exact
PSG and hypnogram filenames and their official SHA256 digests. It selects the
first sleep-cassette night from 12 distinct participants. Subjects 00 through
05 are development data. Subjects 06 through 11 are the sealed pilot test set.

Fetch only the development split while building and calibrating the pipeline:

```powershell
python scripts/fetch_sleep_edf.py --split development
```

The downloader resumes `.part` files, verifies every SHA256 digest, and only
then moves a file to its final name. The test split must not be downloaded or
read until the implementation and development thresholds have been committed.
After that freeze, it can be fetched explicitly with:

```powershell
python scripts/fetch_sleep_edf.py --split test
```

## Confirmatory collision benchmark

The confirmatory source recordings are never tracked. Two generated manifests
record every selected file, official SHA-256 digest, cohort role and EOG
derivation:

- `config/sleep_edf_confirmatory_manifest.csv`;
- `config/cap_normal_manifest.csv`.

Their construction is reproducible from checksum-verified official metadata:

```powershell
python scripts/build_confirmatory_manifests.py --check
```

Downloads require an explicit cohort and are stored below
`data/confirmatory/`:

```powershell
python scripts/fetch_confirmatory_data.py --cohort sc
python scripts/fetch_confirmatory_data.py --cohort st-placebo
python scripts/fetch_confirmatory_data.py --cohort cap-normal
```

Only `sc` may be opened for the primary run. The other runner stages refuse to
open until their required tracked gate files exist. Retrieval alone does not
constitute an analysis, but the ordered gates should still be followed to keep
the scientific record simple.

The independent CAP source is the ODC-By 1.0
[CAP Sleep Database](https://physionet.org/content/capslpdb/1.0.0/), version
1.0.0, DOI <https://doi.org/10.13026/C2VC79>.
