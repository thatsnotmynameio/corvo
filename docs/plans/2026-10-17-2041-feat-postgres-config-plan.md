---
title: Postgres Configuration After Polar - Plan
type: feat
date: 2026-10-17
topic: postgres-config
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Postgres Configuration After Polar - Plan

## Goal Capsule

- **Objective:** corvo's processes connect to PostgreSQL the way Polar's do. Pool, timeouts, SSL, SQL echo and a per-process `application_name` come from settings an operator sets through `CORVO_*` variables. No unused API or database code is left to compete with it, and Polar's Apache-2.0 terms are met.
- **Means:** one `src/corvo/postgres.py` holding Polar's async engine factory, new fields on the existing `src/corvo/settings.py`, and the deletion of `src/corvo/server/` (KTD1, KTD3).
- **Product authority:** the repository owner, who settled the decisions under Key Decisions. The Product Contract wins on behavior, and a KTD wins on mechanism within its cited requirements.
- **Stop conditions:** stop and report, without working around it, when:
  - a module outside `src/corvo/server/` turns out to import `corvo.server`, `fastapi`, `starlette`, `uvicorn` or `alembic`;
  - keeping a worker's behavior unchanged (R11) needs anything beyond the settings fields this plan adds;
  - the earlier CI pull request (U1) has not merged when the deletion (U2) is ready to open.
- **Execution profile:** two pull requests against main. The first holds U1 alone. The second holds U2, U3 and U4 in that order, opened once the first has merged.
- **Open blockers:** none.

---

## Product Contract

Product Contract preservation: changed: R1, R2, R3, R4, R7, R8, R9, R10 and R15, and R16 removed. During planning the owner folded the kit into `postgres.py` and kept `settings.py` as it is today, reading no env file. A new R19 covers `.env.example`.

### Summary

corvo gets Polar's PostgreSQL engine configuration in one module, `src/corvo/postgres.py`. It builds the async engine for a named process from settings and holds Polar's generic engine and sessionmaker factories. `src/corvo/settings.py` keeps its shape and gains Polar's environment, echo, pool, timeout and SSL fields. `src/corvo/server/` goes away, and with it the FastAPI app, the old engine, the ORM base and the migrations.

### Problem Frame

Today `src/corvo/server/database/engine.py` creates the engine with `create_async_engine(url)` and nothing else. There is no pool size, recycle, command or connect timeout, SSL, SQL echo, or `application_name`, so tuning the connection in production means changing code. The settings have no notion of environment. The FastAPI app in `src/corvo/server/api/` only serves `/health`, and no route uses its database session. It is dead weight and a second place where an engine gets built.

### Key Decisions

