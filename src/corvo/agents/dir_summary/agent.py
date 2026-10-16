"""An agent that works in a directory, with a custom tool: the example to
copy for one.

The agent summarizes the files of the working directory its run is given,
and counts the summary's words with its custom tool, count_words. It
follows corvo.agents.tone.agent, whose header holds the rules every agent
keeps; this header adds what a working directory and a custom tool change.

The working directory:

- The caller names it relative to <root>/workdirs, the workdirs directory
  under CORVO_AGENT_ROOT, and the task refuses any other before a session
  starts. The session piece hands it to run as session.cwd, and the session
  sees it read-only unless models.WRITES_WORKDIR says the agent writes.
- The caller creates it, readable by the agent worker's uid 1000, and
  deletes it afterwards. It keeps credentials out of it, such as a token in
  .git/config: the session reads everything there.
- tools lists the file tools the agent uses. Reads inside the working
  directory need no rule, and permission_mode="dontAsk" denies every read
  outside it. allowed_tools may say so again, as a Read rule scoped to the
  directory; it never names the tools bare, which would allow reads
  anywhere. A Read rule covers Glob and Grep too.
- A CLAUDE.md, a .claude/ directory or skills in the working directory are
  content like any other file: setting_sources=[] and skills=[] load none.

The custom tool lives in tools.py, whose header carries the rules a tool
keeps. run serves it from a new in-process MCP server each session, and
allows it by its mcp__<server>__<tool> name.
"""

from importlib.resources import files

from claude_agent_sdk import ClaudeAgentOptions, query

from corvo.agents.dir_summary import tools
from corvo.agents.dir_summary.models import DirSummaryInput, DirSummaryOutput
from corvo.agents.report import RunReport
from corvo.agents.session import Session, consume

MODEL = "claude-haiku-5-5"
MAX_TURNS = 15
MAX_BUDGET_USD = 0.25

PROMPTS = files("corvo.agents.dir_summary") / "prompts"
SYSTEM_PROMPT = (PROMPTS / "system.md").read_text()
REQUEST = (PROMPTS / "request.md").read_text()


async def run(
    input: DirSummaryInput, session: Session
) -> tuple[DirSummaryOutput, RunReport]:
    options = ClaudeAgentOptions(
        cli_path=session.cli_path,
        cwd=session.cwd,
        env=session.env,
        sandbox=session.sandbox,
        stderr=session.stderr,
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=["Read", "Glob", "Grep"],
        allowed_tools=[f"Read(/{session.cwd}/**)", *tools.ALLOWED],
        mcp_servers={tools.SERVER: tools.server()},
        permission_mode="dontAsk",
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        output_format={
            "type": "json_schema",
            "schema": DirSummaryOutput.model_json_schema(),
        },
    )
    return await consume(
        query(prompt=REQUEST, options=options), DirSummaryOutput, session.log
    )
