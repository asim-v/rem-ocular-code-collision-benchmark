# Metadata-only audit of confirmatory corpora

Audit date: 20 August 2026.

This audit used official release documentation, file inventories, checksums,
subject tables, sleep-stage text files and EDF header bytes. It did not inspect
signal samples from any new confirmatory recording.

## Sleep-EDF Expanded

Official source: <https://physionet.org/content/sleep-edfx/1.0.0/>

PhysioNet describes 197 whole-night PSG recordings with horizontal EOG and
manually scored hypnograms. The files are openly available under the Open Data
Commons Attribution License 1.0. The release provides a complete `RECORDS`
inventory, subject spreadsheets and official SHA-256 checksums.

The subject table and release inventory support the following untouched sets:

| Set | Participants | Recordings selected | Role |
|---|---:|---:|---|
| Sleep-cassette participants other than 00 to 11 | 66 | 129 nights | Primary confirmation |
| Sleep-telemetry | 22 | 22 placebo nights | Threshold transport |
| Sleep-telemetry | 22 | 22 temazepam nights | Exploratory drug condition |

Every night from a remaining sleep-cassette participant is retained to improve
REM exposure. Repeated nights are grouped by participant. Excluding
participants 00 to 11, rather than only their pilot nights, prevents reuse of a
person who influenced code selection.

The telemetry subject table identifies 12 placebo recordings as night 1 and
10 as night 2. This assignment is frozen from the official spreadsheet and is
not inferred from physiological data.

Primary release reference: <https://doi.org/10.13026/C2X676>.

## CAP Sleep Database

Official source: <https://physionet.org/content/capslpdb/1.0.0/>

The CAP Sleep Database contains 108 PSG recordings with expert sleep-stage
annotations. PhysioNet documents two EOG channels per recording in the
general collection and distributes the files under the Open Data Commons
Attribution License 1.0. The normal-control group is named `n1` through `n16`.

The release provides official SHA-256 checksums for EDF and annotation files.
The 15 selected EDF files total 3.525 GiB. Their published stage text contains
28.15 hours of nominal REM before boundary erosion and objective quality
exclusions.

An EDF-header audit found the following normal-control EOG layouts:

| Records | Frozen EOG construction | Source rate |
|---|---|---:|
| `n1` | native `ROC-LOC` | 512 Hz |
| `n2`, `n3`, `n5`, `n10`, `n11` | native `ROC-LOC` | 128 Hz |
| `n4` | `EOG dx` minus `EOG sin` | 100 Hz |
| `n6`, `n7`, `n9` | `ROC-A2` minus `LOC-A1` | 128 Hz |
| `n8` | `EOG-R` minus `EOG-L` | 100 Hz |
| `n12` | `ROC / A1` minus `LOC / A2` | 100 Hz |
| `n13`, `n14` | `ROC` minus `LOC` | 200 Hz |
| `n15` | `EOG-R` minus `EOG-L` | 200 Hz |

Polarity does not affect the detector because it uses absolute normalized
correlation. The declared subtraction order is nevertheless frozen for exact
reproduction.

Record `n16` contains only five EEG channels in its EDF header and has no EOG.
It is excluded before signal access. This leaves 15 independent normal
controls.

The RemLogic annotation files give 30-second stages as clock times. Alignment
uses the EDF start clock and explicitly handles midnight rollover. Only rows
whose event is `SLEEP-REM` define REM exposure. The loader must reject
nonmonotonic timing, impossible durations or annotations outside the recording
rather than guessing an offset.

Primary release reference: <https://doi.org/10.13026/C2VC79>.

## Dataset choice

CAP is preferred over ISRUC-Sleep for the first independent replication
because CAP currently provides direct open PhysioNet retrieval, stable file
names, official checksums, expert stage files and a clearly identified normal
group. ISRUC-Sleep remains a possible later robustness corpus, but its official
download is hosted through MEGA and the current public pages do not provide a
comparably simple frozen checksum manifest.

The montage heterogeneity in CAP is a useful transport test, but it also makes
CAP less suitable than Sleep-EDF for the primary confirmatory endpoint. The
primary inference therefore remains in the homogeneous untouched
sleep-cassette cohort. CAP is an external replication with its EOG derivation
declared per record.
