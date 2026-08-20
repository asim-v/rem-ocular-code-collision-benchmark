# Donders release audit

Audit date: 2026-08-19

## Result

The released files cannot support a valid retrospective evaluation of an
automatic dream-communication decoder. The raw physiological recordings are
readable, but the independent event anchors needed to determine when questions
and intentional responses occurred are not present.

Model fitting was therefore stopped before inspecting candidate ocular motifs.
Creating labels from the same EOG morphology that a detector would later be
asked to recover would make the evaluation circular.

## Verified archive

- Figshare article: `21388722`, version 2
- File ID: `41037542`
- Downloaded bytes: `2,173,512,831`
- Verified MD5: `7ae6b141f7ecbf29a8b51f75bcdb9b65`
- Extracted files: 20
- Extracted bytes: `4,160,286,422`
- EDF recordings: 7, all readable with MNE
- DOCX reports: 10
- Embedded EDF annotations: 0
- Event or marker sidecars: 0

The machine-readable inventories are in `outputs/data-audit/`.

## Communication subset

`ExperimentalDescription.txt` explicitly assigns these files to the real-time
dialogue project:

- `Data/PSG/s_04/c_04/morningnap_singlepart.edf`
- `Data/PSG/s_04/c_05/morningnap_singlepart.edf`

Both belong to the same released subject identifier, `s_04`. Each contains
128 channels sampled at 500 Hz, including named horizontal and vertical EOG,
EMG, and ECG channels. Their durations are approximately 8,030 and 8,204
seconds.

No released file identifies:

- question onset or offset;
- the arithmetic problem presented on each trial;
- response-window boundaries;
- lucidity-signal timing;
- original correct, incorrect, ambiguous, or absent labels;
- epoch-level sleep stages or arousal boundaries.

Consequently, the eight Dutch trials reported in the source article cannot be
reconstructed from this release alone.

## Internal provenance issues

### Subject count

The release metadata states that there are six subjects. `Records.csv`
contains five unique identifiers: `s_00` through `s_04`. The seventh EDF is a
second file segment, and `s_04` also has two recording cases.

### Study codes

The documentation states that treatment-group codes correspond to the numbered
studies, but every `Records.csv` assignment uses a different permutation:

| Explicit study in description | Files | `Records.csv` code |
|---|---:|---:|
| 0, real-time dialogue | 2 | 2 |
| 1, motor decoding | 4 | 0 |
| 2, other dream data | 1 | 1 |

This may be an undocumented recoding rather than random corruption. File
selection must use the explicit paths in `ExperimentalDescription.txt`, not the
numeric treatment-group field.

### Duplicate reports

The three reports placed under `s_04/c_04` are byte-for-byte identical to the
three reports under `s_04/c_05`. The two EDF recordings themselves are not
duplicates. Therefore, the released reports do not provide independent
session-level provenance for the two recordings.

Exact report hashes and path pairs are recorded in
`outputs/data-audit/release_metadata_audit.json`.

## Go/no-go decision

**No-go:** supervised decoder training, trial-level correctness analysis,
communication-capacity estimation, or claims about generalization from this
release.

**Still possible:** a data-curation note, exploratory visualization clearly
marked as unlabeled, or a prospective engineering study. The strongest
permission-free follow-up is a continuous-time benchmark that searches for
false collisions of candidate ocular codes in independently staged REM from
public sleepers who were never instructed to communicate. Synthetic code
injection can evaluate engineering robustness, but it must not be presented as
human sensitivity.

## Prior-art boundary

Automatic LRLR detection itself is not new. Template matching for successive
LRLR saccades was reported by LaBerge, Baird, and Zimbardo in 2018
(<https://doi.org/10.1038/s41467-018-05547-0>). The potentially new contribution
would be open continuous-time specificity, codebook optimization, and false
alarms per REM hour across a large public negative corpus.
