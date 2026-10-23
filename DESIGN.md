# domestique — design

Status: concept draft, 2026-10-23. Written after several weeks of running
the pattern by hand on one athlete's data. No task specs beyond the first
four yet; this document is the source for them.

## Problem

Training advice from an LLM mostly comes from the textbook: a *prior*. What
an athlete actually needs is a *posterior*: what their own data says about
them, updated after every session. The failure mode is the assistant
speaking the prior in the voice of an observation ("ride the second session
5% easier" when this athlete's own history says otherwise).

The system closes that gap only if it stores and updates its own posterior,
explicitly, and labels which layer every statement comes from.

Analogy for engineers: the physiology literature is the Kubernetes docs, the
athlete is the cluster with its known quirks, the athlete's history is the
pager log. Nobody lets a debugging agent reason from the docs alone.

## The five cornerstones

### 1. Data plane (deterministic)

Everything the system may treat as fact, normalised and computed in code
before any model sees it. Stores and computes, never interprets.

- Executed sessions: streams, intervals, laps, and derived metrics
  (efficiency factor, decoupling, per-rep L/R balance, watts at a given HR,
  time of day, hours before bed).
- Planned sessions, kept separate from executed so plan-vs-execution is a
  join, not a guess.
- Wellness: HRV, resting HR, sleep duration and timing, weight, with the
  source and its known weaknesses attached.
- Load state: CTL/ATL/form and the FTP each ride was scored against (FTP
  history matters).
- Subjective inputs: RPE, feel, the one answer after each ride, illness,
  pain. Timestamped data, not chat.
- Context: calendar, work days, travel, race dates.
- Tests: threshold tests, step tests, anything that counts as ground truth,
  flagged so the athlete model weights it above inference.

"Decoupling was 0.8%" is data plane. "Durability is intact" is athlete
model, and must cite the first.

### 2. Athlete model (claims with provenance)

A versioned store of claims about the athlete. Each claim has text, a
**source layer**, confidence, status, timestamps, and evidence links.

| Source layer | Meaning | Example |
|---|---|---|
| `observed` | Derived from this athlete's data in layer 1 | "W/bpm reads 5–10% higher outdoors than on the trainer" |
| `stated` | Told to the system by the athlete | "Morning sessions are ridden 10% easier than evening ones" |
| `prior` | Textbook physiology, not yet confirmed on this athlete | "Fat oxidation peaks around 65–75% HRmax" |

Rules:
- Precedence on conflict: observed > stated > prior.
- Output must say which layer it speaks from: "your data shows" vs "you
  told me" vs "the literature says".
- Only `observed` claims can reach high confidence.
- A `prior` is promoted to `observed` after enough confirmed predictions on
  this athlete, or retired after enough misses.
- Append-only history; a claim's confidence trajectory is auditable.

### 3. Prediction and outcome loop

Turns a prescription into something the system can be wrong about.

- **Before** a session: write expected values (watts at target HR, RPE,
  peak HR, next-morning HRV, sleep duration), each naming the claim it came
  from.
- **After**: the data plane supplies actuals; a scoring step computes the
  gap.
- **On a miss**: lower the claim's confidence or retire it (if prior);
  propose a new claim; or draft a question for the athlete when the miss
  looks like intent rather than physiology.
- **On a hit**: raise confidence; promote priors.

Prediction error over time is the eval. Without this loop the athlete
model is a notebook that only grows.

### 4. Intent layer (decided by humans)

Everything a human decided, so the system never has to infer a decision.

- **Goals**: dated, ranked. Every plan is checked against them.
- **Constraints**: hours, work days, "no evening intensity". Facts about
  the athlete's life the planner respects and the model does not argue with.
- **Overrides**: moments the athlete overruled the system or the plan,
  stored with what the system predicted at the time, so the loop scores
  overrides too.
- **Safety rails**: rules nobody overrides from inside the system. Joint
  pain stops the plan. HRV under a floor downgrades the day. Ramp above a
  ceiling is refused. Illness means no intensity. Code, not prompts;
  triggering produces referral wording, not advice.

Precedence inside the layer: rails > current override > constraints >
goals. Against other layers: this layer wins. The intent behind a
prescribed session is asked, never inferred from workout text (a platform's
workout description is often boilerplate; the real intent lives in a
conversation).

### 5. Planner

Where the plan comes from. If sessions are prescribed elsewhere (a training
platform, a template, another person), this slot reads them, scores
execution and drafts questions, and writes nothing back. If the athlete is
self-planned, it is code: periodisation templates, a session library by
phase, a constraint check over ramp rate, form floor and the intent files.
The model adapts inside those rails and explains every session; it never
invents a plan free-form.

Self-planned additions: a 4–6 week **calibration block** (intake, tests,
HR/power relationships, RPE mapping, sleep response); **single-athlete
experiments** as a first-class feature (the way the system learns without
months of someone watching); **explain-why** on every session so the
athlete builds their own model.

## The sixth thing, which is not software

Accountability. Sessions happen when another human can see whether they
happened. A document does not get people out of bed. Deployment
requirement: a training partner, a team check-in, a shared ride event.
Build the hooks (weekly summary for a human, shared visibility), do not
pretend the software replaces it.

## What stays human

- Any write to a training platform is approved by a human.
- Race craft and the in-person read: a path for the system to draft a
  question for a trusted human rather than decide alone.
- Medical and injury management: never. Rails produce referral wording.

## Configuration lives on the athlete's machine

Nothing athlete-specific is in the repository. Ids, timezone, bedtime,
baselines and the intent files live in `$DOMESTIQUE_HOME` (default
`~/.config/domestique`); secrets in the environment. `examples/` shows the
shape with a synthetic athlete.

## Interfaces

- One question after each ride (Telegram/Slack bot). Much of what explains a
  session is said in passing; without this channel the system learns only
  from numbers and stays by-the-book.
- Morning brief, nightly debrief, weekly review, all scheduled.
- Weekly summary plus a queue of drafted questions, for the athlete and
  anyone they choose to share it with.

## Evals

Replay harness: feed a past season day by day, let the system predict,
score against what happened. Prediction error per metric over time is the
headline number and decides whether a prompt or rail change helped.

## Build order

Claims table and prediction loop over existing data first (tasks 001–003).
Everything else is plumbing. See `tasks/`.
