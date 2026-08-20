# Prespecified ocular-code collision pilot

## Purpose

This pilot asks whether temporal coding can make an intentional ocular marker
less likely to collide with spontaneous eye activity during REM sleep. It is a
negative-corpus benchmark. It does not estimate whether a lucid dreamer can
produce a code, and it does not test anomalous information transfer.

The primary hypothesis is:

> At matched nominal duration and matched synthetic detectability, a
> prespecified nonperiodic rhythm produces fewer background detections per REM
> hour than an isochronous ocular sequence.

The intended contribution is an open, continuous-time, exposure-normalized
benchmark. Automatic LRLR detection, activation keys, and ocular communication
from lucid REM have all been described previously and are not novelty claims.

## Data and split

The pilot uses the public Sleep-EDF Expanded sleep-cassette recordings from
PhysioNet. Each recording contains a horizontal EOG channel sampled at 100 Hz
and an expert-scored hypnogram.

The frozen manifest contains the first night from 12 different participants:

- subjects 00 through 05 form the development set;
- subjects 06 through 11 form the sealed pilot test set;
- no participant appears in both sets.

The development files may be used to verify software and select one detector
threshold per code. Test waveforms must not be read until the implementation,
configuration, and selected thresholds have been committed. A later
confirmatory benchmark will use the remaining SC participants and the ST
cohort as an external transport test.

## Code construction

The waveform alternates between horizontal gaze targets. A rhythm string
specifies dwell intervals between successive transitions:

- `S` is 0.35 seconds;
- `L` is 0.75 seconds;
- `E` is 0.55 seconds.

`P` is a one-second return-to-center pause. The primary candidate,
`sync8_c0 = SSLSLSLL`, and its paired symbol,
`sync8_c1 = SSLLSLSL`, each contain four short and four long intervals. Their
Hamming distance is four. Neither code has a proper suffix that is a prefix of
itself or the other code. These properties reduce ambiguous overlap in a
continuous stream, but they do not prove physiological usability.

The primary control, `iso8_matched = EEEEEEEE`, has the same number of
intervals and the same total nominal dwell time as `sync8_c0`. Historical
LRL, four-position LRLR, six-position LRLRLR, and two LRLR blocks separated
by a pause are historical secondary controls. The code definitions here are
alternating gaze-target sequences, not Morse-style center-left-center gestures.

The primary contrast is `sync8_c0` against `iso8_matched`. The wording will be
background resistance or empirical ranking, not optimal code.

## Preprocessing and detector

The horizontal EOG is converted to microvolts and filtered from 0.1 to 8 Hz
with a fourth-order Butterworth filter. The pilot is an offline benchmark and
uses zero-phase filtering. A causal implementation is required before online
deployment.

For each code, templates are evaluated at time scales from 0.8 to 1.2. The
detector scans continuously in 50 ms steps and computes absolute normalized
cross-correlation. Absolute correlation makes the detector invariant to EOG
polarity. A fitted template amplitude must exceed 1.5 times the robust MAD of
the preceding 300 seconds, updated every 30 seconds. This scale uses past data
only. Overlapping detections across time scales are merged by non-maximum
suppression.

Eligible negative exposure consists of windows fully contained in expert-
scored REM after removing a two-second boundary margin. No physiological
transients are removed merely because they resemble a code. Only objective
dropout, flatline, or clipping may be excluded, with excluded exposure
reported.

## Synthetic engineering check

Synthetic signals are added to otherwise untouched REM to check whether the
software can recover perturbed waveforms in realistic background noise. They
are not positive human examples and cannot estimate human sensitivity.

There are at most 20 anchors per recording, at least 60 seconds apart. The
same anchors are reused across codes for paired comparison. Signal polarity,
transition duration, plateau amplitude, timing jitter, and overshoot vary.
The primary calibration condition is four local MAD in amplitude and 15%
interval jitter. Signals are synthesized with smooth nonlinear transitions
that differ from the detector template.

For each code, the selected threshold is the largest prespecified correlation
threshold that reaches at least 90% sensitivity in the primary development
condition. Development false-alarm counts are not used to choose the
threshold. A code that cannot reach the target fails calibration and is not
evaluated on the sealed test set.

## Outcomes

The primary outcome is false detections per hour of eligible REM on unmodified
test recordings. This is the idealized endpoint with expert REM labels as an
oracle gate. Secondary outcomes are:

- the full synthetic sensitivity surface over amplitude and timing jitter;
- false detections per recording night when expert REM labels act as the
  activation gate;
- false detections per full recording hour with no stage gate, which provides
  a deliberately conservative operational bound;
- the implied probability of at least one false event in a 10-second query
  window;
- paired subject-level differences between the rhythmic and isochronous code;
- substitution and erasure rates for the `sync8_c0` and `sync8_c1` pair.

Uncertainty is estimated by a participant-clustered bootstrap. Exact Poisson
intervals are also reported for exposure-normalized event rates. If no event
occurs in `T` REM hours, the one-sided 95% upper limit is
`-log(0.05) / T`, not zero.

## Decision rule

The pilot supports scaling only if all of the following hold:

1. the complete pipeline reproduces from the frozen manifest;
2. both primary codes reach the development sensitivity target;
3. the sealed test results show a practically meaningful separation in
   background collision rate or a clearly informative null result;
4. conclusions remain limited to background resistance under synthetic
   calibration.

A full study must add many more independent REM hours, an independently
validated automatic REM gate, a causal detector, a wake production experiment,
and finally independently annotated intentional signals from lucid REM.

## Development amendment log

On 19 August 2026, after the protocol commit and a software smoke test on
development subject 00, the scale calculation was made explicit as a trailing
300-second MAD rather than the first 300 seconds of the recording. The first
300 seconds in this cassette contain wake activity and were not representative
of the scale at later candidate times. This clarification was made before
threshold selection and before any test file was downloaded. The correlation
grid, amplitude gate, target synthetic recovery, codebook, primary contrast
and sealed participants were unchanged. One minimum-score candidate count for
`sync8_c0` was seen during the smoke test and was not used for threshold
selection. The pilot remains developmental; a later full benchmark will be
frozen anew before its external datasets are read.

The first full development execution was stopped before writing any output
because the exact greedy non-maximum-suppression rule had a quadratic lookup
implementation. It was replaced with time buckets that preserve the same
score order and strict distance rule. Equivalence to the naive algorithm was
verified over randomized candidates at five suppression radii, including
zero. This was a performance-only change; no score, threshold, code or event
definition changed, and the development split was rerun from the beginning.
