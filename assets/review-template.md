# Review: <PR title> (<owner/repo>#<N>)

**Verdict:** Approve | Approve with nits | Request changes | Comment
**Risk:** Low | Medium | High. <one clause on why: what it touches, who it affects>
**Depth:** quick | standard | deep. <what you read line by line, what you skimmed, what you ran>

## Summary

<Two to five sentences, in your own words: the problem, the approach, whether the approach fits the codebase, and the one thing the author most needs to hear. If the design needs to change, say it here, before any line comment.>

## Blocking

<Each item: label, `path:line`, what is wrong, the scenario that triggers it, the fix, how to verify. Omit the section if empty, and say so in the verdict.>

1. **issue (blocking):** `src/billing/total.py:88` ...

## Should fix

<Non-blocking but important: correctness edges, missing tests for risky logic, maintainability traps the next person will hit.>

## Nits

<Optional, non-blocking, batched. Never about things a formatter enforces.>

## Questions

<Things you could not settle from the code. Say what you checked.>

## Missing from the diff

<Changes you expected for this intent that are not here: callers, docs, migration, config, flag, tests, permission check, other call sites, i18n.>

## Tests

<CI status from `checks.md`. What you ran, with the exact command and outcome. What is not covered. Whether breaking the fix made a test fail.>

## Praise

<One or two specific things done well. Omit rather than invent.>

## Out of scope

<Pre-existing problems you noticed that belong in a follow-up issue, so this PR is not held hostage to them.>
