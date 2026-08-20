# Confirmatory ocular-code collision study

Protocol version 1, frozen before access to any waveform outside the completed
12-participant pilot.

## Purpose

This study tests whether the temporal pattern `sync8_c0` produces fewer
accidental matches in spontaneous REM electrooculography than the
equal-duration isochronous control `iso8_matched`.

The comparison is made at the same level of synthetic engineering recovery.
This corrects the main uncertainty left by the pilot, in which test recovery
was 87.5% for `sync8_c0` and 92.5% for `iso8_matched` at their frozen
thresholds.

The study contains no intentional human code productions. It cannot estimate
human sensitivity, motor usability, communication from dreams, lucidity,
information capacity or anomalous information transfer.

## Data separation

Participants 00 through 11 from Sleep-EDF sleep-cassette were used in the
pilot. They and all of their other nights are excluded from confirmatory
inference.

The new data are opened in three ordered stages:

1. **Primary confirmation:** every available night from the remaining
   Sleep-EDF sleep-cassette participants. Multiple nights remain grouped under
   one participant identifier.
2. **Threshold transport:** the placebo night from each Sleep-EDF
   sleep-telemetry participant. Temazepam nights are exploratory and are not
   part of the primary transport endpoint.
3. **Independent montage replication:** normal controls `n1` through `n15`
   from the CAP Sleep Database. Record `n16` is excluded because a metadata-only
   EDF header audit found no EOG channel.

The complete manifests, official SHA-256 digests and EOG derivations are
committed before any new waveform is downloaded or read. Results from a stage
must be committed before the next stage is opened.

## Independent unit and exposure

The independent unit is the participant. Nights, REM episodes, detections,
sliding windows and synthetic injections are not treated as independent
participants.

The primary exposure is horizontal EOG fully contained within manually scored
REM after removing two seconds from each REM boundary. Objective nonfinite
samples, sustained flatlines and acquisition dropout are excluded by frozen
numeric rules. Activity is not removed because it resembles a code.

Recordings with an absent declared EOG derivation, an unreadable expert
hypnogram, a checksum failure or an unrecoverable time-alignment failure are
excluded without examining detector results. Every exclusion and its lost
exposure are reported.

## Frozen detector

The detector retains the pilot design:

- target sampling rate of 100 Hz;
- 0.1 to 8 Hz fourth-order Butterworth filtering;
- offline zero-phase filtering;
- templates at time scales 0.8, 0.9, 1.0, 1.1 and 1.2;
- absolute normalized cross-correlation, making polarity irrelevant;
- an amplitude gate of 1.5 times the robust MAD from the preceding 300
  seconds, updated every 30 seconds;
- scanning every 50 ms;
- exact greedy non-maximum suppression with a one-second radius.

CAP channels sampled at 128, 200 or 512 Hz are combined according to the
frozen manifest and deterministically resampled to 100 Hz before the common
detector is applied. Resampling and annotation alignment are tested without
examining full new waveforms.

The detector first keeps every candidate with score at least 0.45. Final
operating points are obtained by filtering this single nested candidate list.
A lower-scoring candidate can therefore never suppress a higher-scoring
candidate only because a later operating point changed.

## Synthetic engineering reference

Synthetic injections test the software against realistic background noise.
They are not human signals and are never called human sensitivity.

The primary condition is unchanged from the pilot:

- amplitude of four local MAD units;
- 15% interval jitter;
- random polarity;
- prespecified variation in transition time, plateau amplitude and overshoot;
- at most 20 anchors per recording, separated by at least 60 seconds.

The same anchors and perturbation draws are paired across the two primary
codes. The surfaces at two and six MAD units and at 5% and 25% jitter are
exploratory.

## FROC construction

For code \(k\) and score threshold \(t\), define

\[
R_k(t)=\frac{\text{recovered primary-condition injections}}
             {\text{primary-condition injections}}
\]

and

\[
\lambda_k(t)=\frac{\text{background detections in eligible REM}}
                    {\text{eligible REM hours}}.
\]

The descriptive FROC grid is
\(t=0.450,0.455,\ldots,0.950\). The primary matched operating point is
\(\rho=0.90\).

