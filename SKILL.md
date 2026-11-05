---
name: pr-review
description: Review a pull request, merge request, branch or local diff the way a trusted senior engineer does. It understands the intent first, calibrates depth to risk, checks the code out and reads full files (not just hunks) in a deliberate order, finds the callers and the changes that are missing from the diff, verifies every finding before reporting it, runs the tests when it matters, and delivers a clear verdict with severity-ranked, specific, kindly worded comments. Use this skill whenever the user asks to review, look over, check, critique, audit, approve or merge-check a PR, pull request, MR, branch, commit range or diff; pastes a GitHub PR URL or number; asks "is this safe to merge", "what do you think of this change", "review my changes before I open a PR", "do a code review", or "write (or post) review comments"; or wants a second opinion on a teammate's or an AI-generated change. It can post the finished review to GitHub as inline comments, but only when asked. Not for writing the code, the commit, or the PR description itself.
argument-hint: "[PR number | PR URL | owner/repo#N | branch] [--post | --draft] [--depth quick|standard|deep] [--base <ref>]"
license: MIT
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/pr-context.py *), Bash(bash ${CLAUDE_SKILL_DIR}/scripts/pr-worktree.sh *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/callers.py *), Bash(gh pr view *), Bash(gh pr diff *), Bash(gh pr checks *), Bash(gh issue view *), Bash(gh run view *), Bash(git log *), Bash(git diff *), Bash(git show *), Bash(git blame *), Bash(git grep *)
---

# PR review, the way a senior engineer does it

A review has two jobs that pull against each other: protect the codebase and its users from the change, and help the author ship it. Senior reviewers do both by being precise rather than exhaustive. They find the few things that matter, say them clearly and kindly, and get out of the way. Every false alarm, vague comment or style war costs the author time and spends the reviewer's credibility, so everything below optimises for findings that are real, ranked and actionable.

`${CLAUDE_SKILL_DIR}` below is this skill's own folder (`~/.claude/skills/pr-review` after `install.sh`). Working files go under `~/.cache/pr-review/`, never inside the user's project.

## What you were asked

Arguments: `$ARGUMENTS`

- **Target**: a PR number (`123`), a GitHub URL, `owner/repo#123`, a branch name, or nothing. Nothing means the current branch against its base, which is the self-review-before-opening-a-PR case. A branch name is first looked up as an open PR; if there is none it is reviewed locally.
- **`--post`** publishes the review to GitHub as one review with inline comments. **`--draft`** posts it as a *pending* review that only the user can see and submit from the GitHub UI. Without either flag the review stays in the terminal and the work directory. A posted review is a statement made under the user's name, so never post, approve or request changes unless this request asked for it. "Review PR 42" is not a request to post.
- **`--depth quick|standard|deep`** overrides the risk-based depth below. **`--base <ref>`** sets the base for local reviews.
- Free text shapes the review too: "post the comments", "just tell me if it's safe", "focus on the migration", "be harsh".

## The workflow

### 0. Gather the context

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pr-context.py <target> [--base REF] [--repo OWNER/REPO]
```

For a local or branch review, run it from inside the repository. The last line of output is the work directory. It holds `summary.md` (read this first), `description.md`, `linked-issues.md`, `reading-order.md`, `files.tsv`, `commits.md`, `checks.md`, `discussion.md`, `diff.patch` and `meta.json`. Read `summary.md`, then `description.md` and `linked-issues.md` in full. Skim `discussion.md` so you do not repeat what a human already said, and so a re-review only looks at what changed since the last round.

### 1. Understand the intent before reading any code

Write down, in one or two sentences, what problem the PR solves and the approach it takes. Then, before opening the diff, list the files and kinds of change you would expect for that intent: the data model, the callers, the tests, the docs, the config, the migration, the feature flag, the permission check. Comparing that list with `files.tsv` is how senior reviewers find the most valuable class of bug, the change that is **missing** from the diff. A diff can only show you what the author thought of.

If the description does not let you do this (no why, no what, "misc fixes"), that is itself a finding. Ask for it, and review what you can.

### 2. Decide how deep to go

Risk sets the depth, not line count. `summary.md` suggests a tier from risk flags, size and authorship; apply judgment on top.

| Tier | Typical change | What you do |
| --- | --- | --- |
| **quick** | docs, comments, renames, a dependency bump with a changelog, a config toggle, a one-line fix with a test | Still read every line. Check the one thing that could go wrong: the bump's breaking changes, the default that changed, the toggle's blast radius. Verdict in minutes. |
| **standard** (default) | ordinary features and fixes | Everything below. |
| **deep** | auth, permissions, payments or money, PII, crypto, migrations, concurrency, public API or wire contracts, CI, infra, build scripts, deletion of data, more than ~400 hand-written lines, an external or first-time contributor, AI-generated code without tests | Everything below, plus a threat-model pass (`references/checklist.md`, Security), running and deliberately breaking the tests, a repro for anything you suspect, and a look at the rollout and rollback story. |

Speed is part of quality. A review that arrives a day late costs the team more than a nit you missed, so keep quick-tier reviews quick and never pad them.

### 3. Get the code, not just the diff

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/pr-worktree.sh <N> [--repo OWNER/REPO]      # or: --branch NAME
```

