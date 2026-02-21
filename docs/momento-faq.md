# Momento — FAQ

## What is Momento?

Momento is a local memory layer for AI coding agents.

When your AI assistant forgets what it was doing after a reset, context overflow, or new session, Momento restores the important parts: what you were building, what decisions were made, and what still needs to be done.

It gives your agent its short-term memory back.

---

## What problem does this solve?

AI coding tools forget.

You hit a context limit.
You restart the session.
You switch machines.
You open a new chat.

Suddenly the agent has no idea what was happening 30 minutes ago.

You end up re-explaining:

- The architecture
- The decisions
- The constraints
- The bug you just fixed

Momento prevents that.

Instead of re-teaching the AI your project state, you restore it in seconds.

---

## How does it help me day to day?

You are 45 minutes into implementing a feature.
You fix a tricky bug.
You refactor two services.
You update three files.

Then the agent loses context.

Without Momento:
You spend 5 to 10 minutes re-explaining everything.

With Momento:
You ask, "What was I working on?"
The agent restores your active task, key decisions, and known gotchas.

You continue immediately.

That is the product.

---

## Is this a chat history viewer?

No.

Momento does not store full transcripts.

It stores:

- Finalized decisions
- Key implementation patterns
- Important bug resolutions
- Your active task checkpoints

It keeps distilled intent, not raw conversation logs.

If you want transcript browsing, that is a different tool.

---

## Does it store my code?

No.

Momento stores reasoning about your code, not the code itself.

Examples:

- We used a server-side Stripe checkout to avoid exposing keys.
- Token refresh must use actor isolation to avoid race conditions.
- Migration v2 is idempotent to prevent double charges.

It stores durable knowledge, not source files.

---

## Does it work with multiple AI tools?

Yes.

Momento is agent-agnostic.

Whether you use Claude Code, Codex, or other compatible agents, Momento works the same way.

Different agents may call it differently, but the memory layer is shared.

---

## What happens if I work in multiple terminals or projects?

Momento organizes memory by project automatically.

If you:

- Run multiple sessions in the same repo
- Work in different folders of a monorepo
- Switch between backend and frontend

Momento keeps everything scoped correctly.

When restoring, it prioritizes the part of the project you are currently in.

You do not have to configure anything.

---

## Is this automatic?

Partially.

Momento does not inject itself into your workflow.

Instead:

- The agent saves checkpoints at natural work boundaries.
- You can say "checkpoint" to force-save.
- On restart or reset, the agent restores context automatically.

It stays quiet unless needed.

---

## Does this slow down my agent?

No.

Restore responses are small and structured.
There is a hard limit on how much is returned.

The goal is clarity, not flooding the model.

---

## Is my data sent anywhere?

No.

Momento runs locally.

It stores a single local database file on your machine.

No cloud. No telemetry. No account required.

---

## What happens if Momento fails?

Nothing breaks.

Worst case, you re-explain your work like you always did.

Momento adds resilience.
It does not add dependency.

---

## How is this different from just using resume?

Some tools let you resume a session.

That restores raw transcript history.

Momento restores structured intent:

- What you were building
- What was decided
- Why it was decided
- What still remains

Resume gives you scrollback.
Momento gives you orientation.

They work together.

---

## Will this turn into a giant messy log store?

No.

Momento avoids storing everything.

It only keeps:

- Checkpoints
- Decisions
- Durable patterns
- Important bug resolutions

Temporary session state expires automatically.

It is memory, not a data lake.

---

## Who is this for?

Developers who:

- Work on non-trivial codebases
- Use AI assistants heavily
- Switch contexts frequently
- Hit context limits
- Get annoyed re-explaining things

If you have ever said, "Wait... what were we doing again?"

This is for you.

---

## What is the core idea in one sentence?

When your AI forgets, Momento remembers.
