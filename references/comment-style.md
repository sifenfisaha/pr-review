# Writing review comments

The goal of a comment is to get a specific change made, or a specific question answered, by someone who is busy, possibly less experienced, and possibly defensive, while leaving them glad you reviewed. Everything below follows from that.

Contents

1. Anatomy of a good comment
2. Labels and severity (Conventional Comments)
3. Tone: review the code, not the author
4. Rewrites: from bad to good
5. Suggestion blocks
6. Questions versus assertions
7. Praise
8. The summary comment
9. Disagreement and pushback
10. Re-reviews
11. What not to comment on

---

## 1. Anatomy of a good comment

Four parts, usually in this order, usually in two to five sentences:

1. **Label and location.** `issue (blocking):` plus the line it is attached to. In a terminal report, `path:line`.
2. **What is wrong, concretely.** Not "this is incorrect" but "when `items` is empty, `items[0]` on this line raises".
3. **Why it matters.** The scenario, the user who hits it, the consequence. This is what turns a nit into a priority or a priority into a nit, and it is what the author learns from.
4. **A way forward.** A concrete fix, a suggestion block, a pointer to how the codebase does it elsewhere, or a question that would unblock. Leave room for the author to find a better fix than yours.

Optionally: how to verify (a test case, a command), and a reference (doc link, the existing helper).

One concern per comment. Two problems on one line are two comments, so each can be resolved on its own.

## 2. Labels and severity

Use the Conventional Comments vocabulary (conventionalcomments.org). The label does the triage so the author can plan their response before reading the prose.

| Label | Meaning | Blocking by default? |
| --- | --- | --- |
| `issue` | Something is wrong: a bug, a security hole, a broken contract. Say what input triggers it. | Yes |
| `suggestion` | A concrete improvement. Say why it is better. | No, unless decorated |
| `question` | You do not understand, or you suspect but cannot confirm. Say what you checked. | Needs an answer |
| `todo` | A small, necessary change (rename, missing null check, missing test). | Yes, but quick |
| `chore` | Process housekeeping before merge: changelog entry, docs update, ticket link. | Yes, but quick |
| `nitpick` | Trivial, preference-level. Batch them, never block on them. | No |
| `thought` | An idea, context or a possible future direction. No action required. | No |
| `note` | Information the author or future readers should have. | No |
| `praise` | Something done well. Be specific. | No |
| `typo` | A spelling or wording fix. | No |

Decorations in parentheses: `(blocking)`, `(non-blocking)`, `(if-minor)`. Add one whenever the default could be misread. `suggestion (blocking):` for an improvement you will not approve without; `issue (non-blocking):` for a real bug that is pre-existing or out of scope.

In the terminal report, group by severity (Blocking, Should fix, Nits, Questions) *and* label each item, so both the structure and the individual comments carry the triage.

## 3. Tone: review the code, not the author

- Talk about the code: "this branch returns `None` when" not "you return `None` when". It is a small shift that removes most of the sting.
- Assume competence and good intent. The author had reasons; ask for them before assuming they did not think of something.
- No sarcasm, no "obviously", no "just", no "simply", no "why didn't you". These words cost nothing to remove and a lot to leave in.
- Be direct about problems and warm about people. Softening the finding ("maybe we could possibly consider") hides the severity; softening the delivery ("I think this will break when", "one thing I noticed") does not.
- Explain, do not decree. "Use X" teaches nothing; "X handles the retry budget for us, so callers cannot accidentally stack retries" does. Explaining why also lets the author tell you when you are wrong.
- Match effort to severity. A paragraph on a nit signals the wrong priority. A one-liner on a security hole does too.
- Write for the third reader. Comments are read later by people debugging, by new hires learning the codebase, and by the author on a bad day. Would you be comfortable with all three?

## 4. Rewrites: from bad to good

**Bad:** "This is wrong."
**Good:** "**issue (blocking):** `tax` is computed from `subtotal` on line 84, before the discount is applied here, so a 100% coupon still charges tax on the full price. Compute it from the discounted amount; a test with a 100% coupon on a taxable item would pin this."

**Bad:** "Why didn't you use the retry helper?"
**Good:** "**question:** Is there a reason to hand-roll the retry here instead of `utils/retry.ts`? It already does jittered backoff and respects the request deadline. If it is missing something you need, extending it would keep the behavior in one place."

**Bad:** "Nit: rename."
**Good:** "**nitpick (non-blocking):** `data` is used for the next 30 lines; `invoices` would let the reader skip the scroll back up."

**Bad:** "Needs tests."
**Good:** "**todo:** The new `else` branch on line 57 (expired coupon) has no test. `test_cart.py` has the fixtures for it; a case that applies an expired code and asserts the total is unchanged and the error is `CouponExpired` would cover it."

