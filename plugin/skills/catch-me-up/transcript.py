# /// script
# requires-python = ">=3.11"
# dependencies = ["claude-code-log>=1.6.0"]
# ///
"""Extract an intent timeline and an action log from an agent session transcript.

Feeds the catch-me-up skill. Output is markdown on stdout, sized for a subagent
to read in one go: user prompts verbatim-ish, assistant claims, and tool calls
with read-only runs collapsed.

Reading and validating the transcript is claude-code-log's job, not ours. Its
format is internal to Claude Code and changes between releases, so owning a
parser here would be a standing maintenance tax. Delegating also buys session
discovery across providers and automatic loading of subagent transcripts.

What this file owns is the part nobody else does: finding the stretch the user
wasn't watching, and rendering it for a narrator that wasn't there either.
"""

import argparse
import contextlib
import io
import json
import re
import sys

from claude_code_log import discovery, parser

# Bare approvals. The anchor walks back past these to the last stated intent.
APPROVAL = re.compile(
    r"^(y|yes|yep|yeah|ok|okay|sure|go|go ahead|do it|proceed|continue|"
    r"sounds good|lgtm|ship it|please|thanks|ty|k|\+1)[.!]?$",
    re.I,
)
READ_ONLY = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "ToolSearch",
             "NotebookRead", "BashOutput", "ListAgents"}
WRITES = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
SKIP_TOOLS = {"TodoWrite"}


def clean_prompt(text: str) -> str:
    """Strip the wrappers the harness injects into user turns."""
    for pattern in (
        r"<system-reminder>.*?</system-reminder>",
        r"<local-command-(?:stdout|stderr)>.*?</local-command-\w+>",
        r"<command-(?:name|message|args)>.*?</command-\w+>",
        r"<local-command-caveat>.*?</local-command-caveat>",
        r"<user-prompt-submit-hook>.*?</user-prompt-submit-hook>",
        # Harness machinery that arrives on a user turn but nobody typed.
        r"<task-notification>.*?</task-notification>",
        r"<agent-message\b.*?</agent-message>",
        r"\[SYSTEM NOTIFICATION[^\]]*\]",
    ):
        text = re.sub(pattern, "", text, flags=re.S)
    text = text.strip()
    # An unclosed machinery block survives the substitutions above. Nobody typed it.
    machinery = r"<(task-notification|agent-message|system-reminder|local-command|command-)"
    return "" if re.match(machinery, text) else text


