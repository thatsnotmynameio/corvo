# Concepts

> Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Agent isolation

### Agent worker
The worker that runs agent sessions, in a container of its own whose network reaches only the credential proxy and the task engine. It holds no Claude credential, and it never runs an agent's model engine outside an Outer sandbox.

### Engine
The Claude Agent SDK's bundled command-line program, which talks to the model and runs the agent's tools. Each session starts one Engine, and the Engine never starts outside an Outer sandbox.

### Outer sandbox
The fresh bubblewrap sandbox each session's Engine runs in, started with an empty environment and ended with the session. It sees only read-only system files and the Engine's own directory, a fresh process table and device set, temporary scratch and home directories, and the run's working directory, and it holds the session in its Run cgroup.
*Avoid:* session container

### Command sandbox
The Claude Agent SDK's own sandbox, which every shell command an Engine runs goes through, nested inside the Outer sandbox, with credentials scrubbed from the command's environment and its network limited to an allowlist. A session that would let a command run outside it is refused.

The Command sandbox and the Outer sandbox are not two copies of one protection: each closes openings the other leaves, so a session always runs inside both.

### Run cgroup
The cgroup made for one run before its session starts and removed after it, which limits that session's memory, CPU and processes without touching the Agent worker's own.

### Re-run
A second execution of a task run that the task engine starts on its own, after the run's worker stopped answering, or that a replay from the dashboard starts, as opposed to a new run someone triggers.

An agent run fails a re-run before its session starts: from inside the run the two causes look the same, and either would pay for a session again. To run an agent again, trigger a new run, or replay the step that spawned it, which starts a fresh run.

### Placeholder credential
The fixed stand-in credential every session sends in place of a real one, which the credential proxy replaces before forwarding to the Claude API. A real credential never enters an Outer sandbox.
