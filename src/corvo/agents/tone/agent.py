"""An agent with no tools, the example to copy for a new one.

The agent turns a ToneInput into a ToneOutput through one Claude session. It
is written with the Claude Agent SDK's own API: corvo puts no layer between
an agent and its SDK, so an agent on another SDK uses that SDK's own API.

An agent package holds agent.py, which builds the options and runs the
session; models.py, which the worker imports and which never imports the
SDK; prompts/, the prompt text files; and tools.py when the agent has custom
tools. The agent's run takes its input model and the Session the agent
worker supplies, and returns its output with the session's RunReport.

The session supplies the isolation the agent does not own, and run passes
each value under the SDK's own name:

- cli_path is corvo-agent-sandbox, which starts the engine in a bubblewrap
  of its own, with an empty environment, in the run's cgroup. It sets the
  variables that turn off auto memory, CLAUDE.md files and nonessential
  traffic.
- cwd is the run's working directory, None for an agent without one.
- env holds the wrapper's per-run values and the credential's placeholder;
  the real credential stays in the proxy.
- sandbox turns on the SDK's sandbox for commands, never lets one run
  outside it, and fails the run where it cannot start. The wrapper refuses
  a session without it.
- stderr and log send the engine's lines and the session ID to the run log.

The agent sets the options it owns, each for a reason:

- tools lists the built-ins the agent uses, [] for none: without it the
  CLI offers every built-in, and permission rules alone still let some run.
- allowed_tools lists every tool the agent may call, and
  permission_mode="dontAsk" denies every other call.
- setting_sources=[] and skills=[] load no settings, CLAUDE.md or skills,
  from the host or from the working directory, and strict_mcp_config=True
  loads no MCP server but the agent's own.
- model, max_turns and max_budget_usd are the agent's own declarations.

tests/agents/isolation.py checks both halves in each agent's tests.

The run succeeds only on a result whose structured output validates against
the verdict's schema: corvo.agents.session.consume applies that rule.
Decisions on the output belong in the core twin, corvo.core.agents.tone,
which never imports an SDK; the agent only adapts them to the SDK.
"""

from importlib.resources import files

from claude_agent_sdk import ClaudeAgentOptions, query

from corvo.agents.report import RunReport
from corvo.agents.session import Session, consume
from corvo.agents.tone.models import ToneInput, ToneOutput, ToneVerdict
from corvo.core.agents.tone import is_friendly

MODEL = "claude-haiku-5-5"
MAX_TURNS = 3
MAX_BUDGET_USD = 0.05

SYSTEM_PROMPT = (files("corvo.agents.tone") / "prompts" / "system.md").read_text()


async def run(input: ToneInput, session: Session) -> tuple[ToneOutput, RunReport]:
    options = ClaudeAgentOptions(
        cli_path=session.cli_path,
        cwd=session.cwd,
        env=session.env,
        sandbox=session.sandbox,
        stderr=session.stderr,
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        allowed_tools=[],
        permission_mode="dontAsk",
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        output_format={
            "type": "json_schema",
            "schema": ToneVerdict.model_json_schema(),
        },
    )
    verdict, report = await consume(
        query(prompt=input.text, options=options), ToneVerdict, session.log
    )
    return ToneOutput(tone=verdict.tone, friendly=is_friendly(verdict.tone)), report
