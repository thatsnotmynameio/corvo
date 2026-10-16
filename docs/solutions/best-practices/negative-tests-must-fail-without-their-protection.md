---
title: A negative test must fail when the protection it proves is removed
date: 2026-10-16
category: best-practices
module: agent isolation tests
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - A test asserts that something is refused, hidden, kept out or left unwritten
  - A test proves a sandbox, a filter, a permission or a redaction
  - A negative test runs where users, permissions or log levels differ from the author's machine, as on CI
tags: [testing, negative-tests, isolation, sandbox, mutation-check, ci, proxy-log, read-only]
---

# A negative test must fail when the protection it proves is removed

## Context

The agents skeleton (stack #31 to #46) has many tests that prove that something does not happen: a sandbox refuses, a proxy hides a header, a working directory stays unwritten. Three of them passed with their protection removed. The authors did not notice in any of the three cases: review found each one, and each had a different cause.

1. **A check that failed earlier decided the result.** Before it checks the sandbox's content, `assert_isolated` (`tests/agents/isolation.py:23`) checks that the agent's options carry the session's values, `options.sandbox == session.sandbox` among them (line 50). The content checks come after that, such as `enabled`, `failIfUnavailable` and `allowUnsandboxedCommands`. The weakened-sandbox cases changed only the options, so the equality check failed first. Deleting every content check left all the tests green.
   - **Fix:** the weakened sandbox now goes into the session too, so its content is the only thing that can fail (`tests/agents/test_isolation.py:105-111`). With the content checks removed, all seven sandbox cases now fail. That fix is in #35.
2. **The evidence was never produced.** The proxy's log test sent a request too large to accept (a 413) and one to a path the proxy does not serve (a 404). It then asserted that the log was not empty and that no credential header appeared in it. At its default level, Caddy logs no request for a 404 or a 413. The log was not empty only because it held Caddy's startup lines, so it never held a request, and the test passed with the header filter removed.
   - **Fix:** a third proxy now has an upstream that refuses connections. Its 502 is a line that carries the request, headers and all. The test first asserts that this line exists, then that no header is in it (`tests/integration/worker/test_proxy.py:371-390`). That fix is in #44.
3. **Something else stopped the attempt.** The integration test's working directory was `0755` and owned by the CI runner's user, whose uid on GitHub's runners is not 1000 (the plan records it as 1001). The agent worker runs as uid 1000 (`Dockerfile`, `useradd --uid 1000`), so it could not write the directory through any bind. "The session cannot write its read-only working directory" held whether or not the sandbox's read-only bind worked. Where the user running the tests is uid 1000, as on a typical single-user Linux machine, the same test did depend on the bind.
   - **Fix:** the directory is `0777` now, so only the read-only bind keeps the session out (`tests/integration/worker/conftest.py:386-395`). That fix is in #45.

## Guidance

A negative test proves its protection only if the protection is the one thing between the attempt and its success. Check that in two steps.

1. **Remove the protection and watch the test fail.** Before trusting a negative test, delete or weaken the protection it proves: comment out the filter, pass the weaker option, drop the bind. Then run the test. If it still passes, it proves nothing yet. Put the protection back and record in the commit what was checked, as the fix for case 1 in #35 does ("with the sandbox content checks removed, all seven sandbox cases fail").
2. **Name, in the test, what would otherwise stop the attempt, and take it away.** For each of the three causes above:
   - **An earlier assertion:** build the bad input so that every other check passes. Then only the check under test can fail.
   - **Missing evidence:** first assert that the evidence exists. That is the logged line, the response or the file. Only then assert what it must not contain. Make the evidence check specific: the old log test did assert that the log was not empty, and Caddy's startup lines satisfied it. A log with no request in it holds no header.
   - **An unrelated barrier:** remove it explicitly, through permissions, ownership, network, users or log levels, and say so in the fixture's docstring. The `workdir` fixture's docstring says that anyone may write the directory, "so only the sandbox's read-only bind keeps a session from writing there".

The same rule applies to probes that run against real kernels or containers. The seccomp learning below runs its probes under the old profile as well, because a probe that opens a socket there is the proof that it can catch a regression.

## Why This Matters

A negative test that cannot fail is worse than none. It makes the protection look covered, so nobody re-checks it. In this stack, all three would have stayed green through a regression in exactly the protection they were named for: a sandbox turned off, a credential header in the log, or a session writing a directory it should only read. The third case also shows that a test can be real on one machine and empty on another, so passing locally is no evidence for CI.

## When to Apply

- Writing or reviewing any test whose assertion is a refusal, an absence or a "not": `pytest.raises`, `not in logs`, a status that must be an error, a file that must not change.
- Adding a protection whose test runs in a different environment from the author's: other uids, other log levels, other kernels, or CI.
- Refreshing a vendored policy, such as a seccomp profile, a Caddyfile or sandbox settings, whose tests were written against the old one.

## Examples

Before, the log test passed with the filter gone. Neither request is ever logged, and Caddy's startup lines satisfied `assert logs` (from before the fix in #44):

```python
for proxy in proxies.values():
    proxy.send("POST", "/v1/messages", b"x" * (33 * 1024**2), credentials)  # 413
    proxy.send("GET", "/v1/models", headers=credentials)  # 404

    logs = proxy.logs().lower()

    assert logs
    for secret in (TEST_CREDENTIAL, PLACEHOLDER, "x-api-key", "authorization"):
        assert secret not in logs, proxy.container
```

After, the test first proves that the log holds the request, then that no header is in it. This is abridged: the test checks every proxy's log, not only this one's (`tests/integration/worker/test_proxy.py:371-390`):

```python
status, _ = unreachable.send("POST", "/v1/messages", QUICK, credentials)
assert status == 502
errors = [json.loads(line) for line in unreachable.logs().splitlines()
          if '"http.log.error"' in line]
assert [error["request"]["uri"] for error in errors] == ["/v1/messages"]
for secret in (TEST_CREDENTIAL, PLACEHOLDER, "x-api-key", "authorization"):
    assert secret not in unreachable.logs().lower()
```

## Related

- [Seccomp socket filter bypassed by high argument bits and 32-bit socketcall](../security-issues/seccomp-socket-filter-bypassed-by-high-bits-and-32-bit-socketcall.md): its Prevention section applies this rule to seccomp probes.
- [Hatchet's retries=0 does not make a task run at most once](hatchet-retries-zero-is-not-at-most-once.md): its re-run test waits past the engine's 30-second heartbeat window, for the same reason. A check made before the re-queue could happen proves nothing.
