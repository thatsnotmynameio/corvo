---
name: corvo
last_updated: 2026-10-14
---

# corvo Strategy

## Purpose

Alone with Claude Code, taking an idea to production is slow and low-quality, and it does not get better with use: the agents' judgment does not accumulate, so every run decides from scratch, the same mistakes come back, and I can never trust them with more autonomy.

## Positioning

Every decision goes to the cheapest, most predictable level that has proven it gets that decision right: deterministic script > System One > LLM > human. A gate moves down a level only with evidence from corvo's question bank, a generic judgment service whose first consumer is corvo's own workflows, so autonomy is earned gate by gate and brings efficiency and predictability with it. Everything we build is built to be reused across the corvo ecosystem, so autonomous agents assemble from parts that already work instead of improvising, and err less. The workflow engine is a third party's, because our time goes to the gates, not the engine.

## Users

**Primary:** Me, the boss - I'm hiring corvo to take my ideas to production, stepping in only at the gates that have not earned autonomy yet, and labeling the evidence that lets them earn it.

**Secondary:** My other projects and agents, which ask the question bank directly. Other solo builders running their own corvo, and a shared cloud in the spirit of Frigate+, come later and weigh on no decision now.

## Boundaries

- No autonomous releases, for now: the release gate stays with me even when the evidence says it could move down.
- No engine of our own: when Hatchet lacks something crew had, we fix the trigger (events, webhooks), not the engine.
- No compatibility with crew's config: corvo takes over crew's role, not its format; the workflows are redesigned around the gates and Hatchet.

_Resist a change when:_ it builds what the third-party engine already provides, or lets a decision move down a level without evidence from the question bank.

## Key metrics

- **Right decisions (G1)** - on autonomous gates, the share of conclusive answers that fresh labels confirm; the question bank's labels.
- **Decisions that matter (G2)** - the share of answers that predicted a real outcome; outcomes reported to the question bank.
- **Decisions per level** - the share made by script, System One, LLM and human, which must move down over time; corvo's decision log. Labeling is not counted as a human decision.
- **Escaped defects** - bugs found after release; GitHub issues labeled `bug`.
- **Lead time** - approved backlog to released in production; GitHub timestamps.

## Tracks

### Workflows

crew's role on Hatchet: the steps and triggers that take an issue to production.

_Why it serves the approach:_ it is where the gates live, on an engine that is not ours to build.

### Question bank

Versioned questions, judges as adapters, calibration and the maturity ladder.

_Why it serves the approach:_ it holds the evidence that decides when a gate may move down a level.

### Labels and outcomes

Where the evidence comes from: the labeling queue, LLM labelers, me, and real outcomes (G1 and G2).

_Why it serves the approach:_ without labels nothing is calibrated, and no gate earns autonomy.

### Decision ladder

How each gate picks its level (script, System One, LLM or human) and moves down when the evidence allows.

_Why it serves the approach:_ it turns calibrated answers into autonomy, efficiency and predictability.
