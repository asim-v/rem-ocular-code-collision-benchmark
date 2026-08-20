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
