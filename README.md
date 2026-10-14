# corvo

## Development

Needs [uv](https://docs.astral.sh/uv/). It installs the Python of
`.python-version` itself.

```sh
uv sync              # dependencies, in .venv
uv run fastapi dev   # the API, with reload, on http://127.0.0.1:8000
uv run pytest        # the tests, including the import contracts
uvx ruff format && uvx ruff check
```

Settings come from `CORVO_*` environment variables (`src/corvo/config.py`).
The database is PostgreSQL, through SQLAlchemy 2 (async) and asyncpg;
`CORVO_DATABASE_URL` defaults to
`postgresql+asyncpg://corvo:corvo@localhost:5432/corvo`.

Migrations are Alembic's, in `migrations/`:

```sh
uv run alembic revision --autogenerate -m "what changed"
uv run alembic upgrade head
```

A domain's `models.py` is imported in `migrations/env.py`, so autogenerate
sees its tables.

## Layout

The code is organized by domain, not by layer. Each domain is a package:

```
src/corvo/
├── main.py          # the FastAPI app: routers and business error to HTTP status
├── config.py
├── db.py            # the ORM base, the engine and the sessions
├── dependencies.py  # FastAPI dependencies: SessionDep, a session per request
├── exceptions.py    # CorvoError and its subclasses, which know nothing of HTTP
└── <domain>/
    ├── models.py    # SQLAlchemy models
    ├── schemas.py   # Pydantic models in and out
    ├── service.py   # the business logic: never imports fastapi
    └── router.py    # the HTTP routes: validate, call the service, answer
```

A router hands its `SessionDep` to the service, which commits. A service
raises a `CorvoError` subclass; `main.py` maps it to an HTTP status. The
services know nothing of HTTP, so another interface (a CLI, a worker) calls
them as they are. The contract in `[tool.importlinter]` of
`pyproject.toml` enforces it, through `tests/test_architecture.py`.
