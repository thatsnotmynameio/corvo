---
title: GitHub Listener in Vendors - Plan
type: refactor
date: 2026-10-17
topic: github-listener-to-vendors
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# GitHub Listener in Vendors - Plan

## Goal Capsule

- **Objective:** the code that turns GitHub's Hatchet events into corvo events lives in corvo's Hatchet adapter, as its first integration, not inside the worker's own machinery, and every `github:` event still becomes the same corvo event it does today.
- **Means:** move the external event parser workflow from `corvo.worker.event_gateway` to `corvo.vendors.hatchet.integrations.github.listener` unchanged, move the Hatchet task defaults it uses to `corvo.vendors.hatchet.defaults`, and point the worker's checks at the new area (KTD1, KTD2, KTD4).
- **Product authority:** the repository owner, who settled the decisions under Key Decisions. The Product Contract wins on behavior; a KTD wins on mechanism within its cited requirements.
- **Stop conditions:** stop and report, without working around it, when:
  - ruff flags a module under `src/corvo/vendors/hatchet/` under TID251 on any line other than the three KTD6 lifts, such as a `corvo.worker` import;
  - the registration test or the import-boundaries test cannot see the listener in its new area;
  - keeping a Hatchet name, a default's value or a test unchanged turns out to need a behavior change.
- **Execution profile:** one pull request against main, units in order U3, U1, U2.
- **Open blockers:** none.

---

## Product Contract

### Summary

The external event parser moves to `src/corvo/vendors/hatchet/integrations/github/listener.py`, and the package `corvo.worker.event_gateway` goes away. The main profile still registers it, under the same Hatchet workflow and task names, listening to the same prefixes. The Hatchet task defaults (`RETRIES`, `EXECUTION_TIMEOUT`, `WAITING_EXECUTION_TIMEOUT`, `EVENT_SCHEDULE_TIMEOUT`) move from `corvo.worker.defaults` to `corvo.vendors.hatchet.defaults`, and the worker reads them from there. The listener imports nothing from `corvo.worker`.

### Problem Frame

The parser listens only to GitHub's events, yet it lives in `corvo.worker.event_gateway`, next to the worker's profiles and agent runtime. #63 gave Hatchet its own adapter, `corvo.vendors.hatchet`, which only the worker imports and which never imports the worker. The GitHub listener is a Hatchet workflow for an outside source, so it belongs in that adapter. For it to live there, the task defaults it passes must come from the adapter too, since they describe Hatchet's retries and timeouts, not the worker.

### Key Decisions