For each code, \(\tau_k(\rho)\) is the largest observed score threshold that
recovers at least proportion \(\rho\) of the pooled primary-condition
injections. This is an empirical order-statistic rule based only on injection
scores. Background counts cannot influence the threshold. With at least 1,200
injections, the possible mismatch above 90% is less than one percentage point
unless tied scores occur. Ties and achieved recovery are reported.

If either code cannot reach 90% at the minimum candidate score, the primary
engineering requirement fails and no superiority claim is made. The curve is
not extrapolated.

## Primary endpoint and decision rule

At the matched 90% operating point, the primary estimand is

\[
\Delta_{90}=\lambda_{\mathrm{C0}}(0.90)
            -\lambda_{\mathrm{ISO}}(0.90).
\]

Negative values favor `sync8_c0`. The complementary rate ratio is

\[
RR_{90}=\frac{\lambda_{\mathrm{C0}}(0.90)}
              {\lambda_{\mathrm{ISO}}(0.90)}.
\]

The primary hypothesis is tested only in the untouched sleep-cassette cohort.
Lower background collision is confirmed when both codes meet the 90%
engineering requirement and the upper limit of the participant-clustered 95%
bootstrap interval for \(\Delta_{90}\) is below zero. A point estimate
\(RR_{90}\leq0.70\) is the separate practical gate for advancing the marker to
a human production study. It is not required to report the statistical
comparison.

If the point estimate is negative but the interval includes zero, the result
is inconclusive. It is not evidence of equivalence. If the estimate is zero or
positive, the proposed advantage is not supported.

## Uncertainty

The primary interval uses 50,000 bootstrap replicates with a frozen seed. Each
replicate resamples participants and carries all of a selected participant's
nights, exposure, candidates and injections together. The matched thresholds,
recoveries, rates and contrasts are recalculated inside every replicate.

Exact Poisson intervals for aggregate rates are descriptive because they do
not model participant heterogeneity. Participant-level paired counts, common
events and code-exclusive events are also reported.

The fixed public cohort determines the sample size. There is no optional
stopping. The precision target is at least 60 independent sleep-cassette
participants, 150 eligible REM hours and 1,200 primary-condition injections.
If objective exclusions leave less exposure, the analysis still runs but is
explicitly labeled as under the planned precision target. No corpus is added
after collision results are known.

## Secondary and external analyses

The only primary test is \(\Delta_{90}\) in the untouched sleep-cassette
cohort.

Secondary confirmatory analyses are \(\Delta_{85}\), \(\Delta_{95}\) and
transport of the two sleep-cassette 90% thresholds to placebo
sleep-telemetry. They are interpreted only if the primary test passes and are
controlled with Holm's procedure at family level 0.05.

The sleep-telemetry analysis reports two distinct quantities:

1. recovery and background rate at thresholds frozen in sleep-cassette, which
   measures actual threshold transport;
2. a newly matched 90% FROC point using only telemetry injection scores, which
   diagnoses the available tradeoff in that corpus.

CAP normal controls provide a second, montage-independent replication. Their
matched FROC comparison is external and descriptive unless a separate
inferential gate is committed before CAP waveforms are opened.

Historical LRL and LRLR controls, `sync8_c1`, other injection conditions,
full-night ungated scans, automatic REM gating, demographic heterogeneity,
drug-night contrasts and query-window probabilities are exploratory. They
cannot replace the primary endpoint.

## Integrity and amendment rules

Before each stage, the runner must verify a clean tracked Git revision, exact
hashes of code and configuration, exact source-file checksums and an empty
output directory. Outputs are never overwritten in place.

An error discovered after a new cohort is opened is documented publicly. If a
change can alter scores, events, exposure or REM classification, the original
output is retained and the correction is labeled as an amended analysis. It
does not silently replace the confirmatory run.

## Permitted conclusion

Even if the primary criterion succeeds, the strongest permitted conclusion is:

> At equal recovery of prespecified synthetic engineering signals,
> `sync8_c0` produced fewer background detections than an equal-duration
> isochronous control in the evaluated spontaneous REM corpus.

Human production, lucid-REM signaling and any future anomalous-information
experiment require separate prospective studies with a causal detector frozen
in advance.