**Bad:** "This will be slow."
**Good:** "**issue:** `order.customer` inside this loop triggers one query per order; on the invoices page that is one query per row (I counted 51 for the fixture dataset with `django-debug-toolbar`). `select_related('customer')` on the queryset in line 12 brings it to one."

**Bad:** "Security issue here."
**Good:** "**issue (blocking):** `filename` comes straight from the upload and is joined onto `UPLOAD_DIR`, so `../../etc/cron.d/x` escapes the directory. Use `os.path.basename` and then `secure_filename` as `attachments.py:40` does, or store under a generated name."

**Bad:** "I would have done this differently."
**Good:** "**thought (non-blocking):** This works. For what it is worth, the strategy pattern here could be a dict of callables since none of the strategies hold state; not asking for a change, just noting it in case you touch this again."

**Bad:** "LGTM"
**Good:** "Approve. Read the model, service and tests in full and ran the suite in a worktree (42 passed). The two nits inline are take-it-or-leave-it. Nice use of the existing `Money` type instead of raw decimals."

## 5. Suggestion blocks

When the fix is a few lines and you are confident, write it as a GitHub suggestion so the author can apply it in one click:

````markdown
**issue (blocking):** `start` can be `None` here when the range is open-ended.

```suggestion
    if start is not None and start > end:
        raise ValueError("start must not be after end")
```
````

Rules: the block replaces exactly the lines the comment is attached to (use `start_line` and `line` for a range when posting), it compiles in your head, it follows the file's indentation, and it is not used for anything the author needs to think about. A suggestion is an offer, not an instruction.

## 6. Questions versus assertions

Assert when you have verified: you read the callers, ran the test, reproduced the input. Ask when you have not, and say what you checked so the author does not repeat your work:

> **question:** Can `user.email` be `None` here? The column is nullable in `0012_users.py`, but every caller I found (`signup.py`, `admin/users.py`) sets it. If it can, this `.lower()` raises.

A question that is really an assertion in disguise ("Did you consider that this is broken?") is worse than either. If you know, say so.

## 7. Praise

One genuinely deserved, specific piece of praise per review is worth more than five "nice". It tells the author which instincts to keep, it tells the third reader what good looks like here, and it makes the critical comments land as what they are: a colleague's help, not an attack.

Praise the decision, not the person: "Splitting the migration from the backfill means we can ship the schema tonight and run the backfill in business hours" rather than "great job". Never invent praise; an empty praise section is better than a false one.

## 8. The summary comment

The top-level comment is what the author reads first and what the team reads later. In order:

1. The verdict, in the first line, with the number of blocking items.
2. What the PR does, in your words (two to five sentences). This is where the author discovers you misunderstood, which is cheaper than discovering it after they implement your comments.
3. The one thing that matters most, if there is one. Design-level concerns go here, not on line 212.
4. What you did: what you read in full, what you skimmed, what you ran and the result. This calibrates how much weight your approval carries.
5. What is missing from the diff, and anything out of scope you are deliberately not asking for.
6. A specific thank-you or praise.

Keep it under a screen. The details are in the inline comments.

## 9. Disagreement and pushback

- When the author disagrees, consider first that they are right. They have spent more time in this code than you.
- Separate facts from preferences. A bug is a fact; a naming choice is a preference. Facts and data win over opinions; the style guide wins over both on style; absent all three, consistency with the surrounding code, then the author's choice.
- Do not block on a preference. Say "non-blocking, your call" and move on.
- If you still believe a blocking finding stands after one round, explain it once more with a concrete scenario or a failing test, then take it out of the comment thread: a short call or a third opinion resolves in five minutes what threads take a day to not resolve.
- Never approve to end an argument, and never block to win one.
- "We will fix it in a follow-up" is acceptable for non-blocking items when there is a ticket, and not acceptable for blocking ones.

## 10. Re-reviews

- Read what changed since your last review (new commits, replies), not the whole PR again.
- For each of your earlier blocking comments, check the code, not the reply. "Done" with no diff is not done.
- Do not raise new non-blocking comments on code you already accepted. New blocking findings are fair if the delta introduced them or you genuinely missed them; say which.
- Resolve threads you raised when they are addressed. Approve promptly once the bar is met.

## 11. What not to comment on

- Formatting, import order, quote style or anything a formatter or linter enforces. If the tool is not enforcing it, the finding is "add the tool", once, in the summary.
- Personal preference dressed as a rule. If you cannot cite the style guide, a measurable consequence or the surrounding code, label it `nitpick (non-blocking)` or drop it.
- Pre-existing problems not touched by the PR. Mention them once under "Out of scope" with an offer to file an issue.
- The same point on every occurrence. Make it once, say "applies to the other N places", and let the author find them.
- Things you have not verified, stated as facts. Those are questions.
