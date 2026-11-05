# Posting a review to GitHub

The review is posted as **one** GitHub review: a summary body plus inline comments, submitted together, so the author gets a single notification and a coherent document rather than a drip of comments. `scripts/post-review.py` does the posting and the validation. Only post when the user asked for it in this request.

## `review.json`

```json
{
  "repo": "owner/repo",
  "pr": 123,
  "event": "COMMENT",
  "body": "**Verdict:** ...\n\n## Summary\n...",
  "comments": [
    { "path": "src/billing/total.py", "line": 88, "body": "**issue (blocking):** ..." },
    { "path": "src/admin/routes.py", "start_line": 12, "line": 18, "body": "**issue (blocking):** ..." },
    { "path": "src/legacy.py", "line": 40, "side": "LEFT", "body": "**question:** this removed check ..." }
  ]
}
```

| Field | Notes |
| --- | --- |
| `repo`, `pr` | Copy from `meta.json` in the work directory. `repo` may be omitted when running inside a checkout of that repository. |
| `event` | `COMMENT` (default), `APPROVE`, `REQUEST_CHANGES`, or `PENDING`. `PENDING` creates a draft review visible only to the user, who submits or discards it in the GitHub UI; use it for `--draft` and whenever the user wants to look before it goes live. GitHub refuses `APPROVE` on the user's own PR. |
| `body` | The summary, in Markdown. Required for `COMMENT` and `REQUEST_CHANGES`. Keep it to the verdict, risk, summary, what you ran, what is missing, praise, out-of-scope. Line-level detail goes in `comments`. |
| `comments[].path` | Path relative to the repository root, exactly as in `files.tsv`. |
| `comments[].line` | Line number in the file **as it is in the PR** (the right side of the diff). For a range, `line` is the last line and `start_line` the first. |
| `comments[].side` | `RIGHT` (default) for added or unchanged lines; `LEFT` with the old numbering to comment on a removed line. `start_side` likewise for ranges. |
| `comments[].body` | Markdown. Start with the Conventional Comments label in bold. A ```` ```suggestion ```` block replaces exactly the lines the comment covers. |

GitHub only accepts inline comments on lines that appear in the diff: added, removed or context lines inside a hunk. A comment on line 300 of a file whose only hunk covers lines 80 to 95 is rejected for the whole review (HTTP 422), so the script checks every comment against the PR's current patches first. Comments it cannot place are appended to the body under "Notes on lines outside the diff" with their `path:line`, or, with `--strict`, reported as errors so you can fix the lines.

To find the right line: open the file in the worktree (the numbering there is the right side) and confirm the line is inside a hunk in `diff.patch`. Hunk headers `@@ -a,b +c,d @@` give the right-side start `c` and length `d`.

## Running it

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/post-review.py <work>/review.json --dry-run   # validate, print the payload
python3 ${CLAUDE_SKILL_DIR}/scripts/post-review.py <work>/review.json             # post
```

Always run the dry run first and read what it prints: how many comments were placed, moved or skipped, and the exact body. Then post. The script prints the review URL on success.

Options: `--strict` (fail on unplaceable comments instead of moving them), `--no-dedupe` (post even if an identical comment of yours already exists at that location; by default those are skipped so a retry does not double-post).

## Choosing the event

- The user said "approve" or "request changes": use that.
- The user said "post the review" or "post the comments" without choosing: `COMMENT`, with the verdict stated in the body's first line. A GitHub approval is a formal act under their name; let them click it.
- The user said "draft" or "let me look first": `PENDING`.

## Re-reviews

A second round is a new review (new `review.json`, new submission), not edits to the old one. Reply in existing threads only when the user asks to; the script does not post replies. Mention in the body which earlier items are resolved and which remain.

## Troubleshooting

- `422 ... line must be part of the diff`: the PR changed since `pr-context.py` ran. Re-run it, re-check the lines, post again.
- `422 ... Can not approve your own pull request`: change `event` to `COMMENT`.
- `422 ... Review Comment is already pending`: a `PENDING` review of the user's already exists on this PR. Submit or discard it in the UI first.
- `403` or `404`: the token (`gh auth status`) lacks write access to the repository, or the PR is in a repository the user cannot write to; post the review as a plain issue comment with `gh pr comment` only if the user wants that.
- `gh: command not found` or not logged in: `gh auth login`.
- Secondary rate limit: wait a minute and retry; the dedupe check prevents duplicates.

## Limits

Review and comment bodies are limited to 65,536 characters each. Keep the summary under a screen and the comments under a paragraph; a review that needs more than about 25 inline comments is a sign the PR should be split, and the summary should say so.
