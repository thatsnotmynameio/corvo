# Running agents

corvo's agents run on the agent worker, `agent-worker` in `compose.yaml`. Each session's Claude engine runs in a bubblewrap sandbox and a cgroup of its own, and every shell command it runs goes through the Claude Agent SDK's own sandbox inside that. The Claude credential lives only in the credential proxy, `claude-proxy`. The agent worker's network, `agents`, is internal: it reaches the Hatchet engine and the proxy, and nothing else.

This document is what an operator needs to run them.

## What the host needs

- **cgroup v2, mounted with `nsdelegate`.** systemd mounts it so by default. Check with `grep cgroup2 /proc/self/mountinfo`: the options must include `nsdelegate`.
- **Docker 29.7.2 or later.** The agent worker's seccomp profile is generated from Docker 29.7.2's own (see [Refreshing the seccomp profile](#refreshing-the-seccomp-profile)), and the service uses the `writable-cgroups` security option.
- **On Ubuntu, unprivileged user namespaces.** Ubuntu 24.04's AppArmor refuses the user namespaces bubblewrap needs, and the agent worker then refuses to start (`agents refused: bubblewrap: …`). Two settings lift that, in order; apply the second only if the first is not enough:
  1. `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, kept across reboots in `/etc/sysctl.d/`. It applies to the whole host.
  2. `apparmor=unconfined` added to the `agent-worker` service's `security_opt`. It applies to that container only.

  GitHub's `ubuntu-24.04` runners needed both. Arch needs neither.

## Keep the kernel patched

Sessions run on the host's kernel and may create user namespaces, the area most kernel privilege escalations of recent years were reached through. The seccomp profile refuses netfilter sockets, the route CVE-2024-1086 took, but a kernel bug elsewhere would defeat every layer above it. Keep the host on a kernel with current security fixes.

## Credentials

Set the credential and its kind in `.env`. Only `claude-proxy` receives the credential; the agent worker holds only its kind, and each session sends a fixed placeholder that the proxy replaces. Compose starts nothing until both are set.

```
CORVO_AGENT_CREDENTIAL_KIND=api_key
CORVO_AGENT_CREDENTIAL=sk-ant-...
```

- **`api_key`**, the one for a product or service: an API key from a Claude Console workspace of its own, with a spend limit on that workspace. The spend limit is what bounds an agent's spending; corvo puts no ceiling of its own on a run. In the key's Console organization, turn off web search and web fetch: the proxy refuses the betas that make the API fetch from an address a request names, but web search needs no beta header.
- **`oauth_token`**: a token from `claude setup-token`, which lasts a year. Anthropic's terms allow a subscription only for the subscriber's own ordinary use: anything built on the Agent SDK for others must use an API key. The consumer terms and the subscriber's privacy settings, not the commercial terms, then govern the code the sessions send. A subscription has no Console organization, so web search and web fetch cannot be turned off for it.

To change the credential, edit `.env` and run `docker compose up -d claude-proxy`. Sessions in flight while the proxy restarts may fail.

## What a session's output carries

A session reads the repository content its agent is given, and its output and run log carry that content by design: the result, the engine's stderr lines and the report line. A workflow that publishes an agent's output, in a comment or a message, treats it as confidential as the repository itself.

## The first deployment

Start the agent worker, and let it pass its checks, before anything triggers an agent task on a new Hatchet tenant. A run of a task no worker has ever registered is lost: the engine refuses the trigger with `workflow names not found: <task>`, or, seen once on a development machine, returns a run ID it never stores.

Once an agent worker has registered a task, a run triggered while no agent worker is up waits in the queue, for up to `AGENT_SCHEDULE_TIMEOUT` (60 minutes), and runs when one starts.

## Sizing

At most `AGENT_MAX_RUNS` (2) sessions run at once across the tenant, and each gets `AGENT_MEMORY` (2 GiB, no swap), including its two tmpfs of 512 MiB. A cancelled run's slot frees before its session has ended, so a host holds memory for one session more than the cap: 3 sessions and the worker. The service's own limits, `mem_limit: 7g` and `pids_limit: 1024`, are sized for that. Raising the cap means raising them too.

## When the agent worker refuses to start

Before it registers any task, the agent worker checks its isolation, within 45 seconds. When a check fails, it logs `agents refused: <part>: <detail>` and exits, and compose restarts it. A passing cause clears on its own; a lasting one shows as a restarting container. Read it with `docker compose logs agent-worker`.

| Part | Means | Fix |
|---|---|---|
| `settings` | `CORVO_AGENT_ROOT`, `CORVO_AGENT_PROXY_URL` or `CORVO_AGENT_ENGINE` is not set. | Set it; `compose.yaml` and the image set all three. |
| `credential in environment` | The worker's own environment holds `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `CLAUDE_CODE_OAUTH_TOKEN`. | Remove it from the service: the credential belongs to `claude-proxy` alone. |
| `cgroup delegation` | No cgroup2 mount, one without `nsdelegate`, or no run cgroup can be made. | Run on cgroup v2 with `nsdelegate`, and keep the service's `writable-cgroups=true`. |
| `bubblewrap` | The session sandbox did not start, or shows more than it should: `/sys`, the worker's files, another process, or a variable outside its list. | On Ubuntu, see [What the host needs](#what-the-host-needs). Keep the service's seccomp profile and `systempaths=unconfined`. |
| `the SDK's sandbox` | A nested bubblewrap, the one the SDK runs each shell command in, did not start, or `socat` is missing. | As for `bubblewrap`; `socat` comes with the image. |
| `proxy` | No TCP connection to `CORVO_AGENT_PROXY_URL` within the bound; the detail ends with the last error. | Start `claude-proxy`, and check that both services are on the `agents` network. |

Any check that does not finish within 45 seconds is refused as `<part>: not done within 45 seconds`.

## What a failed run's log shows

Every run's log ends with its report line, `agent <name>: <outcome>, cost=<USD> turns=<n> session=<ID>`, and a failed run's error is `agent <name> failed: <reason>`.

- **Out of memory.** The kernel killed the session at its memory limit: the reason is `out of memory`.
- **A dead proxy.** The engine retries the API for about 3 minutes, then ends with an error result: the reason is `api_error`, with `turns=1`. A proxy that is down when the agent worker starts makes it refuse, as `proxy`.
- **The worker stopping.** A redeploy stops in-flight sessions before the worker exits, and their runs fail with `worker stopping`. They are not re-run.

## Re-runs fail

A run that Hatchet runs again, after a lost worker or a replay from the dashboard, fails before any session, with `this is a re-run (retry <n>)`: a second session would be paid again for nobody's asking. To run it again, trigger a new run, or replay the parent step, which starts a fresh child run.

## Working directories

An agent that works in a directory names it relative to `<CORVO_AGENT_ROOT>/workdirs`, which in compose is the `agent-root` volume at `/var/lib/corvo/agents`.

- The caller creates the directory before triggering the run, and deletes it after. It must be readable by uid 1000, and writable by it when the agent writes.
- The name must lead to an existing directory strictly below `workdirs`, symlinks followed. `workdirs` itself, absolute names, names that leave it and missing directories fail the run before any session.
- Keep credentials out of it, such as a token in `.git/config`: the session reads everything there.
- The session sees it read-only, unless the agent declares that it writes to it.

## Refreshing the seccomp profile

When the host's Docker moves to a new major version:

1. Replace `src/corvo/worker/agent_runtime/seccomp-moby-default.json` with moby's `vendor/github.com/moby/profiles/seccomp/default.json` at the new `docker-v<version>` tag, and update the tag in `corvo.worker.agent_runtime.seccomp`'s docstring and here.
2. Run `uv run python -m corvo.worker.agent_runtime.seccomp`, and review the difference in `seccomp.json`.
3. Run `uv run pytest tests/worker/agent_runtime/test_seccomp.py` and the integration suite.

## Proving an agent on Claude Haiku

No automated test calls Claude. Each agent is proven once against real Claude Haiku, by hand, and the run is recorded in its pull request.

1. Set a real credential in `.env`, preferably an API key from a workspace with a low spend limit, and the Hatchet token, created as `.env.example` says.
2. Start the stack: `docker compose up -d --build`.
3. Check that the agent worker passed its checks: `docker compose logs agent-worker | grep 'agents:'` shows `agents: every isolation check passed`.
4. In a second terminal, watch the run's peak process count while it runs:

   ```
   docker compose exec agent-worker sh -c \
     'while sleep 0.2; do cat /sys/fs/cgroup/agents/run-*/pids.peak 2>/dev/null; done'
   ```

5. Trigger the agent, here `tone`, from the main worker's container:

   ```
   docker compose exec worker python -c '
   from corvo.agents.tone.models import ToneInput, ToneOutput
   from corvo.worker.hatchet_client import hatchet
   tone = hatchet.stubs.task(name="tone", input_validator=ToneInput, output_validator=ToneOutput)
   print(tone.run(ToneInput(text="Thanks a lot, that was really helpful!")))
   '
   ```

6. Record in the pull request:
   - the output, here `tone='friendly' friendly=True`;
   - the report line, with its cost, turns and session ID: `docker compose logs agent-worker | grep 'agent tone:'`, or the run's log in the dashboard;
   - the peak process count, the last value step 4 printed;
   - what the session reached: the agent worker's only way out is `claude-proxy`, and the Console's usage for the workspace shows the requests.
7. Put the credential back as it was.