This checks the PR head out into a detached worktree under `~/.cache/pr-review/worktrees/` (making a blobless clone first if the repository is not on this machine), so the user's own checkout is never touched. Re-running it updates the worktree to the PR's current head. The diff hides what matters most: the rest of the function, the callers, how the codebase already solves this elsewhere, and whether the tests would really fail. Open full files in the worktree; do not review from hunks.

**External or first-time contributors.** Before running anything (install, build, tests), read the changes to build scripts, CI workflows, `package.json` scripts, `setup.py`, `build.rs`, Makefiles and lockfiles. Running `npm install` on a PR runs the PR's code.

### 4. Read in a deliberate order

Alphabetical order is how the diff viewer thinks, not how the change works. `reading-order.md` groups the files for you:

1. **Tests first.** They say what the author believes the change does, and reveal what they did not think about.
2. **Contracts**: schemas, migrations, types, interfaces, routes, config shapes, serialized formats. A change here radiates everywhere.
3. **Core logic**, following the call path from the entry point down, not file by file.
4. **Callers and neighbours** outside the diff:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/callers.py --diff <work>/diff.patch --root <worktree>
   ```
   lists the functions, classes and exports whose signature changed or that were removed, and every place the rest of the repository references them. Open those sites. A changed default, a reordered argument or a narrowed return type breaks callers silently.
5. **Config, infra, CI, dependencies.** Most outages come from the boring files.
6. **Docs and comments.** Are they now wrong?

Read deletions as carefully as additions. Removed validation, a dropped `await`, a deleted test case, a narrowed `catch` are easy to scroll past.

### 5. Hunt for what breaks

For each hunk ask: what input, state or timing makes this line wrong? The short list, with the long form and how to check each item in `references/checklist.md`:

- **Correctness**: empty, null, zero, negative, huge; off-by-one; unicode and encoding; time zones, DST, leap days, clock skew; floats for money; ordering assumptions; mutation of shared or passed-in state.
- **Error paths**: the exception, the timeout, the partial failure half-way through a loop or a multi-step write. Swallowed errors, catch-alls, missing cleanup, non-idempotent retries, messages that leak internals or help nobody.
- **Concurrency**: read-then-write races, missing locks or transactions, double processing, deadlocks, unbounded parallelism, forgotten `await`s.
- **Data and migrations**: compatibility with rows, messages, caches and sessions already in flight during a rolling deploy; expand/contract ordering; locks on large tables; missing indexes; irreversible steps; whether the rollback is real.
- **Contracts**: breaking changes to public APIs, events, CLI flags, config keys and serialized formats; versioning; pagination; idempotency keys.
- **Security**: authentication *and* authorization on every new path, deny by default; injection (SQL, shell, path, template, log, header); SSRF; deserialization; secrets or PII in code, fixtures, URLs or logs; new dependencies that exist, are maintained and are the package the author meant.
- **Performance**: N+1 queries, unbounded result sets, work inside loops that belongs outside them, memory held across a stream, allocations on hot paths, cache invalidation.
- **Reliability and operations**: a timeout on every network call, retries with backoff and a cap, a flag or kill switch for risky behavior, logs and metrics that would let someone debug this at 3am, log volume and level.
- **Tests**: would the test fail if the bug were introduced? Does it test behavior or mirror the implementation? Negative cases, boundaries, error paths. Mocks that mock the thing under test. Sleeps, real clocks, network, order dependence.
- **Maintainability**: the simplest design that solves the problem; names that say what things are; a utility that already exists in the repo; dead code; comments that explain why; consistency with how the codebase already does this.

Weight it by tier: on a quick-tier change you glance at this list, on a deep one you walk it per file.

### 6. Verify before you write anything down

Every candidate finding passes this gate: re-read the code with the finding in mind, open the callers or tests that would prove or disprove it, and when it is cheap, reproduce it (run the test, write a three-line script, call the function). Then:

- Confirmed: report it, with the scenario that triggers it.
- Plausible but unproven: report it as a **question**, saying what you checked.
- Disproven: drop it. Do not pad the review.

Senior reviewers are trusted because their findings are real. One confidently wrong "bug" costs more than three missed nits.

### 7. Run things when it matters

In the worktree, when the tier or the change calls for it: the affected tests (or the suite), the type checker, the linter, the build. Read `checks.md` first so you do not repeat what CI already proved and so you know what CI does *not* cover. For risky logic, break it on purpose: revert the fix or flip the condition and confirm a test fails. A suite that stays green when the fix is removed is not testing the fix.

Report exactly what you ran and what happened. If you could not run something, say so instead of implying you did.

### 8. Write the review

Use the structure in `assets/review-template.md` and the voice in `references/comment-style.md`. The shape:

1. **Verdict** first, then **risk**, then two to five sentences that **summarize what the PR does in your own words**. The summary proves you understood the change and lets the author correct you if you did not. If the approach itself is wrong, say so here before any line comment; nobody should polish code that needs a redesign.
2. **Findings by severity**, each anchored to `path:line`, each with what is wrong, the scenario that makes it matter, a concrete fix (a suggestion block when it is a few lines) and how to verify. Label them with Conventional Comments: `issue`, `suggestion`, `question`, `nitpick`, `thought`, `todo`, `chore`, `praise`, adding `(blocking)` or `(non-blocking)` whenever it is not obvious.
3. **Missing from the diff**: the expected changes from step 1 that are absent.
4. **Tests**: what CI says, what you ran, what is not covered.
5. **Praise** for something that genuinely deserves it, named specifically. Never filler.
6. **Out of scope**: things you noticed that belong in a follow-up, so the author is not asked to fix the world in this PR.

Save it as `review.md` in the work directory and show it to the user in full.

### 9. Post only when asked

When the request included `--post`, `--draft` or words to that effect: write `review.json` in the work directory (schema and examples in `references/posting.md`, `repo` and `pr` come from `meta.json`), then

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/post-review.py <work>/review.json --dry-run    # inspect what would be posted
python3 ${CLAUDE_SKILL_DIR}/scripts/post-review.py <work>/review.json              # publish as one review
```

