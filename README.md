# pr-review

A [Claude Code](https://claude.com/claude-code) skill that reviews pull requests the way a trusted senior engineer does.

Most automated review is a linter with opinions: it reads the diff top to bottom and comments on everything it notices. Senior reviewers work differently. They understand what the change is *for* before they read a line, decide how deep to go from the risk rather than the size, check the code out and read whole files, look for the callers and the changes that are *missing* from the diff, verify a suspicion before writing it down, run the tests when it matters, and then deliver a clear verdict with a few ranked, specific, kindly worded comments. This skill encodes that process, and the judgment behind it, so Claude follows it on every review.

```
/pr-review 412                                    # PR 412 of the repo you are in
/pr-review https://github.com/acme/shop/pull/412  # any PR you can read
/pr-review acme/shop#412 --post                   # review, then post it as one GitHub review with inline comments
/pr-review feature/coupons                        # a branch: its open PR, or a local review against the base
/pr-review                                        # self-review the current branch before opening a PR
/pr-review 412 --draft                            # post as a pending review only you can see and submit
/pr-review 412 --depth deep --base release/2.4
```

Plain language works too: "review PR 412 and tell me if it's safe to merge", "look at this before I open it", "post the comments".

## What a review looks like

```
# Review: Add coupon codes to checkout (acme/shop#412)

**Verdict:** Request changes. Two blocking items, both small; everything else is non-blocking.
**Risk:** Medium. Changes the total every order pays, and adds an admin write path.
**Depth:** standard, leaning deep on total.py and the admin route. Read all 11 files; ran the suite in a worktree.

## Summary
Adds percentage and fixed-amount coupons ... The one thing to fix before anything else is the order of
operations in Cart.total: tax is computed before the discount is subtracted, so every discounted order
over-pays tax ...

## Blocking
1. issue (blocking): src/billing/total.py:88 ... a 100% coupon on a $50 taxable item charges $4.00 ...
2. issue (blocking): src/admin/routes.py:12-18 ... no @require_role("admin"); every other route in this file has one ...

## Should fix / Nits / Questions / Missing from the diff / Tests / Praise / Out of scope
```

The full example, with the reasoning behind each comment, is in [`references/example-review.md`](references/example-review.md).

## How it works

1. **Gather context.** `scripts/pr-context.py` pulls the PR (or the local branch) into a work directory under `~/.cache/pr-review/`: description, linked issues, commits, CI checks, existing review threads, the diff, and a one-screen `summary.md` with size (generated files and lockfiles excluded), risk flags from the paths touched, a suggested review depth, signals of AI authorship, and a grep over the added lines for things worth a second look (secrets, `eval`, disabled TLS verification, skipped tests, suppressed warnings, broad `catch` blocks).
2. **Understand the intent first.** Claude writes down what the change is for and which files it would expect to see, then compares that with the diff. Missing changes (the other call sites, the migration, the permission check, the docs) are the most valuable finding a reviewer makes, and a diff cannot show them.
3. **Calibrate depth to risk.** Docs and dependency bumps get a quick pass. Auth, money, migrations, concurrency, public contracts, infrastructure, large diffs, first-time contributors and AI-generated code get a deep one: threat-model pass, tests run and deliberately broken, a repro for anything suspected.
4. **Read the code, not the diff.** `scripts/pr-worktree.sh` checks the PR head out into a detached worktree (cloning bloblessly if the repository is not on the machine) so the user's own checkout is never touched. Files are read whole, in a deliberate order: tests, then contracts, then core logic along its call path, then the boring config and infra files where outages hide.
5. **Find the blast radius.** `scripts/callers.py` lists the functions, classes and exports whose signature changed or that were removed, and every place the rest of the repository references them.
6. **Verify before writing.** Every candidate finding is checked against the code, the callers or a quick repro. Confirmed findings are reported with the input that triggers them; unproven ones become questions; disproven ones are dropped.
7. **Write the review.** Verdict first, then a summary in the reviewer's own words, then findings by severity with [Conventional Comments](https://conventionalcomments.org) labels, each anchored to `path:line` with a concrete fix. Plus what is missing, what was run, specific praise, and what belongs in a follow-up.
8. **Post only when asked.** `scripts/post-review.py` submits everything as one GitHub review. It validates every inline comment against the PR's current diff (GitHub rejects comments outside hunks), snaps near misses, moves unplaceable ones into the summary, skips duplicates on retry, and supports pending (draft) reviews. Without `--post` or `--draft`, nothing leaves the machine.

The standard for approval is borrowed from Google's engineering practices: approve once the change definitely improves the overall health of the codebase, even if it is not perfect. Style a formatter enforces, personal preference, and work outside the PR never block.

## Install

```bash
git clone https://github.com/sifenfisaha/pr-review.git
cd pr-review && ./install.sh
```

The installer symlinks the checkout into `~/.claude/skills/pr-review`, so `git pull` updates the installed skill. Start a new Claude Code session afterwards; `/pr-review` appears in the skill list. To install by hand, copy or symlink this folder to `~/.claude/skills/pr-review` (or to `.claude/skills/pr-review` inside one project).

Requirements: [GitHub CLI](https://cli.github.com) logged in (`gh auth login`), `git`, `python3` 3.9+. Local branch reviews work without `gh`.

## Layout

```
pr-review/
├── SKILL.md                     the workflow and the judgment: what Claude follows on every review
├── references/
│   ├── checklist.md             the long checklist by concern, with how to check each item
│   ├── comment-style.md         labels, severity, tone, bad-to-good rewrites, suggestion blocks, pushback
│   ├── example-review.md        a complete review to calibrate against, and its review.json
│   ├── stack-notes.md           traps per stack: TS/JS, React/Next, Python, Go, Rust, Java/Kotlin, SQL, Docker/CI/Terraform, shell, mobile
│   ├── ai-generated.md          where AI-written changes fail and how to review them
│   └── posting.md               review.json schema, dry runs, pending reviews, troubleshooting
├── scripts/
│   ├── pr-context.py            gather the PR or local branch into a work directory
│   ├── pr-worktree.sh           check the PR head out into an isolated worktree
│   ├── callers.py               blast radius of changed and removed symbols
│   └── post-review.py           validate and post one GitHub review with inline comments
├── assets/                      the report template and an example post payload
├── evals/                       test cases in the `claude plugin eval` layout
└── install.sh
```

Claude loads `SKILL.md` when the skill triggers and reads the reference files only when a review needs them.

## Scripts on their own

The scripts are plain Python and bash and work outside Claude too.

```bash
scripts/pr-context.py acme/shop#412                 # prints the work directory; read summary.md
scripts/pr-context.py -C ~/code/shop feature/x      # a local branch against its base, from anywhere
scripts/pr-worktree.sh 412 --repo acme/shop         # prints the worktree path; --cleanup removes it
scripts/pr-worktree.sh --branch feature/x           # inside a repo without a GitHub remote: a scratch clone
scripts/callers.py --diff WORK/diff.patch --root WORKTREE [--all]
scripts/post-review.py WORK/review.json --dry-run   # then without --dry-run to post
```

Everything they write lives under `~/.cache/pr-review/` (override with `PR_REVIEW_CACHE`). Delete that directory at any time. When a PR is checked out as a worktree of your own clone, the only traces left in that clone are a ref under `refs/pr-review/` and the worktree registration, both removed by `pr-worktree.sh --cleanup`; a repository without a GitHub remote is never touched at all.

## Testing the skill

`evals/` holds three cases: a real public PR reviewed by URL, a local branch with planted bugs (a paginated user directory shipped as a git bundle: an off-by-one offset, SQL built from a sort parameter, a lost last page, an unbounded page size, tests that catch none of it), and a dependency bump that should get a short, proportionate review. Each has a prompt and graders in the layout `claude plugin eval` reads. To run them from a terminal, copy the folder somewhere outside `~/.claude/skills`, add `.claude-plugin/plugin.json` containing `{"name": "pr-review"}`, and run `claude plugin eval . --allow-tools Write,Edit,Bash --scaffold`. These are billed model runs.

## Sources

The process draws on Google's [engineering practices for code review](https://google.github.io/eng-practices/review/), [Conventional Comments](https://conventionalcomments.org), the GitHub [pull request review API](https://docs.github.com/en/rest/pulls/reviews), and the practice of reviewers who are trusted because their findings are real.

## License

MIT