- **Only the async engine and its sessionmaker come over.** (session-settled: user-directed — chosen over also bringing Polar's `AsyncReadSession`/`AsyncSession` types, and over a full port with the read-replica and sync engines: with no replica and no repositories yet, those types protect little, and the sync engine would add `psycopg2`.) Governs R8, R9.
- **Polar's `postgres.py`, its kit and the `sql` names live in one `src/corvo/postgres.py`.** (session-settled: user-directed — chosen over Polar's `kit/db/` and `kit/extensions/sqlalchemy/` folders: no need to branch the tree for one engine.) Governs R1, R9, R10.
- **No FastAPI: `src/corvo/server/` is deleted whole.** (session-settled: user-directed — chosen over leaving the API untouched beside the new module, and over pointing its lifespan at the new engine: the API is unused, and keeping it would leave two engines.) Governs R12, R13, R14.
- **`src/corvo/settings.py` stays as it is today and only gains Polar's fields.** It keeps `get_settings()` with its cache, lower-case names, `CORVO_POSTGRES_PASSWORD` and its current `extra`. (session-settled: user-directed — chosen over Polar's `config.py` with a module-level instance and upper-case names: every reader and test keeps working as it does.) Governs R2, R3, R4, R5, R6, R7.
- **Settings read no env file.** (session-settled: user-directed — chosen over reading `.env` per environment as Polar does: compose's `.env` holds `CORVO_AGENT_CREDENTIAL` and the `HATCHET_*` values, so reading it would force `extra="ignore"` and change how the credential test proves its point.) Governs R3.
- **Compose passes `CORVO_ENV` to both workers, `development` unless set.** (session-settled: user-directed — chosen over containers always running on the default: an operator picks the environment in `.env`.) Governs R15, R19.
- **`Environment` has `development`, `testing` and `production`.** (session-settled: user-approved — chosen over Polar's full enum: its `sandbox` and `test` are Polar's own Render environments.) Governs R2.
- **`ProcessName` is `Literal["worker"]`.** (session-settled: user-approved — chosen over Polar's `app`/`worker`/`scheduler`/`script`: once `server/` is gone, corvo runs no app, scheduler or script.) Governs R8.
- **corvo has no migrations after this work.** (session-settled: user-approved — they live in `src/corvo/server/database/` and go with it. A later piece brings them back in Polar's structure.) Governs R12.

### Requirements

**Structure**

- R1. The engine configuration lives in one module, `src/corvo/postgres.py`, and the settings stay in `src/corvo/settings.py`. No `kit/` package and no `config.py` are created.

**Settings (`settings.py`)**

- R2. `settings.py` defines `Environment`, a `StrEnum` with `development`, `testing` and `production`, and an `env` field read from `CORVO_ENV` that defaults to `development`.
- R3. `Settings` keeps its `env_prefix="CORVO_"`, reads environment variables only, and keeps refusing unknown fields as it does today.
- R4. `Settings` gains Polar's database fields, in lower case, with Polar's defaults:
  - `sqlalchemy_debug` (`False`) and `postgres_ssl` (`False`);
  - `database_pool_size` (5), `database_pool_recycle_seconds` (600), `database_command_timeout_seconds` (30.0) and `database_connect_timeout_seconds` (10.0).

  The existing fields keep their names and defaults. `debug` goes, since only the deleted API read it.
- R5. `get_postgres_dsn(driver)` takes the driver as Polar's does (`Literal["asyncpg", "psycopg2"]`) and builds the URL with `URL.create(f"postgresql+{driver}", ...)`, with the password left unmasked.
- R6. `Settings` has `is_environment`, `is_development`, `is_testing` and `is_production`, as Polar's does.
- R7. Code and tests keep reading settings through `get_settings()`, and tests keep overriding them with environment variables and `get_settings.cache_clear()`.

**Engine (`postgres.py`)**

- R8. `postgres.py` defines `ProcessName` and `create_async_engine(process_name, *, pool_logging_name=None, pool_pre_ping=False)`. It builds the engine from the asyncpg DSN and `application_name=f"{settings.env.value}.{process_name}"`, with the pool logging name defaulting to the process name. From settings it also takes:
  - echo, pool size and recycle;
  - pre-ping;
  - the command and connect timeouts;
  - `ssl="require"` when `postgres_ssl` is set.
- R9. `postgres.py` also holds Polar's generic engine factory:
  - its `connect_args`: `prepared_statement_cache_size=0`, `application_name` under `server_settings`, `command_timeout`, `timeout` and `ssl`;
  - `echo`, the pool arguments, the Decimal-aware `json_serializer` and `query_cache_size=128`.

  It also holds `create_async_sessionmaker(engine)` with `expire_on_commit=False` and the `AsyncSessionMaker` type.
- R10. `postgres.py` exports Polar's `sql` names: `select`, `insert` (PostgreSQL's), `update`, `delete`, `func`, `Select`, `Insert`, `Update`, `Delete` and `ExecutableOption`.
- R11. The worker and the agent worker behave as they do today.

**Removal**

- R12. `src/corvo/server/` and `tests/unit/corvo/server/` are deleted.
- R13. Everything that existed only for the API or the migrations goes:
  - the `app` and `migrate` services in `compose.yaml`;
  - the uvicorn `CMD` and `EXPOSE 8000` in the `Dockerfile`;
  - `fastapi`, `uvicorn` and `alembic` in `pyproject.toml`, and any dev dependency only the API's tests used.
- R14. In `ruff.toml`, the `fastapi` and `starlette` bans and the `server/api` exemptions go. In `.github/python.yml`, the `corvo-server` collection and its `--ignore` go. `tests/unit/corvo/test_import_boundaries.py` no longer lists `corvo.server`.
  - The organization's CI reads `.github/python.yml` from a pull request's base commit. So the collection changes in an earlier pull request, and the pull request that deletes `tests/unit/corvo/server/` comes after it (KTD1).

**Compose**

- R15. The `x-corvo` anchor, which holds the `CORVO_POSTGRES_*` variables, goes with `app` and `migrate` under R13. The `db` service stays. After this work no compose service receives the database variables, so `agent-worker` still holds no database password. The `worker` and `agent-worker` services pass `CORVO_ENV`, defaulting to `development`.
- R19. `.env.example` documents `CORVO_ENV` and its three values.

**License (Apache-2.0)**

- R17. Each file derived from Polar starts with a notice: `src/corvo/postgres.py`, and `src/corvo/settings.py` for the parts it takes from Polar's `config.py`. The notice gives:
  - the Polar paths and the commit they came from;
  - "Copyright 2023 Polar Software Inc" and the Apache License 2.0;
  - that corvo modified the code, and what changed.
- R18. One copy of the Apache License 2.0 text from Polar's `LICENSE` sits in `src/corvo/`, and every notice points to it. Polar has no `NOTICE` file, so there is none to carry.

### Scope Boundaries

- The read-replica engine, the sync engine, `psycopg2`, and the `AsyncReadSession`/`AsyncSession` types: deferred until corvo has a replica or repositories.
- Polar's FastAPI request dependencies (`get_db_session`, `get_db_sessionmaker`, `get_db_read_session`) and its `TransactionalMiddleware`: corvo has no API.
- Polar's `config.py` shape: the module-level `settings`, upper-case names, `.env` per environment and `extra="allow"`. Rejected in favour of keeping `settings.py` (see Key Decisions).
- `POSTGRES_*_FALLBACK`, `POSTGRES_URL_NON_POOLING`, `DATABASE_SYNC_POOL_SIZE`, `DATABASE_STREAM_YIELD_PER`, and the rest of Polar's settings.
- Migrations and an ORM base in Polar's structure: a later piece.
- Giving a compose service the database variables: no process connects yet. The service that first does gets them then.

### Sources / Research

- Polar, Apache-2.0 (`LICENSE`: "Copyright 2023 Polar Software Inc"; no `NOTICE` file), at `main` `10fc4889db1f97e52bf67b74df567dbdea299267` on 2026-10-17:
  - `server/polar/postgres.py`: the process-named engine factories and the FastAPI dependencies.
  - `server/polar/kit/db/postgres.py`: the generic factories, `connect_args`, `json_serializer` and the sessionmakers.
  - `server/polar/kit/extensions/sqlalchemy/sql.py`: the statement re-exports.
  - `server/polar/config.py`: `Environment`, the database fields and defaults, `get_postgres_dsn`, and the `is_*` helpers.
  - `server/migrations/env.py`, which builds its own engine with `async_engine_from_config` rather than `polar.postgres`.
- corvo today:
  - `src/corvo/server/database/engine.py`, whose only importer is `src/corvo/server/api/server.py`;
  - `src/corvo/settings.py`, read through `get_settings()`;
  - the `x-corvo` anchor in `compose.yaml`, whose only users are `migrate` and `app`.
- Precedent for vendored Apache-2.0 material: `src/corvo/worker/agent_runtime/seccomp-moby-default.LICENSE` beside the vendored file, with its source and version named in `seccomp.py`'s docstring.

---

## Planning Contract

### Key Technical Decisions

- KTD1. **The earlier pull request folds the `corvo-server` collection into the catch-all, rather than leaving a collection that selects nothing.** It removes the `corvo-server` entry and the catch-all's `--ignore=tests/unit/corvo/server`, so the server's tests run in the catch-all. The organization's workflow reads `.github/python.yml` from the base commit. A path that does not exist makes pytest exit 4, which fails the job, while an empty selection exits 5, which passes. With the collection gone from the base, the deleting pull request needs no `python.yml` change for the server at all. This follows the #57-before-#58 precedent. Governs R14.
- KTD2. **The `Dockerfile`'s `app` stage runs `CMD ["corvo-worker"]` once uvicorn goes.** With no `CMD`, the default target would inherit the Python image's, and `tests/unit/corvo/worker/test_compose.py` could no longer tell what a `build: .` service without a `command` runs. The worker is now the image's only program. Governs R13.
- KTD3. **In `postgres.py`, Polar's generic kit factory becomes a private function, and the public `create_async_engine(process_name, ...)` keeps Polar's name.** The `sql` names become module-level names of `postgres.py` (R10), so callers write `from corvo.postgres import select`. Governs R8, R9, R10.
- KTD4. **The engine tests capture what reaches SQLAlchemy rather than open a connection.** The tests replace SQLAlchemy's `create_async_engine` inside `corvo.postgres` with a recorder and assert its arguments: the URL, `connect_args`, the pool arguments, `echo` and the JSON serializer. One test also builds a real engine without connecting and reads back its pool size and `echo`. No unit test needs a database. Governs R8, R9.
- KTD5. **The license copy is `src/corvo/polar.LICENSE`, and `pyproject.toml` keeps `license = "MIT"` with `license-files = ["LICENSE"]`.** This names the copy after its source, as `seccomp-moby-default.LICENSE` does. It also leaves the package metadata as the moby copy left it. Each notice names the commit in Sources / Research. Governs R17, R18.

### Assumptions

- `starlette`, `uvicorn` and `httpx2` stay in `uv.lock` through `mcp` after their direct entries go. Removing them from `pyproject.toml` drops only the direct pins.

---

## Implementation Units

### U1. Fold the server's test collection into the catch-all

- **Goal:** the CI configuration on main no longer names `tests/unit/corvo/server/`, so the later pull request that deletes it passes its own CI.
- **Requirements:** R14 (KTD1).
- **Dependencies:** none. This unit is a pull request of its own and merges first.
- **Files:** `.github/python.yml`.
- **Approach:**
  1. Remove the `corvo-server` collection (`yQxWQ7gk`).
  2. Remove `--ignore=tests/unit/corvo/server` from the catch-all collection.
  3. Keep the header comment's list of collections true.
- **Patterns to follow:** #57 (`cd09697`), which changed this file before #58 moved the tests.
- **Test expectation:** none -- CI configuration only.
- **Verification:** on this pull request, the base's `corvo-server` job still runs the server's tests. After merge, the catch-all job runs them.

### U2. Delete the server and what existed only for it

- **Goal:** no FastAPI app, old engine, ORM base, migrations or leftover reference to them remains in the repository.
- **Requirements:** R11, R12, R13, R14, R15 (the `x-corvo` part), R4 (the removal of `debug`).
- **Dependencies:** U1 merged.
- **Files:**
  - delete `src/corvo/server/` and `tests/unit/corvo/server/`;
  - `compose.yaml`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `ruff.toml`;
  - `src/corvo/settings.py` (the `debug` field);
  - `tests/unit/corvo/test_import_boundaries.py`, `tests/unit/corvo/worker/test_compose.py`;
  - `tests/unit/corvo/core/events/test_event.py`, `tests/unit/corvo/core/events/test_child.py`;
  - `docs/solutions/architecture-patterns/hatchet-adapter-ruff-exemption-keeps-worker-ban-in-a-test.md`.
- **Approach:**
  1. `compose.yaml`: drop `migrate`, `app` and the `x-corvo` anchor. Rewrite the header comment and the worker's "from the app's image" comment so they no longer describe an app.
  2. `Dockerfile`: drop `EXPOSE 8000` and the uvicorn `CMD`, add `CMD ["corvo-worker"]` to the `app` stage (KTD2), and reword the first line's FastAPI reference.
  3. `pyproject.toml`: drop `fastapi`, `uvicorn[standard]` and `alembic`, and the dev `httpx2`, which only FastAPI's test client used. Replace the description "corvo's API." with one that describes the project. Regenerate `uv.lock`.
  4. `ruff.toml`: drop the `fastapi` and `starlette` bans with their comment, and the two `server/api` per-file ignores.
  5. `settings.py`: drop `debug`.
  6. `test_import_boundaries.py`: drop `"corvo.server"` from the main-profile areas. Point the synthetic `corvo.server.api.x` cases (the SDK sample and the transitive-chain parametrize) at an area that still exists, and reword the docstring and comment that name the server.
  7. `test_compose.py`: replace the synthetic Dockerfile's uvicorn `CMD` and the "runs uvicorn" wording with a neutral command. The real-file check keeps passing on the new `Dockerfile`.
  8. The `docs/solutions` note: remove the `server/api` exemption it describes, and its pointer to issue #64.
  9. The event tests: change their sample `source="corvo.server"` values to `"corvo.worker"`. `Event.source` is plain text, so no behavior changes.
- **Patterns to follow:** #66, which took `corvo.worker.event_gateway` out of the worker with its tests and repointed the boundary tests.
- **Test scenarios:**
  - The import-boundaries suite passes with `corvo.server` gone. Its transitive-chain case still fails a declared module that reaches the SDK through an area that exists.
  - The real compose and Dockerfile pass `test_compose.py`: every worker service states its profile, and a `build: .` service without a `command` resolves to `corvo-worker`.
- **Verification:** `rg` finds no `corvo.server`, `fastapi`, `uvicorn`, `alembic` or port 8000 outside `docs/plans/` and `uv.lock`. `uv.lock` keeps `uvicorn` and `starlette` through `mcp` (see Assumptions). `docker compose config` resolves with no `app` or `migrate` service. The suite passes at the 90% coverage floor.

### U3. Add Polar's environment and database fields to the settings

- **Goal:** an operator can set the environment and the engine's pool, timeouts, SSL and echo through `CORVO_*` variables, and compose passes the environment to both workers.
- **Requirements:** R2, R3, R4, R5, R6, R7, R15 (the `CORVO_ENV` part), R17, R18, R19 (KTD5).
- **Dependencies:** U2.
- **Files:** `src/corvo/settings.py`, `src/corvo/polar.LICENSE`, `tests/unit/corvo/test_settings.py`, `compose.yaml`, `.env.example`.
- **Approach:**
  1. Copy Polar's `LICENSE` text verbatim to `src/corvo/polar.LICENSE`.
  2. In `settings.py`, add `Environment` and the fields of R2 and R4 next to the Postgres fields, with comments in the file's style saying what each one controls.
  3. Give `get_postgres_dsn` its `driver` argument, and add the `is_*` helpers.
  4. Start the module's docstring with the R17 notice. It names `server/polar/config.py` at the pinned commit and says which parts come from it: `Environment`, the database fields, `get_postgres_dsn(driver)` and the `is_*` helpers.
  5. Add `CORVO_ENV: ${CORVO_ENV:-development}` to the `worker` and `agent-worker` environments in `compose.yaml`, as `CORVO_LOG_LEVEL` is passed.
  6. Add a commented `CORVO_ENV` line to `.env.example` listing the three values.
- **Patterns to follow:** the existing fields and their comments in `settings.py`, and the `CORVO_LOG_LEVEL` pass-through in `compose.yaml`.
- **Test scenarios:**
  - `env` defaults to `development`, and `CORVO_ENV=production` reads as `Environment.production`.
  - `CORVO_ENV=staging` is rejected with an error naming `env`.
  - `is_development`, `is_testing` and `is_production` are true for their own environment only, and `is_environment` accepts a set.
  - Each new field has Polar's default: `sqlalchemy_debug` and `postgres_ssl` are false, and the pool size, recycle, command timeout and connect timeout are 5, 600, 30.0 and 10.0.
  - `CORVO_DATABASE_POOL_SIZE=12` and `CORVO_POSTGRES_SSL=true` read through.
  - `get_postgres_dsn("asyncpg")` gives the `postgresql+asyncpg://` URL the existing DSN tests expect, and `get_postgres_dsn("psycopg2")` gives `postgresql+psycopg2://` with the same parts.
  - The password-escaping test passes a driver and still round-trips `p@ss/w:rd#?`.
  - The credential test stays as it is and still passes: `Settings(agent_credential=...)` is refused.
  - The compose check still passes with `CORVO_ENV` added to both workers.
- **Verification:** `test_settings.py` and `test_compose.py` pass. `docker compose config` shows `CORVO_ENV: development` on both workers when `.env` leaves it unset.

### U4. Build the engine module from Polar's

- **Goal:** `corvo.postgres.create_async_engine("worker")` returns an engine configured from settings the way Polar's is, ready for the first process that connects.
- **Requirements:** R1, R8, R9, R10, R11, R17 (KTD3, KTD4).
- **Dependencies:** U3.
- **Files:** `src/corvo/postgres.py`, `tests/unit/corvo/test_postgres.py`.
- **Approach:**
  1. Start the module with the R17 notice. It names `server/polar/postgres.py`, `server/polar/kit/db/postgres.py` and `server/polar/kit/extensions/sqlalchemy/sql.py` at the pinned commit. It lists what changed: the files merged into one module, the read and sync engines and the FastAPI dependencies left out, the kit factory made private, settings read through `get_settings()`, and `ProcessName` narrowed to `worker`.
  2. Bring over the kit's generic factory as a private function (KTD3), with its `connect_args`, `json_serializer` and `query_cache_size`. Add `create_async_sessionmaker` and `AsyncSessionMaker` on plain SQLAlchemy `AsyncSession`.
  3. Bring over Polar's process-named `create_async_engine`, reading `get_settings()` (R8).
  4. Add the R10 names and an `__all__` that lists the public names.
- **Patterns to follow:** Polar's two files, line for line, apart from the changes the notice names. `src/corvo/worker/agent_runtime/seccomp.py`'s docstring shows how this repository names a vendored source.
- **Test scenarios:**
  - `create_async_engine("worker")` passes SQLAlchemy:
    - the `get_postgres_dsn("asyncpg")` URL;
    - `application_name="development.worker"` under `server_settings`;
    - `prepared_statement_cache_size=0`, `command_timeout=30.0` and `timeout=10.0`;
    - pool size 5, recycle 600, `pool_pre_ping=False` and `pool_logging_name="worker"`;
    - `echo=False` and `query_cache_size=128`.
  - With `CORVO_ENV=production`, the application name is `production.worker`.
  - With `CORVO_POSTGRES_SSL=true`, `connect_args` carries `ssl="require"`. Without it, `connect_args` has no `ssl` key.
  - With `CORVO_SQLALCHEMY_DEBUG=true`, `echo` is true.
  - `pool_logging_name` and `pool_pre_ping` passed by the caller reach SQLAlchemy.
  - The JSON serializer writes `Decimal("1.5")` as `1.5`, and raises `TypeError` for an object JSON cannot encode.
  - A real `create_async_engine("worker")`, built without connecting, reports pool size 5.
  - `create_async_sessionmaker(engine)` makes sessions that do not expire objects on commit.
  - `corvo.postgres.insert` is PostgreSQL's `insert`, so `on_conflict_do_nothing` is available on its statements.
- **Verification:** `test_postgres.py` passes without a database. mypy accepts the module under `strict`. The import-boundaries suite passes with the new module scanned automatically.

---

## Verification Contract

| Gate | Command | Applies to |
|---|---|---|
| Lint | `uv run --frozen ruff check` and `uv run --frozen ruff format --check` | U2, U3, U4 |
| Types | `uv run --frozen mypy` | U2, U3, U4 |
| Unit tests and coverage | `uv run --frozen pytest tests/unit` (CI holds 90% coverage of `src`) | U2, U3, U4 |
| Lockfile | `uv lock --check` | U2 |
| Compose | `docker compose config` | U2, U3 |
| Hooks | `prek run --all-files` | every unit |
| CI | the organization's Python checks on each pull request, including the Trunk collections | U1, and the second pull request |

---

## Definition of Done

- U1 is merged before the second pull request opens, and every check passes on both pull requests.
- `src/corvo/server/` and `tests/unit/corvo/server/` are gone. Nothing outside `docs/plans/` and `uv.lock` names `corvo.server`, FastAPI, uvicorn, alembic or port 8000.
- `src/corvo/postgres.py` and the new `settings.py` fields meet R1 to R10, each with the tests its unit lists.
- Both derived files carry the R17 notice, and `src/corvo/polar.LICENSE` holds Polar's license text unchanged.
- The worker and the agent worker start and serve as before (R11). Their only new input is `CORVO_ENV`.
- No experimental or abandoned code from the work is left in the diff.
