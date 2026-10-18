---
title: The Hatchet adapter's ruff exemption moves its worker ban into the import-boundaries test
date: 2026-10-17
category: architecture-patterns
module: Hatchet adapter import boundaries
problem_type: architecture_pattern
component: tooling
severity: medium
applies_when:
  - Adding a module under corvo.vendors.hatchet, such as another integration's listener
  - Adding or changing a per-file-ignores entry in ruff.toml for a package that must keep one of its bans
  - Adding a banned-api entry for another adapter under corvo.vendors
  - Changing ruff.toml and the code that depends on it in the same pull request
tags: [ruff, tid251, banned-api, per-file-ignores, import-boundaries, hexagonal, vendors, hatchet]
---

# The Hatchet adapter's ruff exemption moves its worker ban into the import-boundaries test

## Context

`corvo.vendors.hatchet` is corvo's Hatchet adapter: only `corvo.worker` imports it, and it never imports `corvo.worker`. `ruff.toml` bans both directions with TID251 banned-api entries (`ruff.toml:12-14`):

- `"hatchet_sdk"`: "Only corvo.worker and corvo.vendors.hatchet import Hatchet."
- `"corvo.vendors.hatchet"`: "Only corvo.worker imports corvo.vendors.hatchet."
- `"corvo.worker"`: "Only corvo.worker imports the worker."

Two facts about ruff (0.17.0) decide how the adapter's own modules get past these bans. Both were checked by running ruff on stdin with the repo's config.

1. **A banned-api entry matches the module and everything under it, wherever the import is.** It has no "except from inside" clause. So the `corvo.vendors.hatchet` ban flags the adapter's imports of its own modules: the GitHub listener was flagged on `hatchet_sdk`, `corvo.vendors.hatchet.client` and `corvo.vendors.hatchet.defaults`.
2. **`per-file-ignores` lifts a rule code, not one banned entry.** Every banned-api entry reports as TID251. An exemption for the adapter's folder therefore lifts its `corvo.worker` ban along with the two it meant to lift.

The adapter first lifted the ban line by line, with `# noqa: TID251` on each adapter import. That started in #63, where a draft folder exemption was dropped after review found it also let the adapter import the worker (session history). With the GitHub listener moved in, every new adapter module needed the same `noqa` lines. #67 replaced them with a folder exemption, and moved the worker ban into a test.

## Guidance

The adapter's folder is exempt from TID251 (`ruff.toml:22-25`). A module under `src/corvo/vendors/hatchet/` imports Hatchet and the adapter's own modules with no `noqa`.

`corvo.worker` stays off limits to the adapter, but ruff no longer checks it there. `tests/unit/corvo/test_import_boundaries.py` does. It names any module under `corvo.vendors.hatchet` that imports `corvo.worker`, whether by module or by `from corvo import worker` (`tests/unit/corvo/test_import_boundaries.py:188-194`). The test reads every module in the tree, so a new adapter module is covered without editing it.

Apply the same pairing to any package whose folder is exempted while it must keep one of its bans: add the folder to `per-file-ignores` only together with a rule in `test_import_boundaries.py` for the ban the exemption drops. A nested `ruff.toml` that redefines the bans for one folder is no way out: CI reads no nested ruff config (`tests/unit/corvo/test_import_boundaries.py:8-9`).

**Land a `ruff.toml` change before the code that relies on it.** CI reads `ruff.toml` from a pull request's base commit (`ruff.toml:1-3`). A pull request that adds the exemption and drops the `noqa` lines at once fails CI's lint on the old config. #67 added the exemption and the test rule and kept `client.py`'s `noqa`. Only after it merged did the pull request moving the listener drop all four.

## Why This Matters

Without the test rule, the exemption silently removes the boundary. `ruff.toml` stays green, CI stays green, and the adapter can import the worker that imports it. The rule is the only check of that direction now, so a change that weakens or removes it, or narrows `within(module, "corvo.vendors.hatchet")`, drops the boundary as surely as the exemption would have alone.

The test folders exempted wholesale (`ruff.toml:26` and `28-29`) have the same gap, which is accepted: a test may need Hatchet's or the worker's names.

## When to Apply

- Writing or moving a module into `src/corvo/vendors/hatchet/`: no `noqa` is needed, and `corvo.worker` stays off limits.
- Reviewing a `per-file-ignores` change: ask which of TID251's bans the new path still needs, and where the test checks it.
- Adding another adapter under `corvo.vendors` with its own banned-api entry: its modules get flagged the same way, and need the same exemption and test rule.

## Examples

A worker import in the adapter now fails the test, not ruff:

```text
corvo.vendors.hatchet.client imports corvo.worker.defaults: corvo.vendors.hatchet never imports corvo.worker, which imports it
```

That was checked by appending `from corvo.worker.defaults import AGENT_CPUS` to `src/corvo/vendors/hatchet/client.py` and running the test, then restoring the file. The same pressure moved the listener's task defaults out of `corvo.worker.defaults` and into `corvo.vendors.hatchet.defaults`, from which every task and workflow now passes them (`docs/worker.md`).

## Related

- `docs/solutions/best-practices/event-triggered-hatchet-task-reads-validates-and-tests.md`: how the GitHub listener reads, validates and tests its Hatchet events.
- `docs/worker.md`: where tasks, workflows and listeners live, and the defaults they pass.
- #67: the folder exemption and the boundaries-test rule.
- #63: the adapter's bans, and the first line-level lift.