The script checks every inline comment against the PR's current diff (GitHub rejects comments on lines outside it), moves unplaceable ones into the summary with a `path:line` reference, skips comments you already posted, and submits everything as a single review. Use `"event": "PENDING"` for `--draft`. Use `APPROVE` or `REQUEST_CHANGES` only when the user chose that outcome; otherwise post as `COMMENT`.

## Reaching a verdict

The standard, borrowed from Google's engineering practices: **approve once the change definitely improves the overall health of the codebase, even if it is not perfect.** Perfect is not the bar. "Better than before, and nothing in it is a mistake we will regret" is.

- **Approve** when nothing blocking remains. Say "approve with nits" when the remaining comments can be fixed without another look.
- **Request changes** when at least one finding blocks: a correctness bug, a security hole, a data loss or corruption risk, a breaking change without a migration path, risky logic without a test, or an approach that has to change. Lead with the most important one.
- **Comment** when you need an answer before you can decide, when the design needs a conversation, or when you are not confident enough to block.

Things that never block: style the formatter or linter already enforces; a preference where both options are fine (the author's choice stands, consistency with the surrounding code is the tie-breaker); work outside the PR's scope (file a follow-up); perfection. Technical facts and data beat opinions. The project's style guide beats both on style.

## Special situations

**Re-review.** Read `discussion.md` and the new commits only. Check that each earlier blocking comment was addressed in the code, not just answered. Review the delta, and do not raise new non-blocking comments on code you already accepted unless the delta introduced them. Approve promptly when the bar is met; moving the goalposts teaches people to stop asking you.

**The PR is too big.** Above roughly 400 changed lines of hand-written code, review effectiveness drops sharply. If the commits are atomic and tell a story (`commits.md`), review commit by commit. Otherwise review the design of the whole, review the riskiest part line by line, say explicitly which parts you did not read line by line, and suggest a split along natural seams (contract change, then implementation, then call-site migration). Generated files and lockfiles do not count toward size; `summary.md` separates them.

**Self-review (no PR yet).** Same workflow against the local branch, plus a PR-hygiene section: is the title a sentence about the outcome, does the description say why and how to test, is there a screenshot for UI, does the commit history read, is anything unrelated bundled in, is there uncommitted work?

**AI-generated or suspected.** `summary.md` lists the signals (bot author, co-author trailers, tool mentions). Do not grade it differently, but spend the extra minutes where these changes fail. Read `references/ai-generated.md`.

**"Pure refactor" or "no behavior change".** A claim to verify, not a reason to skim. Compare before and after for every branch, default and error path; check that the tests did not change and that the existing ones would catch a behavior change.

## Habits that erode trust

- Commenting on formatting a tool enforces, or restating the linter.
- Twenty nits with the one real bug buried in the middle. Rank, and lead with what matters.
- "This is wrong" without the input that makes it wrong; "consider X" without why.
- Blocking on taste, or on work outside the PR.
- Reviewing the author instead of the code ("you always", "why didn't you"). Ask about the code, assume competence and good intent.
- Rubber-stamping because the author is senior or CI is green.
- Claiming to have run or checked something you did not.
- Posting anything to GitHub the user did not ask for.

## Where to look next

| Need | Read |
| --- | --- |
| The full checklist by concern, with how to check each item | `references/checklist.md` |
| Writing comments: labels, tone, bad-to-good rewrites, suggestion blocks, disagreement | `references/comment-style.md` |
| A complete example review to calibrate tone and depth | `references/example-review.md` |
| Stack-specific traps: TypeScript/JS, React/Next, Python, Go, Rust, Java/Kotlin, SQL and migrations, Docker/CI/Terraform, shell | `references/stack-notes.md` |
| Reviewing AI-generated code | `references/ai-generated.md` |
| Posting to GitHub: `review.json` schema, dry runs, pending reviews, troubleshooting | `references/posting.md` |
