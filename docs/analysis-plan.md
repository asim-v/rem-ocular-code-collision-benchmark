# Analysis plan

## Scope

This project has two strictly separated components. The first is a provenance
and completeness audit of the public Donders contribution to real-time
communication during lucid REM sleep. The second is a prospective benchmark
of accidental ocular-code collisions in independent, uninstructed public PSG.
Donders is not used as validation data because the public files do not contain
the independent event and sleep-stage labels needed for that purpose.

The benchmark is a measurement study of background resistance. It is not a
confirmatory estimate of population-level dream communication performance.

The Dutch contribution reported eight communication attempts: one correct
response, no incorrect responses, one ambiguous response, and six trials with
no response. That sample is too small for supervised model fitting or a stable
estimate of communication capacity. It remains relevant only as provenance
and as motivation for a future independently labeled positive dataset.

## Data gates

### Gate A: trial reconstruction

Proceed to question-response analysis only if the release contains independent
timestamps, or sufficient acquisition records to reconstruct:

- the onset and offset of each question;
- the expected answer;
- the response interval;
- the original response category;
- REM scoring and arousal boundaries.

The expected answer must never be used to detect or delimit the physiological
response.

### Gate B: intentional-signal detection

Proceed to signal-detection analysis if intentional ocular signals can be
located independently of the proposed algorithm, even if question timestamps
are unavailable. Wake calibration signals are preferred. Otherwise, two human
raters must annotate candidate signals while blinded to expected answers.

### Gate C: false-alarm exposure

Estimate specificity only from continuous REM intervals in which the detector
is allowed to run without knowledge of stimulus timing. Negative exposure must
exclude instructed ocular tasks and margins around known signals, stimuli,
arousals, and stage transitions.

If none of these gates can be satisfied, the release cannot support the
proposed reanalysis. The reproducible audit and a prospective protocol will be
the appropriate outputs.

## Estimands

The following quantities are distinct and will not be conflated:

1. **Signal sensitivity:** detected unequivocal intentional signals divided by
   all unequivocal intentional signals.
2. **False-alarm rate:** unmatched detections per hour of eligible REM control
   exposure.
3. **Coverage:** questions receiving a nonambiguous decoded symbol divided by
   all questions.
4. **Selective accuracy:** correct symbols divided by all nonambiguous decoded
   symbols.
5. **End-to-end success:** correct symbols divided by all questions, including
   unanswered trials.

Ambiguous signals and absent responses are erasures at the communication
channel level. An absent response is not automatically a detector false
negative because the participant may not have emitted a signal.

## Independent negative-corpus benchmark

The active analysis uses Sleep-EDF Expanded as an uninstructed negative
corpus. A frozen pilot compares prespecified codes on participants held out by
subject. The primary endpoint is continuous false detections per expert-scored
REM hour. Synthetic injections check software robustness only and are never
called human sensitivity. See
[the frozen pilot protocol](ocular-code-pilot-protocol.md).

## Detector design

The primary detector will be a frozen, interpretable EOG pipeline:

1. construct or identify horizontal EOG;
2. apply a low-frequency-preserving filter suitable for saccades;
3. normalize within recording using robust scale estimates;
4. identify alternating horizontal deflections;
5. group deflections into left-right cycles under fixed duration and amplitude
   constraints;
6. score morphology with a prespecified template or dynamic time warping;
7. translate cycle count into a symbol;
8. abstain when confidence is insufficient;
9. merge overlapping detections with a fixed refractory rule.

Thresholds may be selected from wake calibration or an explicitly labeled
development record. They may not be tuned on the sole correct lucid-dream
answer and then evaluated on that answer.

## Controls and uncertainty

- Prefer within-session REM controls with comparable phasic or tonic REM
  composition.
- Do not use the instructed motor-decoding project as negative exposure.
- Report exact binomial intervals for trial proportions.
- Report a Poisson interval for false alarms per hour.
- If zero false alarms occur in `T` hours, report the one-sided 95% upper bound
  of approximately `3/T` false alarms per hour.
- Use block or episode-level resampling, never randomly split adjacent windows
  from the same recording between training and testing.
- Use circularly shifted event times or matched pseudo-onsets as secondary null
  analyses when timestamps are available.

## Information-theoretic analysis

Raw counts and the erasure rate are primary. Plug-in mutual information and a
Shannon-capacity claim are not justified by eight trials. If included, an
information rate will be explicitly labeled as model-based and accompanied by
wide uncertainty and prior-sensitivity analyses.

## Claim boundary

This analysis can evaluate physiological signal detection and ordinary
sensory-motor communication during REM sleep. It cannot test anomalous
information transfer, telepathy, or shared dreaming.
