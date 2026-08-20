# External 95% FROC replication results

## Integrity and cohort

The new external protocol was committed before any Sleep-EDF sleep-telemetry
signal was downloaded or opened. The analysis used the 22 frozen placebo
nights, one per participant. Temazepam and CAP remained sealed.

All 44 source files matched their frozen SHA256 digests. The cohort contributed
34.237 eligible expert-scored REM hours and 440 paired synthetic injections per
code. Candidate extraction ran from commit `0c252f9`. The final inference ran
from commit `148c6ed` after a platform-only provenance hash correction. The
numerical outputs before and after that correction were identical.

## Primary external result

The sleep-telemetry thresholds were selected independently for each code to
recover exactly 418 of 440 injections, or 95%.

| Quantity | `sync8_c0` | `iso8_matched` |
|---|---:|---:|
| Matched threshold | 0.532931 | 0.490856 |
| Synthetic recovery | 418/440, 95.0% | 418/440, 95.0% |
| Background events | 308 | 321 |
| Events per eligible REM hour | 8.996 | 9.376 |

The synchronized minus isochronous rate difference was -0.380 events per REM
hour. Its 50,000-replicate participant-clustered 95% interval was -10.523 to
12.394. The rate ratio was 0.960.

The interval did not establish lower collision and the rate ratio was not at
most 0.70. Both external replication rules failed. This is not evidence of
equivalence, but it does reject advancement of the proposed high-recovery
effect under the frozen decision rule.

## Why fixed thresholds look different

Applying the descriptive SC 95% thresholds directly to sleep-telemetry gave:

| Quantity | `sync8_c0` | `iso8_matched` |
|---|---:|---:|
| SC threshold | 0.543444 | 0.452067 |
| ST synthetic recovery | 415/440, 94.32% | 421/440, 95.68% |
| ST events per REM hour | 7.214 | 16.795 |

That fixed-threshold comparison appears to favor the synchronized code, but
the codes no longer have equal recovery. Once both are rematched within the
external corpus at exactly 95%, the large rate difference nearly disappears.

This is the main methodological result of the external study: absolute
threshold transport can create an impressive apparent specificity advantage
when detector-score distributions shift between cohorts. A fair code
comparison requires either equal transported sensitivity or explicit
within-corpus matched recovery.

## Reproducibility and decision

Machine-readable combined ST inputs are under
`outputs/ocular-code-external95/st-placebo/`. The matched thresholds, primary
contrast, fixed-threshold transport table and final decision are under
`outputs/ocular-code-external95/st-analysis/`.

The external analysis was rerun from the same saved tables after normalizing
the provenance check to canonical Git bytes. All four numerical CSV files were
byte-for-byte identical, and the primary estimate and decision in the JSON
summary were identical.

The prespecified CAP advancement rule failed. CAP normal controls will not be
downloaded under this sequence. Temazepam nights also remain unopened.

The SC 90% primary result and the ST 95% external result jointly show no robust
advantage for `sync8_c0` at equal engineering recovery. The work remains an
open benchmark of physiological background collisions. It estimates neither
human production sensitivity nor dream communication and provides no evidence
for psi or anomalous information transfer.
