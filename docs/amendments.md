# Confirmatory study amendments

## 2026-08-20: optional official S3 transport

After the confirmatory study was frozen, the primary PhysioNet HTTPS file
endpoint was observed to transfer the large PSG files too slowly for a
practical full-cohort download. The downloader therefore gained an optional
`--base-url` argument so that the same files can be retrieved from PhysioNet's
official public S3 mirror.

This is a transport-only change. The original endpoint remains the default.
The frozen cohort, filenames, SHA256 digests, detector, outcomes, thresholds,
and statistical analysis are unchanged. Every completed file is still accepted
only when it matches the digest recorded before confirmatory data access. No
signal values were decoded or analyzed before this amendment was recorded.

## 2026-08-20: platform-independent frozen-file verification

The first invocation of the SC benchmark stopped before opening any EDF file.
Its preflight check compared raw working-tree bytes with canonical Git blob
bytes, so Git-managed CRLF line endings on Windows were incorrectly reported
as a modified confirmatory input even though the worktree was clean.

The preflight now uses Git's own clean-content comparison and records SHA256
digests of the canonical files stored in the frozen commit. A regression test
covers clean CRLF working copies and genuinely modified files. This change
affects only the preflight seal check. The cohort, data, detector, synthetic
injections, outcomes, thresholds, and statistical analysis are unchanged. No
signal values were decoded or analyzed before this amendment was recorded.

## 2026-08-20: complete background-score support

The first complete SC scan met the frozen precision targets: 129 nights from
66 participants, 177.13 eligible REM hours, and 2,563 primary synthetic
injections. The first inferential invocation then stopped without creating an
analysis output. At least one participant-bootstrap resample required a
matched-recovery threshold below the predeclared candidate-storage floor of
0.45. Background-event counts below that floor had not been retained, and the
analysis correctly refused to extrapolate them.

The storage floor is therefore lowered to 0.0 and the entire SC scan will be
rerun. Because the detector score is an absolute normalized correlation in
the closed interval from 0 to 1, a zero floor retains the complete score
support and prevents further left-censoring. The original floor-0.45 output is
retained locally as a censored audit artifact.

This is a post-data-access amendment and must be reported as such. It changes
only which already-defined background candidates are retained. It does not
change the cohort, code waveforms, preprocessing, amplitude gate, nonmaximum
suppression, synthetic injections, recovery targets, threshold-selection rule,
bootstrap seed or replicates, superiority rule, or practical gate. No
comparative rate estimate, confidence interval, or scientific conclusion was
produced before this amendment was recorded.