@contextlib.contextmanager
def quiet():
    """claude-code-log narrates its loading to stdout; our stdout is the payload."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


def find_session(session: str | None, provider: str, project: str | None):
    """Pick the session to narrate.

    Without --session, take the most recently written transcript, optionally
    filtered to a project. That is the live session, because it is the one being
    appended to right now.
    """
    with quiet():
        found = [s for s in discovery.discover_all_sessions() if s.provider == provider]
    if session:
        match = [s for s in found if s.session_id == session]
        if not match:
            sys.exit(f"no {provider} session {session}")
        return match[0]
    if project:
        # project_path is the transcript directory, whose name is the cwd with every
        # non-alphanumeric turned into "-". Slug the argument so a real path matches.
        # A full path must match the whole name: worktrees get "<repo>--claude-
        # worktrees-..." directories, and a substring match would pick their sessions.
        slug = re.sub(r"[^A-Za-z0-9]", "-", project)
        if project.startswith("/"):
            found = [s for s in found if s.project_path and s.project_path.name == slug]
        else:
            found = [s for s in found if s.project_path and slug in str(s.project_path)]
    if not found:
        sys.exit(f"no {provider} sessions found"
                 + (f" for project matching {project!r}" if project else ""))
    # discover_all_sessions leaves updated_at and source_path unset, so sort on the
    # file itself. For claude, project_path is the transcript directory. Without
    # this every mtime was 0 and the pick fell to discovery order, not the live one.
    def mtime(s) -> float:
        path = s.source_path or (s.project_path and s.project_path / f"{s.session_id}.jsonl")
        return path.stat().st_mtime if path and path.exists() else 0

    found.sort(key=mtime)
    return found[-1]


def describe(name: str, params: dict) -> str | None:
    """One line per tool call. None means drop it from the log."""
    if name in SKIP_TOOLS:
        return None
    if name in WRITES:
        return f"WROTE {params.get('file_path', '?')}"
    if name == "Bash":
        return f"RAN {params.get('command', '?')[:220]}"
    if name in ("Agent", "Task"):
        return (f"DISPATCHED subagent ({params.get('subagent_type', 'general')}): "
                f"{params.get('description', '?')}")
    if name == "Skill":
        return f"INVOKED skill {params.get('skill', '?')}"
    if name == "AskUserQuestion":
        asks = "; ".join(q.get("question", "?") for q in params.get("questions") or [])
        return f"ASKED YOU: {asks[:220]}"
    blob = json.dumps(params, default=str)[:120]
    return f"{name} {blob}"


def events(entries: list) -> list[dict]:
    """Ordered, flattened stream: prompts, decisions, assistant claims, tool calls."""
    out: list[dict] = []
    asked: set[str] = set()  # tool_use ids for questions put to the user
    for entry in entries:
        record = entry.model_dump()
        if record.get("isSidechain"):
            continue  # subagent internals; the dispatch itself is logged below
        kind = record.get("type")
        ts = str(record.get("timestamp") or "")
        content = getattr(getattr(entry, "message", None), "content", None)
        blocks = content if isinstance(content, list) else []

        if kind == "user" and not record.get("isMeta"):
            # A reply to AskUserQuestion is stated intent too, not a tool result.
            for block in blocks:
                if (getattr(block, "type", None) == "tool_result"
                        and getattr(block, "tool_use_id", None) in asked):
                    answer = getattr(block, "content", None)
                    text = (parser.extract_text_content(answer)
                            if isinstance(answer, list) else str(answer or ""))
                    out.append({"kind": "decided", "ts": ts, "body": text.strip()})
            body = clean_prompt(parser.extract_text_content(blocks))
            if body:
                out.append({"kind": "prompt", "ts": ts, "body": body})

        elif kind == "assistant":
            for block in blocks:
                btype = getattr(block, "type", None)
                if btype == "text":
                    said = (getattr(block, "text", "") or "").strip()
                    if said:
                        out.append({"kind": "said", "ts": ts, "body": said})
                elif btype == "tool_use":
                    name = getattr(block, "name", "?")
                    if name in ("AskUserQuestion", "ExitPlanMode"):
                        asked.add(getattr(block, "id", "") or "")
                    line = describe(name, getattr(block, "input", None) or {})
                    if line:
                        out.append({"kind": "tool", "ts": ts, "name": name, "body": line})
    return out


def anchor_index(stream: list[dict]) -> int:
    """Index of the instruction that began the stretch the user wasn't watching.

    A catch-up covers work done while they were away, so the boundary is the start
    of the longest unbroken run of agent activity — the span where they said
    nothing. Then back up past bare approvals: "yes" launched the run, but the
    instruction before it is what they actually asked for.
    """
    prompts = [i for i, e in enumerate(stream) if e["kind"] == "prompt"]
    if not prompts:
        return 0
    spans = list(zip(prompts, prompts[1:] + [len(stream)]))
    start = max(spans, key=lambda s: s[1] - s[0])[0]
    while APPROVAL.match(stream[start]["body"]):
        earlier = [i for i in prompts if i < start]
        if not earlier:
            break
        start = earlier[-1]
    return start


def render(stream: list[dict], start: int, limit: int) -> str:
    lines, pending = [], []

    def flush() -> None:
        if pending:
            tally = ", ".join(f"{n}x{pending.count(n)}" for n in sorted(set(pending)))
            lines.append(f"- explored ({tally})")
            pending.clear()

    for event in stream[start:]:
        if event["kind"] == "tool" and event["name"] in READ_ONLY:
            pending.append(event["name"])
            continue
        flush()
        if event["kind"] == "prompt":
            lines.append(f"\n**[you, {event['ts'][11:16]}]** {event['body'][:limit]}\n")
        elif event["kind"] == "decided":
            lines.append(f"- YOU CHOSE: {event['body'][:limit]}")
        elif event["kind"] == "said":
            lines.append(f"- CLAIMED: {event['body'][:limit]}")
        else:
            lines.append(f"- {event['body']}")
    flush()
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract the stretch of a session the user wasn't watching.")
    ap.add_argument("--session", help="session uuid; defaults to the newest transcript")
    ap.add_argument("--provider", default="claude",
                    help="harness whose transcripts to read (default: claude)")
    ap.add_argument("--project", help="project directory, or part of its path, to disambiguate")
    ap.add_argument("--all", action="store_true",
                    help="whole session, not just since the anchor")
    ap.add_argument("--from", dest="start_at", type=int, metavar="N",
                    help="anchor on instruction N from the list instead")
    ap.add_argument("--limit", type=int, default=600, help="per-message truncation")
    args = ap.parse_args()

    info = find_session(args.session, args.provider, args.project)
    with quiet():
        entries = list(discovery.load_session(args.provider, info.session_id))
    stream = events(entries)
    if not stream:
        sys.exit(f"no readable turns in session {info.session_id}")

    prompts = [i for i, e in enumerate(stream) if e["kind"] == "prompt"]
    print(f"# Session {info.session_id}")
    if info.project_path:
        print(f"\n_{info.project_path}_")

    print("\n## Instructions given this session\n")
    for n, i in enumerate(prompts, 1):
        print(f"{n}. {stream[i]['body'][:200]}")

    if args.all:
        start = 0
    elif args.start_at is not None:
        if not 1 <= args.start_at <= len(prompts):
            sys.exit(f"--from must be between 1 and {len(prompts)}")
        start = prompts[args.start_at - 1]
    else:
        start = anchor_index(stream)

    anchored = sum(1 for i in prompts if i <= start)
    print(f"\n## Action log (from instruction {anchored})\n")
    print(render(stream, start, args.limit))

    wrote = sorted({e["body"][6:] for e in stream[start:]
                    if e["kind"] == "tool" and e["body"].startswith("WROTE ")})
    if wrote:
        print("\n## Files this session wrote\n")
        for path in wrote:
            print(f"- {path}")


if __name__ == "__main__":
    main()
