# Ocular-code pilot: development results

## Status

These are exploratory development results, not the sealed pilot result. They
were used to set detector thresholds through the prespecified synthetic
engineering rule. No test PSG or hypnogram had been downloaded or read when
these outputs were produced.

The run started from clean commit
`d860dc83c2a2c27fe41637c8d7c3af91ad9c70e8`. All 12 source files passed their
frozen SHA-256 checks before analysis. The output contains six distinct
participants, 7.685 hours of eligible expert-scored REM, and 136.4 hours of
full-recording exposure.

## Frozen threshold rule

Each threshold is the largest value on the prespecified correlation grid that
recovers at least 90% of the primary synthetic condition. That condition uses
four trailing MAD in amplitude and 15% timing jitter. Background collision
counts did not enter threshold selection. Synthetic recovery is an engineering
check and is not human signal sensitivity.

All seven codes passed calibration.

| Code | Threshold | Synthetic recovery | REM events | REM rate/h (95% CI) | Full events | Full rate/h (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| `double_lrlr_pause` | 0.675 | 108/120 | 5 | 0.651 (0.211, 1.518) | 133 | 0.975 (0.816, 1.156) |
| `iso8_matched` | 0.675 | 108/120 | 5 | 0.651 (0.211, 1.518) | 115 | 0.843 (0.696, 1.012) |
| `legacy_lrl` | 0.800 | 108/120 | 143 | 18.608 (15.683, 21.920) | 3,700 | 27.126 (26.259, 28.015) |
| `legacy_lrlr` | 0.775 | 109/120 | 44 | 5.725 (4.160, 7.686) | 1,206 | 8.842 (8.350, 9.355) |
| `legacy_lrlrlr` | 0.725 | 109/120 | 4 | 0.520 (0.142, 1.333) | 282 | 2.067 (1.833, 2.323) |
| `sync8_c0` | 0.725 | 109/120 | 2 | 0.260 (0.032, 0.940) | 31 | 0.227 (0.154, 0.323) |
| `sync8_c1` | 0.675 | 109/120 | 5 | 0.651 (0.211, 1.518) | 145 | 1.063 (0.897, 1.251) |

The REM intervals are exact Poisson intervals. Full exposure is an ungated,
deliberately conservative analysis of the complete cassette and is not the
performance of an automatic REM-staging gate.

## Prespecified primary contrast

The primary candidate `sync8_c0` produced two REM collisions, compared with
five for the duration-matched isochronous control. The aggregate difference
was -0.390 events per REM hour. A 10,000-replicate participant-clustered
bootstrap interval was -0.821 to 0.000 events per REM hour.

At the participant level, `sync8_c0` was never worse than the matched control:

- equal in subjects 00, 01, 04 and 05;
- one fewer event in subject 02;
- two fewer events in subject 03.

This pattern is interesting but fragile with only six development
participants. Subject 03 generated many of the long-code collisions, and the
same data contributed noise backgrounds to synthetic threshold calibration.
The independent pilot test is therefore essential.

## Secondary interpretation

The short historical patterns behaved as predicted by prior reports. LRL
collided 143 times in REM and LRLR collided 44 times. Adding length reduced
the rate sharply, but length alone did not explain the ranking. The rhythmic
`sync8_c0` had fewer development collisions than the equal-duration
`iso8_matched`, its paired `sync8_c1`, and the longer paused historical
control.

This is evidence of background resistance, not an optimal code and not a
working dream communication channel. The next valid action is to commit these
thresholds unchanged and run the six sealed participants once.