- **The listener lives at `corvo.vendors.hatchet.integrations.github.listener`.** (session-settled: user-directed — chosen over `corvo.vendors.github.listener`: under `ruff.toml`'s rules only `corvo.vendors.hatchet` may import Hatchet, and only the worker may import `corvo.vendors.hatchet`.) Governs R1, R4.
- **The Hatchet task defaults move to `corvo.vendors.hatchet.defaults`, and the worker reads them from there.** (session-settled: user-directed — chosen over importing `corvo.worker.defaults` with a `noqa`, and over constants declared in the listener: these are Hatchet's defaults, not the worker's.) Governs R8.
- **Behavior and Hatchet names stay as they are.** (session-settled: user-approved — chosen over renaming the workflow or task to match the new module: a rename changes what Hatchet registers.) Governs R2, R3.
- **Only the unit test moves; the integration test stays in `tests/integration/corvo/worker/`.** (session-settled: user-approved — chosen over moving it beside the unit test: it needs that folder's conftest, which starts the stack and the worker.) Governs R5.
- **The pure conversion stays in `corvo.core.event_gateway`.** (session-settled: user-approved — chosen over a mirrored twin under `corvo.core.vendors`: `parse` serves any source prefix, not only GitHub.) Governs R7.
- **This work changes neither `ruff.toml` nor `.github/python.yml`.** (session-settled: user-directed — chosen over adding an exemption or a Trunk collection here: the adapter's rules and the `corvo-vendors` collection came with #63.) Governs R6.

### Requirements

**The listener**

- R1. The workflow, its task, `EXTERNAL_PREFIXES` and `ParsedOutput` live in `src/corvo/vendors/hatchet/integrations/github/listener.py`, and `src/corvo/worker/event_gateway/` no longer exists.
- R2. Hatchet registers the workflow as `external-event-parser` with `on_events` `["github:*"]`, and its task as `external_event_parser`, with the same retries, execution timeout and schedule timeout.
- R3. A `github:` event still publishes one `corvo:external_event:` event, and an event that is no corvo event still fails at once without a retry.
- R4. The main profile in `src/corvo/worker/profiles/main.py` still serves the workflow.

**The defaults**

- R8. `RETRIES`, `EXECUTION_TIMEOUT`, `WAITING_EXECUTION_TIMEOUT` and `EVENT_SCHEDULE_TIMEOUT` live in `src/corvo/vendors/hatchet/defaults.py` with their values and comments unchanged. The `AGENT_` values stay in `corvo.worker.defaults`, and nothing re-exports the moved names from there.

**Tests and checks**

- R5. The listener's unit test lives at `tests/unit/corvo/vendors/hatchet/integrations/github/test_listener.py` with its cases unchanged, and the integration test stays at `tests/integration/corvo/worker/test_event_gateway.py`.
- R6. `tests/unit/corvo/worker/test_registration.py` and `tests/unit/corvo/test_import_boundaries.py` check `corvo.vendors.hatchet.integrations` as a main-profile area in place of `corvo.worker.event_gateway`. `ruff.toml` and `.github/python.yml` stay as they are.

**Documentation**

- R7. Docstrings, comments, `docs/worker.md` and `docs/solutions/` name the new module, defaults and test paths. Plans under `docs/plans/` keep their old paths as history.

### Scope Boundaries

- Renaming the module's symbols or the Hatchet names: outside this work (see Key Decisions).
- Moving or renaming `corvo.core.event_gateway`: outside this work.
- Moving the `AGENT_` limits: they are the agent worker's, and stay in `corvo.worker.defaults`.
- A check in `test_import_boundaries.py` that `corvo.vendors.hatchet` never imports `corvo.worker`: considered and not built. `ruff.toml` lifts TID251 inside the adapter line by line, so its `corvo.worker` ban still flags such an import. A per-file exemption for `src/corvo/vendors/hatchet/**` would change this call.

### Sources / Research

- #63 (`refactor: move the Hatchet client to corvo.vendors.hatchet`, merged) set the adapter's rules on main:
  - `ruff.toml` bans `hatchet_sdk` outside `corvo.worker` and `corvo.vendors.hatchet`, and `corvo.vendors.hatchet` outside `corvo.worker`. It exempts only `tests/unit/corvo/vendors/hatchet/**` from TID251, besides the worker's and the API's paths.
  - `src/corvo/vendors/hatchet/client.py` lifts TID251 on its one `hatchet_sdk` import line with `# noqa: TID251`, and states it "must not import the worker, which imports it".
  - `.github/python.yml` has a `corvo-vendors` collection for `tests/unit/corvo/vendors`.
  - The listener and its test already import `corvo.vendors.hatchet.client`.
- Ruff, run on stdin with main's config at the listener's new path, flags `hatchet_sdk`, `corvo.vendors.hatchet.client` and `corvo.vendors.hatchet.defaults`, because the `corvo.vendors.hatchet` ban matches by parent module. It also flags a `corvo.worker` import. At the test's new path it flags nothing.
- On main, the four moved defaults are used only by the listener, its unit test and `tests/unit/corvo/worker/test_defaults.py`, besides `docs/worker.md` and two solution docs. Every other user of `corvo.worker.defaults` reads only `AGENT_` values.
- `docs/solutions/best-practices/hatchet-retries-zero-is-not-at-most-once.md` cites `src/corvo/worker/defaults.py:21-28` for the durable-task comment and `:47` for the agent retry comment, which is already at line 53 on main.
- `tests/integration/corvo/worker/conftest.py`: `stack`, `worker`, `hatchet` and `DONE`, which `test_event_gateway.py` uses. That test imports only `corvo.core`.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **A plain move, history kept.** The listener and its test move with `git mv`. Only the docstring and the imports change, so `git log --follow` finds their history. The module keeps `logging.getLogger(__name__)`, so its logger becomes `corvo.vendors.hatchet.integrations.github.listener`. Nothing filters on the old logger name: `src/corvo/worker/worker.py` sets only the root logger's level. Instantiates the Key Decisions that govern R1 to R3.
- KTD2. **`corvo.vendors.hatchet.integrations` is the main-profile area.** `AREAS["main"]` and `MAIN_PROFILE_AREAS` name it, not the GitHub package, so a second source's listener is checked without editing either test. The area excludes `corvo.vendors.hatchet.client`, which defines no workflow. `src/corvo/vendors/hatchet/integrations/__init__.py` and `.../integrations/github/__init__.py` are empty, like the adapter's own packages, and must exist, or the registration test's `unpackaged` check fails. Governs R6.
- KTD3. **The test's packages copy the adapter's layout.** `tests/unit/corvo/vendors/hatchet/integrations/__init__.py` and `.../integrations/github/__init__.py` exist and are empty, like `tests/unit/corvo/vendors/hatchet/__init__.py`. The parser test uses no fixture from `tests/unit/corvo/worker/conftest.py`, so it loses nothing by leaving that folder. Governs R5.
- KTD4. **The adapter depends on nothing in the worker.** The listener imports `corvo.core.event_gateway`, `corvo.vendors.hatchet.client`, `corvo.vendors.hatchet.defaults` and `hatchet_sdk`. The worker imports the listener, through its main profile, and the defaults. `corvo.vendors.hatchet.defaults` itself imports only `datetime`. Ruff's `corvo.worker` ban enforces the direction (KTD6). Governs R1, R8.
- KTD5. **The defaults' test moves with them.** `test_waiting_timeout_covers_every_attempt_of_a_child` and `test_an_event_task_waits_longer_than_hatchets_default` move to `tests/unit/corvo/vendors/hatchet/test_defaults.py`. The agent tests stay in `tests/unit/corvo/worker/test_defaults.py`. Both files declare the `DETECTION_LAG` they use. The moved file also declares `SCHEDULING_TIMEOUT`, which only the moved tests read. Governs R8.
- KTD6. **The listener lifts the adapter's ban line by line, as `client.py` does.** Its three adapter imports, `hatchet_sdk`, `corvo.vendors.hatchet.client` and `corvo.vendors.hatchet.defaults`, each carry `# noqa: TID251`, and no other line does. The `corvo.worker` ban therefore stays live on the module. The test needs no `noqa`, since its folder is exempt. Governs R1.

---

## Implementation Units

### U3. Move the Hatchet task defaults

- **Goal:** the four task defaults live in `corvo.vendors.hatchet.defaults`, and the worker reads them from there.
- **Requirements:** R8, R7.
- **Dependencies:** none.
- **Files:**
  - Create `src/corvo/vendors/hatchet/defaults.py`.
  - Modify `src/corvo/worker/defaults.py`.
  - Create `tests/unit/corvo/vendors/hatchet/test_defaults.py`.
  - Modify `tests/unit/corvo/worker/test_defaults.py`.
- **Approach:**
  1. Move `RETRIES`, `EXECUTION_TIMEOUT`, `WAITING_EXECUTION_TIMEOUT` and `EVENT_SCHEDULE_TIMEOUT`, with their comments and doc links, to the new module (KTD4).
  2. Give the new module a docstring in the style of the old one: Hatchet's retries and timeouts, which every task passes, and why `TaskDefaults` does not fit.
  3. In `corvo.worker.defaults`, narrow the docstring to the agent limits. Point the `AGENT_WAITING_EXECUTION_TIMEOUT` comment, which names `WAITING_EXECUTION_TIMEOUT`, at its new module.
  4. Split the defaults' tests per KTD5.
- **Patterns to follow:** `src/corvo/worker/defaults.py`'s comment style: one comment per value, naming its reason and Hatchet's doc page.
- **Test scenarios:**
  - Test expectation: none -- the values do not change. The two moved tests prove the same invariants from the new module: the waiting timeout covers every attempt of a child, and an event task waits longer than Hatchet's default.
- **Verification:** both defaults test files pass. `corvo.worker.defaults` no longer defines a moved name, so any import of one from there fails mypy and the tests.

### U1. Move the listener and its unit test

- **Goal:** the listener and its unit test live in `corvo.vendors.hatchet.integrations.github`, and the main profile serves it from there.
- **Requirements:** R1, R2, R3, R4, R5.
- **Dependencies:** U3.
- **Files:**
  - Move `src/corvo/worker/event_gateway/workflows/external_event_parser.py` to `src/corvo/vendors/hatchet/integrations/github/listener.py`.
  - Create `src/corvo/vendors/hatchet/integrations/__init__.py` and `src/corvo/vendors/hatchet/integrations/github/__init__.py`.
  - Delete `src/corvo/worker/event_gateway/__init__.py` and `src/corvo/worker/event_gateway/workflows/__init__.py`.
  - Move `tests/unit/corvo/worker/event_gateway/workflows/test_external_event_parser.py` to `tests/unit/corvo/vendors/hatchet/integrations/github/test_listener.py`.
  - Create `tests/unit/corvo/vendors/hatchet/integrations/__init__.py` and `tests/unit/corvo/vendors/hatchet/integrations/github/__init__.py`.
  - Delete `tests/unit/corvo/worker/event_gateway/__init__.py` and `tests/unit/corvo/worker/event_gateway/workflows/__init__.py`.
  - Modify `src/corvo/worker/profiles/main.py`.
- **Approach:**
  1. Move both files with history kept (KTD1), and add the empty packages (KTD2, KTD3).
  2. Rewrite the listener's docstring opening: `corvo.vendors.hatchet.integrations` holds the Hatchet workflows through which outside sources' events cross into corvo, and the main profile serves them. In the thin-shell sentence, drop "at the mirrored path" and name `corvo.core.event_gateway` as where the logic lives. Keep the rest of the docstring as it is: the anchored prefix match, retries and `EmptyModel`.
  3. Point the listener's and the test's defaults import at `corvo.vendors.hatchet.defaults`, and the test's listener import at the new module. Lift TID251 on the listener's three adapter imports per KTD6.
  4. Point the profile's import at the new module, and rewrite its comment to name `corvo.vendors.hatchet.integrations` in place of `corvo.worker.event_gateway`.
- **Patterns to follow:** `src/corvo/vendors/hatchet/client.py`'s `noqa` line and the comment above it; the empty `__init__.py` files of `src/corvo/vendors/hatchet/` and `tests/unit/corvo/vendors/hatchet/`.
- **Test scenarios:**
  - Test expectation: none -- behavior is unchanged. The moved test's existing cases prove R2 and R3 from the new path: workflow and task names, `on_events == ["github:*"]`, the retry and timeout settings, one publish per event, and an immediate failure with no retry for a bad event.
- **Verification:** the moved test passes from its new path, and ruff flags nothing in the listener.

### U2. Point the checks and docs at the new area

- **Goal:** the registration and import-boundaries checks cover the listener in its new area, and the docs name its new paths and the defaults' module.
- **Requirements:** R6, R7.
- **Dependencies:** U1, U3.
- **Files:**
  - Modify `tests/unit/corvo/worker/test_registration.py`.
  - Modify `tests/unit/corvo/test_import_boundaries.py`.
  - Modify `src/corvo/core/event_gateway/external_event_parser.py`.
  - Modify `docs/worker.md`.
  - Modify `docs/solutions/best-practices/event-triggered-hatchet-task-reads-validates-and-tests.md`.
  - Modify `docs/solutions/best-practices/hatchet-retries-zero-is-not-at-most-once.md`.
- **Approach:**
  1. In `test_registration.py`, swap the import and the `AREAS["main"]` entry from `corvo.worker.event_gateway` to `corvo.vendors.hatchet.integrations`, and update the docstring's area list (KTD2).
  2. In `test_import_boundaries.py`, swap the `MAIN_PROFILE_AREAS` entry the same way.
  3. In the core module's docstring, name the listener's new module as the workflow that reads the event, and drop "at the mirrored path", which no longer holds.
  4. In `docs/worker.md`, make these changes:
     - Replace the sentence that names `corvo.worker.event_gateway` with one saying that the listeners in `corvo.vendors.hatchet.integrations` follow the same rules. The one exception: a listener's logic need not sit at the mirrored path, and the GitHub listener's is in `corvo.core.event_gateway`.
     - Point the mentions of `corvo.worker.defaults` in the top-level declaration rule and the `WAITING_EXECUTION_TIMEOUT` rule at `corvo.vendors.hatchet.defaults`. The `AGENT_WAITING_EXECUTION_TIMEOUT` rule keeps `corvo.worker.defaults`.
  5. In `event-triggered-hatchet-task-reads-validates-and-tests.md`, update the module, defaults and test paths and the `applies_when` line. Match the line numbers in its citations to the moved files.
  6. In `hatchet-retries-zero-is-not-at-most-once.md`, point the durable-task citation at the `WAITING_EXECUTION_TIMEOUT` comment's lines in `src/corvo/vendors/hatchet/defaults.py`, and match its citation of the `AGENT_` retry comment to that comment's line in `src/corvo/worker/defaults.py`.
- **Patterns to follow:** how each test already lists `corvo.worker.tasks` and `corvo.worker.workflows`.
- **Test scenarios:**
  - Test expectation: none -- the two checks change which area they read, not what they assert. `test_every_definition_in_the_areas_is_on_its_profile` still passes with the listener found under its new area. `test_the_tree_keeps_the_agents_boundaries` still passes with that area on the main profile.
- **Verification:** removing `external_event_parser` from the main profile's list makes the registration test name the listener under its new module path as on no worker. Check this by hand and revert it.

---

## Verification Contract

| Gate | Command | Proves |
|---|---|---|
| Lint, format, types, lockfile | `uv run prek run --all-files` | ruff (TID251 under main's rules, KTD6), ruff format, mypy strict over `src` and `tests`, `uv lock --check` |
| Unit tests | `uv run pytest tests --ignore tests/integration` | R2 to R6 and R8: the moved tests, registration, import boundaries |
| Integration tests | `uv run pytest tests/integration/corvo/worker/test_event_gateway.py` | R3 and R4 on the real engine: the worker serves the listener from its new module |
| Leftover references | `rg -n 'worker[./]event_gateway' --glob '!docs/plans/**'` | R1 and R7: no reference to the old path remains outside the historical plans |
| No worker import in the adapter | `rg -n 'corvo\.worker' src/corvo/vendors` | KTD4: nothing in the adapter imports the worker |
| CI | the org workflow `tnmn.io: python` on the pull request | the same gates, with coverage at 90, and the `corvo-vendors` collection running the moved tests |

---

## Definition of Done

- Every gate in the Verification Contract passes locally, and CI passes on the pull request.
- `git log --follow src/corvo/vendors/hatchet/integrations/github/listener.py` reaches the parser's history.
- No abandoned attempt remains in the diff: no leftover packages, re-exports or shims under `corvo.worker.event_gateway` or `corvo.worker.defaults`.
- Per unit:
  - U3: the moved defaults keep their values, and `corvo.worker.defaults` holds only `AGENT_` values.
  - U1: the moved test passes unchanged except for its imports, and the listener has exactly three `noqa: TID251` lines.
  - U2: the registration test names a listener that is missing from the main profile under its new module path.
