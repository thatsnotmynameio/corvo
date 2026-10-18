# The app's image, as uv's Docker guide builds one: the dependencies in a
# layer of their own, then the project.
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

# The worker is the image's one program.
CMD ["corvo-worker"]

# The agent worker (KTD13): the app's image, with bubblewrap and socat for the
# two sandboxes each session runs in. Its entrypoint starts as root only to
# hand uid 1000 a cgroup subtree for the sessions, then drops root for good.
FROM app AS agent-worker

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap socat \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin agent \
    && find / -xdev -type f -perm /6000 -exec chmod ug-s {} +

# The SDK's engine, out of the SDK's package and off PATH, where the SDK's own
# discovery never finds it: an agent that leaves out cli_path then fails with
# CLINotFoundError instead of running the engine outside the sandbox.
RUN mkdir -p /opt/corvo/engine \
    && mv /app/.venv/lib/python3.14/site-packages/claude_agent_sdk/_bundled/claude \
        /opt/corvo/engine/claude

ENV HOME=/home/agent \
    CORVO_AGENT_ENGINE=/opt/corvo/engine/claude \
    CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1

ENTRYPOINT ["/app/src/corvo/worker/agent_runtime/entrypoint.sh"]
CMD ["corvo-worker"]

# The app's image stays the default target, for `docker build .` and compose's
# `build: .`.
FROM app
