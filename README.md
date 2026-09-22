# catch-me-up

Narrates the stretch of a coding session you weren't watching, and marks inline where the work drifted from what you asked for.

Output looks like this:

```
**What you asked for:** move the HA token out of the dotfile.

**What happened**
1. Found the token in ~/.zshrc:61 and checked what reads it: two homelab scripts
   and the Taskfile.
2. **Reported it was in git history and in claude-mem. Both wrong.** Matched on a
   shared JWT header prefix, not the token itself.
3. Stored it in the login Keychain and verified the round-trip by hash.
4. Rewrote ~/.zshrc without it. **Used Write rather than Edit**, which wasn't asked
   for, but avoided re-exposing the token in the tool call.

**Where it stands**
Done: token in Keychain, .zshrc clean, Taskfile updated.
Unverified: nothing.
Broken: nothing.
```

## Why it isn't just a summarizer

**It finds the stretch you weren't watching.** Not the whole session, not the last N messages. It takes the longest unbroken run of agent-only activity, which is by definition the part you missed. If that run started with a bare "yes", it walks back to the instruction the "yes" was approving, because that's what you actually asked for.

No other tool does this. They summarize a unit picked in advance: the whole session, the last turn, the day, the branch diff.

**The agent doesn't narrate itself.** The skill forbids it and dispatches a subagent that sees only the extracted timeline, nothing from the parent's context. An agent is the worst possible narrator of its own session: its context may already be compacted, it remembers what it *meant* to do, and it has every incentive to call a workaround a fix. A better model shortens the account without making it reliable. Claude Code's built-in `/recap` generates in the running session's own context, which is the same problem.

**It reports drift, not just events.** The narrator marks, inline and at the step where it happened, anything that diverged from your stated intent: scope you didn't ask for, a call that was yours to make, a workaround where you asked for a root cause, a claim that something passed without a command that proves it.

## Credit

This exists because of a prompt Sam, an engineer at Anthropic, shared in the Claude Code newsletter on 2026-09-19:

> After a long session I want to see the decisions Claude made along the way, not re-read the whole thread. So I ask: *In your own words, without jargon, narrate each step in the order it actually happens, and bold inline anything in the current PR that has drifted from my most recently stated intent.*

That is the output format, and it was already right. Plain language, chronological, drift bolded where it happened rather than collected in a section at the bottom. The narrator brief in `SKILL.md` is that prompt, expanded.

What's added here is the part a prompt can't do for you: working out which stretch of the session to narrate, and handing it to an agent that didn't do the work. Sam's version asks the session about itself, which is fine when you were watching. It's the wrong move when you weren't.

## Install

As a plugin:

```
/plugin marketplace add ktdrv/catch-me-up
/plugin install catch-me-up@catch-me-up
```

Or drop the skill in by hand:

```bash
git clone https://github.com/ktdrv/catch-me-up
cp -R catch-me-up/plugin/skills/catch-me-up ~/.claude/skills/
```

Needs [uv](https://docs.astral.sh/uv/). The script declares its own dependency inline, so there's nothing to install.

## Use

Say "catch me up", "where are we", "what did you just do", or "I'm lost". The skill does the rest.

Directly, if you want the raw timeline:

```bash
uv run --no-project ~/.claude/skills/catch-me-up/transcript.py --project myrepo
```

| Flag | |
|---|---|
| `--session <uuid>` | a specific session; defaults to the most recently written |
| `--project <substr>` | disambiguate by project path |
| `--provider <name>` | which harness's transcripts to read (default `claude`) |
| `--from N` | anchor on instruction N instead of the detected one |
| `--all` | whole session |
| `--limit N` | per-message truncation (default 600) |

It prints the numbered instruction list first, so if the detected anchor is a mid-task correction rather than the real start, you can see that and re-run with `--from`.

## Design notes

**It doesn't parse JSONL.** Reading and validating transcripts is [`claude-code-log`](https://github.com/daaain/claude-code-log)'s job. Claude Code's transcript format is internal and changes between releases, so owning a parser here would be a standing maintenance tax for no differentiation. Delegating also buys session discovery across providers and automatic loading of subagent transcripts, both of which came free.

What this repo owns is about 200 lines: the anchor algorithm, the tool-call-to-plain-English mapping, and the narrator brief.

**Read-only tool calls collapse.** Forty `Read`s become `explored (Read x40)`. The log is for a human-facing narrative, not an audit trail.

**Subagent internals are dropped**, but the dispatch is logged. You want to know it delegated, not what the delegate's inner monologue was.

## Limitations

- Claude Code's transcript format is internal. `claude-code-log` tracks it, but a release can still break things for a day.
- Anchor detection assumes the longest silent stretch is the one you missed. If you were watching intently for an hour and then stepped away for five minutes, it picks the hour. `--from` overrides.
- The narrator is a language model reading a log. It can miss drift, and it can invent drift. Treat a clean report as weak evidence, not proof.

## Licence

MIT.
