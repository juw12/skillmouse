---
name: refine-loop
description: Autonomous improve-until-done loop. Freezes a rubric, scores a baseline, iterates with a separate judge plus objective checks, keeps only real improvements, and stops on hard rules. Use when the user says "improve until perfect", "loop till 10/10", "/refine", or asks the AI to iterate without approval between rounds.
---

# Refine Loop

Goal: improve an artifact on its own until it **meets a written spec**, not until the AI *feels* it is perfect.
"Perfect" can't be measured. "Passes these checks" can.

## 0. Safety boundary (read first)

"Autonomous" means no human approval between rounds. It does **not** mean no limits.

- Allowed without asking: editing a **working copy** of the artifact, running tests and checks, re-judging.
- Always ask first: touching the original or any file outside the working copy, deleting, publishing or sending anything, paid usage beyond the budget, anything irreversible.

## 1. Freeze the rubric BEFORE generating

Write `rubric.md` first:

- **Hard gates**: pass/fail. Every gate must pass. Use a tool to check whenever possible (tests, build, word count, dimension check).
- **Soft criteria**: each scored 0–10, with a written anchor for 4, 7 and 10 so the scores mean something.
- **Weights** for the soft criteria.
- **Done** = all gates pass AND weighted soft score ≥ target (default **8.5**). Don't target 10: asking for 10 invites score inflation.

The rubric is frozen. The maker may not edit it. If the rubric is wrong, stop and report. Changing the rubric is a human decision.
If the goal is vague, derive the criteria from it and record them as assumptions in the log.

## 2. Score the baseline first

Judge v0 before changing anything and record the result. Every later claim of "better" is measured against this.

## 3. Separate the roles

| Role | Sees | Never sees |
|---|---|---|
| **Maker** | best version so far, rubric, latest feedback | – |
| **Checker** | the artifact | – (it's code: tests, linters, measurements) |
| **Judge** | the artifact + rubric only | maker reasoning, previous scores, round number |

- Checker results override the judge. A failing test beats a 9/10 opinion.
- Run the judge in a **fresh context** (new subagent or session), ideally on a different model.
- If no separate judge is available, clear the context between passes and label the scores **self-judged** in the report.

Judge prompt template:

```
You are a strict reviewer. You did not write this.
Score each criterion 0-10 using the anchors. For each score, quote the
specific evidence. List the 3 highest-impact fixes. Do not round up.
RUBRIC: <rubric.md>
ARTIFACT: <artifact>
```

## 4. The loop

```
best, best_score = v0, judge(v0)
stalls = 0
for round in 1..MAX_ROUNDS:                    # default 5
    candidate = maker(best, feedback)          # always revise from BEST, not latest
    gates = checker(candidate)
    if gates fail:
        feedback = gate failures
        continue
    score = judge(candidate)
    win = blind_pairwise(best, candidate)      # A/B, order randomized
    if score >= best_score + MIN_GAIN and win: # MIN_GAIN default 0.3
        best, best_score = candidate, score
        stalls = 0
    else:
        stalls += 1
    log(round)
    if done(best) or stalls >= 2 or over_budget:
        break
```

The **blind pairwise check** is the anti-inflation guard. Absolute scores drift upward over rounds. "Which of these two is better?", asked with the order shuffled, doesn't drift the same way. A candidate is kept only if both signals agree.

## 5. Stop rules (any one ends the loop)

1. Done definition met.
2. 2 rounds in a row without a kept improvement (plateau).
3. MAX_ROUNDS reached.
4. Time, token or cost budget reached.
5. The same gate fails 3 times: **blocked**. Stop and report it. Never dress it up as done.

## 6. Log every round

`refine_log.md`:

| Round | Change | Gates | Judge score | Pairwise win | Kept? | Note |
|---|---|---|---|---|---|---|

## 7. Final report

- Final artifact and the baseline → final score.
- Which results are **objective** (checker) and which are **judged**, and whether the judge was separate or self-judged.
- Criteria still below target, and why the loop stopped.
- Never claim "perfect". Say "meets rubric v1 at 8.7/10, all gates pass".

## Single-response mode (no tools or subagents)

When the host can't run code or open a fresh judge (e.g. a plain chat or SkillMouse on a local model), run the loop inside one answer:

1. Print the rubric (gates + 3–5 soft criteria with anchors).
2. Score the input as v0.
3. Revise up to 3 times. For each round, show the change, then re-score as a strict reviewer who didn't write it, quoting evidence.
4. Keep the best-scoring version, stop early on plateau, and output it last.
5. Label every score **self-judged** and list what a real checker should still verify.

## Anti-patterns

- Letting the maker grade its own work in the same context.
- Editing the rubric mid-loop to make the score go up.
- Revising from the latest version instead of the best one, so regressions pile up.
- Looping until "10/10" with no plateau or budget stop.
- Deleting tests or checks so the gates pass.
