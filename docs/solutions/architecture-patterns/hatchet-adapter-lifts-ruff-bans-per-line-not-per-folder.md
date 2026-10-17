---
title: The Hatchet adapter lifts ruff's import bans line by line, never by folder
date: 2026-10-17
category: architecture-patterns
module: Hatchet adapter import boundaries
problem_type: architecture_pattern
component: tooling
severity: medium
applies_when:
  - Adding a module under corvo.vendors.hatchet, such as another integration's listener
  - Ruff reports TID251 inside src/corvo/vendors/hatchet/ on a hatchet_sdk or corvo.vendors.hatchet import
  - Proposing a per-file-ignores entry for src/corvo/vendors/hatchet/** to quiet those reports
  - Adding a banned-api entry for another adapter, or a folder exemption for any package that must keep one of its bans
tags: [ruff, tid251, banned-api, noqa, import-boundaries, hexagonal, vendors, hatchet]
---

# The Hatchet adapter lifts ruff's import bans line by line, never by folder

## Context

`corvo.vendors.hatchet` is corvo's Hatchet adapter: only `corvo.worker` imports it, and it never imports `corvo.worker`. `ruff.toml` states both directions as TID251 banned-api entries (`ruff.toml:16-18`):

- `"hatchet_sdk"`: "Only corvo.worker and corvo.vendors.hatchet import Hatchet."
- `"corvo.vendors.hatchet"`: "Only corvo.worker imports corvo.vendors.hatchet."
- `"corvo.worker"`: "Only corvo.worker imports the worker."

Two facts about ruff (0.17.0) shape how a module inside the adapter gets past these bans. Both were checked by running ruff on stdin with the repo's config.

1. **A banned-api entry matches the module and everything under it, wherever the import is.** It has no "except from inside" clause. So the `corvo.vendors.hatchet` ban flags the adapter's own imports of its siblings. Moved to `src/corvo/vendors/hatchet/integrations/github/listener.py`, the GitHub listener was flagged on `hatchet_sdk`, on `corvo.vendors.hatchet.client` and on `corvo.vendors.hatchet.defaults`.
2. **`per-file-ignores` lifts a rule code, not one banned entry.** Every banned-api entry reports as the same code, TID251. An entry `"src/corvo/vendors/hatchet/**" = ["TID251"]` would therefore lift the `corvo.worker` ban in the adapter along with the two it meant to lift.

That second trap was hit once already (session history). #63's first draft of `ruff.toml` exempted the adapter's folder from TID251 so that `client.py` could import `hatchet_sdk`. The independent review in that session pointed out that this also let the adapter import the worker with ruff silent. The folder exemption was dropped for a line-level `noqa`.

## Guidance

A module under `src/corvo/vendors/hatchet/` puts `# noqa: TID251` on each of its adapter imports and on no other line. It explains the lift in a comment above them. `src/corvo/vendors/hatchet/client.py:1-3` does this for its one `hatchet_sdk` line, and the GitHub listener for its three:

```python
# Lifted on these three lines alone, so the module's other imports keep every
# ban: it must not import the worker, which imports it.
from hatchet_sdk import Context, EmptyModel, NonRetryableException  # noqa: TID251
from pydantic import BaseModel

from corvo.core.event_gateway.external_event_parser import parse
from corvo.vendors.hatchet.client import hatchet  # noqa: TID251
from corvo.vendors.hatchet.defaults import (  # noqa: TID251
    EVENT_SCHEDULE_TIMEOUT,
    EXECUTION_TIMEOUT,
    RETRIES,
)
```

(`src/corvo/vendors/hatchet/integrations/github/listener.py:31-42`.) A multi-line import is reported on its first line, so its `noqa` goes after the opening parenthesis, where `ruff format` keeps it. A module that imports nothing banned needs no `noqa`. `src/corvo/vendors/hatchet/defaults.py` imports only `datetime`.

Never add `src/corvo/vendors/hatchet/**` to `per-file-ignores`. A nested `ruff.toml` inside the adapter that redefines the bans is no way out either: corvo's CI reads no nested ruff config (`tests/unit/corvo/test_import_boundaries.py:7-8`).

Check a new adapter module with two ruff runs on stdin:

```bash
L=src/corvo/vendors/hatchet/integrations/github/listener.py
# Each lifted line is needed: without the comments, ruff names exactly those lines.
sed 's/  # noqa: TID251//' "$L" | uv run ruff check --stdin-filename "$L" --select TID251 -
# The worker ban is still live: an appended worker import is flagged.
{ cat "$L"; echo 'from corvo.worker.defaults import AGENT_CPUS'; } |
  uv run ruff check --stdin-filename "$L" --select TID251 -
```

## Why This Matters

Ruff's `corvo.worker` ban is the only thing that keeps the adapter from importing the worker:

- `tests/unit/corvo/test_import_boundaries.py` checks the agents' boundaries: the Agent SDK, `corvo.agents` and the main profile against the agent worker's side. It does not check vendors against the worker.
- The plan that moved the listener considered such a check and did not build it, because the line-level lift keeps ruff's ban live. It records that a per-file exemption for the adapter would change that call (`docs/plans/2026-10-17-1704-refactor-github-listener-to-vendors-plan.md`, Scope Boundaries).

So a folder exemption would not fail anything. CI stays green, and the boundary is gone without a trace. Each new listener under `corvo.vendors.hatchet.integrations` adds three `noqa` lines that look like noise, and the folder exemption is the obvious-looking cleanup. This doc exists to stop it.

`src/corvo/server/api/**` has exactly this gap today. It ignores TID251 wholesale for FastAPI and Starlette (`ruff.toml:26`), which also lifts its Hatchet and worker bans. Issue #64 (open) tracks a check for it in `test_import_boundaries.py`. The test folders exempted wholesale (`ruff.toml:27-28` and `30-31`) have the same gap, which is accepted: a test may need Hatchet's or the worker's names.

## When to Apply

- Writing or moving a module into `src/corvo/vendors/hatchet/`, such as a second source's listener under `corvo.vendors.hatchet.integrations`.
- Reviewing a change to `ruff.toml`'s `per-file-ignores`: ask which of TID251's bans the new path still needs.
- Adding a banned-api entry for another adapter under `corvo.vendors`: its own modules will be flagged the same way.

## Examples

Before, a folder exemption that lifts every ban, the worker's included:

```toml
[lint.per-file-ignores]
"src/corvo/vendors/hatchet/**" = ["TID251"]
```

After, no folder entry, and each adapter import lifted on its own line:

```python
from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet  # noqa: TID251
```

With the line-level lift, a listener that reaches for a worker value gets "TID251 `corvo.worker` is banned: Only corvo.worker imports the worker.". The listener's task defaults therefore moved to `corvo.vendors.hatchet.defaults`, from which every task and workflow now passes them (`docs/worker.md`). Importing `corvo.worker.defaults` with another `noqa` was rejected.

## Related

- `docs/solutions/best-practices/event-triggered-hatchet-task-reads-validates-and-tests.md`: how the GitHub listener reads, validates and tests its Hatchet events.
- `docs/worker.md`: where tasks, workflows and listeners live, and the defaults they pass.
- Issue #64: the server API's wholesale TID251 exemption, the same per-rule-code limit.
- #63: the change that set the adapter's bans and the first line-level lift.
