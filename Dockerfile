# The app's image, as the FastAPI template and uv's Docker guide build one:
# the dependencies in a layer of their own, then the project. The agent stage
# builds on it, and the last stage is the app again, so a build without
# --target, such as compose's, still gives the app's image.
# The Python patch is pinned, as Polar does: a floating tag falls behind
# .python-version and silently stays on a stale cached patch.
FROM python:3.14.7-slim AS app

# The uv the organization's CI runs.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

EXPOSE 8000

CMD ["uvicorn", "corvo.server.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

# The image every agent container runs, built into the agents' Podman store
# with `podman build --target agent`. The container mounts the run directory
# at /corvo/run, the working directory, if any, at /workspace, and tmpfs
# over /tmp and /home/agent, on a read-only root.
FROM app AS agent

ENV HOME=/home/agent

RUN mkdir -p /home/agent /corvo/run

# Empty in the image: an agent without a working directory runs here.
WORKDIR /workspace

ENTRYPOINT ["corvo-agent"]
CMD ["run"]

FROM app
