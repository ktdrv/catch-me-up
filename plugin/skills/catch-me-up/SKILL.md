---
name: catch-me-up
description: Narrate what the agent has actually been doing, in plain language, and flag where it drifted from what the user asked for. Use whenever they say "catch me up", "where are we", "what have you been doing", "what just happened", "summarize the last hour", "I'm lost", "did you finish", or otherwise signal they stepped away during a long run of autonomous work and need to re-enter without reading the scrollback. Also use when they ask whether the work still matches their original intent, or whether anything got done that they didn't ask for. Not for explaining a codebase or a concept — this is strictly about reconstructing recent session work from the transcript.
---

# catch-me-up

The user walked away while you worked. Now they're back and have no idea what happened. Give them the session in plain words, in the order it happened, and tell them honestly where you went off the rails.

## The one rule that makes this work

**You do not write the summary. A subagent does.**

You are the worst possible narrator of your own session. You remember what you *meant* to do, your context may already be compacted, and you have every incentive to describe a workaround as a fix. A fresh agent reading the raw transcript has none of that. Your job is to set it up and relay what it says.

Do not skip this because the session felt short or you think you remember it clearly. That feeling is the failure mode.

The output format below comes from a prompt Sam, an engineer at Anthropic, shared in the Claude Code newsletter on 2026-09-19: "narrate each step in the order it actually happens, and bold inline anything in the current PR that has drifted from my most recently stated intent."

## Step 1 — find the transcript

The session id is the UUID in your scratchpad path — if your scratchpad is `/private/tmp/claude-501/-Users-you/0000e1b3-92fc-4d24-89a3-83315d3d96fc/scratchpad`, the session id is `0000e1b3-92fc-4d24-89a3-83315d3d96fc`.

The project directory is `~/.claude/projects/<cwd with every / replaced by ->`. For `/Users/you/repo` that's `~/.claude/projects/-Users-you-repo`.

If you can't work out the session id, omit `--session` and the script takes the most recently modified transcript in that directory — correct in practice, because the live session is the one being appended to right now.

## Step 2 — extract the timeline

```bash
uv run --no-project ~/.claude/skills/catch-me-up/transcript.py \
  --project-dir ~/.claude/projects/<slug> --session <uuid>
```

It prints every instruction the user gave this session, then the ordered action log since the anchor — the instruction that began the longest unbroken stretch of agent-only activity, which is the span they weren't watching. If that stretch was launched by a bare "yes", it backs up to the instruction the yes was approving.

**Check the anchor before you trust it.** If the numbered list shows the anchor is a mid-task correction rather than the start of the task, re-run with `--from N` pointing at the instruction that actually began the work. `--all` covers the whole session. Do this yourself; don't make the subagent guess.

Don't read the output. Pipe it to a file in your scratchpad and hand over the path.

```bash
uv run --no-project ~/.claude/skills/catch-me-up/transcript.py ... > "$SCRATCH/timeline.md"
```

## Step 3 — dispatch the narrator

One subagent, **model: sonnet**, `subagent_type: general-purpose`. It gets the file path and the brief below and nothing else from your session — no summary of what you think happened, no framing, no defense. Contaminating it defeats the point.

Fill in the placeholder and send it verbatim:

```
Read <SCRATCH>/timeline.md. It is a reconstruction of a Claude Code session: every
instruction the user gave, then the ordered log of what the agent actually did.

The user stepped away during this work and is coming back cold. Write them a catch-up.

First, establish ground truth about the files:

1. The "Files this session wrote" list is the ONLY set of files this session touched.
   Never run a bare `git status` or `git diff` — the user may run several Claude
   sessions at once, and an unscoped git command reports other sessions' work as
   this one's.
2. In a git repo, scope every command to that set: `git diff --stat -- <paths>`,
   `git status --porcelain -- <paths>`. Outside a repo, read the files directly.
3. If a file in the set has changes the log doesn't account for, say so as its own
   line: something else is editing it. Do not fold it into the narration.

Then write, in this shape and nothing more:

**What you asked for** — one sentence, their intent in your own words.

**What happened** — numbered, one line each, in the order it actually happened.
Ten lines maximum; collapse a long boring stretch into one line ("spent a while
getting the test harness to run"). Plain English throughout. Say "read the config"
not "called Read on". Never name a tool. Skip the false starts that led nowhere
unless one cost real time or left something behind.

Lead each line with what the software now does differently, then where. Give them
the path — `fetch.ts:88` — when the change is one they might want to eyeball:
tricky, hacky, or foundational. Leave it off small obvious edits; they have git
for those.

They know what the project is for and roughly how it is shaped. They do not know
its files, its function names, or any decision made during this session — they
weren't in it. Introduce a name the first time you use it ("the retry wrapper,
which sits between the scraper and the portal"), then lean on it freely. A line
that avoids internal names still reads fine to someone who knows them; one that
assumes them loses someone who doesn't, at that word.

**Bold inline, right where it happened**, anything that drifted from their stated
intent. Do not collect drift in a section at the bottom; they need to see it at the
step where it happened. Bold it when the agent:
  - added scope they didn't ask for
  - made a call that was theirs to make
  - shipped a workaround where they asked for a root cause
  - re-introduced something they'd explicitly ruled out earlier in the session
  - broke a rule in their CLAUDE.md
  - said something was done, fixed, passing, or working without running the thing
    that proves it — check the log for the claim and for a corresponding command

**Where it stands** — three short lines: what's actually done, what's half-finished,
what's broken or unverified right now.

**Worth a look** — at most three bullets, only if they exist: decisions waiting on
them, things you'd want a second opinion on, files another session is also editing.
Omit the whole section if there's nothing. Do not pad it.

Rules: no preamble, no "great question", no restating these instructions. Be blunt
about the agent's mistakes — you are not it and you owe it nothing. If the log shows
the work genuinely matched their intent, say so in one line rather than
manufacturing drift to look thorough.
```

## Step 4 — relay it

Print what came back, near-verbatim. Tighten obvious padding; do not soften a drift call, do not add context defending a decision it flagged, do not append your own summary. If you disagree with a finding, say so in one line *after* the summary and let them judge.

If the agent flagged something as unverified and you can verify it in one command, run it and say what happened. That's more useful than arguing.

## When not to use this

- They're asking what some code does → that's not this skill.
- The session is two exchanges old and they were watching → just answer them.
- They ask for a catch-up on a *different* session → same flow, but find that session's UUID by listing the project directory by mtime and confirm which one they mean before narrating.
