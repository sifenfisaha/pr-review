# Reviewing AI-generated changes

More and more PRs are written partly or wholly by coding agents. Review them to the same standard as any other change, with the same courtesy toward the human who opened them. The difference is where the defects hide. Human mistakes cluster around what the author did not know; generated code fails in ways that look like success: fluent, well-commented, plausibly tested, and wrong in a way nobody has looked at.

`summary.md` reports the signals it found (bot author, `Co-authored-by` trailers naming a tool, "Generated with" in the body or commits). Treat absence of signals as no information.

## Where generated code fails

- **Things that do not exist.** Functions, methods, options, config keys, CLI flags and packages that are plausible but not real, or real in another version or another library. Check every unfamiliar API against the installed version in the worktree (`grep` the dependency's source or docs). Check every new dependency exists under exactly that name on the registry and is the maintained one; registering a hallucinated name is a known attack.
- **Tests that test nothing.** Assertion-free tests, tests that assert the mock was called, tests that re-implement the function and compare it with itself, snapshot tests regenerated to match whatever the code does. Apply the mutation test from the checklist: remove the fix, run the tests, expect red.
- **The second implementation.** A new helper for something the repo already has (a retry wrapper, a slugifier, a date formatter, a config loader). Grep for the operation before accepting the new one.
- **Convention drift.** Error handling, logging, naming, layering and test style that match the model's habits rather than the codebase's. Compare with a neighbouring file that does the same kind of thing.
- **Scope creep and churn.** Unrelated refactors, reformatting, comment rewrites and "improvements" bundled with the requested change. Ask for them to be dropped or split; they hide the real diff.
- **Over-engineering.** Abstractions, options and extension points nobody asked for; defensive code for impossible states; configuration for constants. Prefer the simplest version that solves the stated problem.
- **Swallowed errors.** Broad `try/except` or `catch` blocks that log and continue, added to make something "robust". Each one hides a failure someone will need to see.
- **Security defaults.** Missing authorization on new endpoints, string-built SQL, unsanitised HTML, logging of request bodies, TLS verification disabled in a client "for local development". Walk the Security section of the checklist on any new boundary.
- **Narrating comments and docstrings.** Comments that restate the code line by line, or documentation written confidently for behavior the code does not have. Read the code, then check the comment, not the other way round.
- **Partial understanding of the ticket.** The literal request implemented, the implied requirement missed (the ticket says "add an export button"; the obvious need is that the export respects the user's permissions).
- **Stale or wrong edits.** A fix applied in one of three similar places; a rename that missed a string reference or a template; an import left behind.

## How to review it

1. Ask the human author to explain any part they cannot. Code nobody on the team can account for should not merge, regardless of who or what wrote it. Say this kindly; it is about maintainability, not blame.
2. Spend your time on verification rather than reading: run it, break it, grep for the duplicate, check the API exists. Reading fluent code builds false confidence.
3. Weight the review toward boundaries: inputs, permissions, database writes, external calls, money.
4. Hold the tests to the same standard as the code. A green suite is a claim, not evidence, until you have seen a test fail.
5. Do not lower the bar for communication. A clear, kind, specific review is as valuable to someone using an agent as to anyone else, and it teaches them what to ask the agent for next time.
