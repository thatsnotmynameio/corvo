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

## Workers

### Permission profile
The area of code a worker serves, named by `CORVO_WORKER_PROFILE`: the tasks and workflows it registers, and so the permissions it needs, such as `main` or `agents`. A worker serves exactly one profile and registers only that profile's definitions, so a task never runs on a worker holding more permissions than its profile. Every profile has a compose service, and every worker service states its profile.
*Avoid:* worker role

## Events

### Event
An immutable record that something happened, the unit corvo's work receives and emits. Nothing in it changes after creation, at any depth. It carries its own id, its parent's id and its chain's root id, so a chain of events reads like the spans of a trace.

An event built from an External event also carries that event's id, as its external id. Its children never inherit it, so only the root of the chain points back outside corvo.

### Root id
The id of the first event in a chain, carried by every event descended from it, so a whole chain is found without walking from parent to parent. A root event's root id is its own id.

### Category
A node in a tree of categories, each with an optional parent, that classifies an event. Categories are data that live outside code and grow there; an event references an existing one and never creates one. An event without a category has `unknown`, a fixed category with no parent.

### Label
A key-value pair of strings on an event, meant to be counted, as in how many events carry `repo=corvo`.
*Avoid:* tag

### External event
An event a source outside corvo publishes to the task engine, under a key that starts with that source's prefix, such as `github:issue:opened`. It is not a corvo event: the external event parser turns it into a root corvo event named `corvo:external_event:` followed by its key, whose external id is the id the task engine gave the external event.
