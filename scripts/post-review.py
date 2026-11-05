#!/usr/bin/env python3
"""Post a pull request review (summary plus inline comments) to GitHub as ONE review, after checking
every inline comment against the PR's current diff.

Usage
  post-review.py review.json              validate and post
  post-review.py review.json --dry-run    validate and print the payload; post nothing
  post-review.py review.json --strict     fail instead of moving unplaceable comments into the summary
  post-review.py review.json --no-dedupe  post even if an identical comment of yours already exists there

review.json
{
  "repo": "owner/repo",                  optional when run inside a checkout of the repository
  "pr": 123,
  "event": "COMMENT",                    COMMENT | APPROVE | REQUEST_CHANGES | PENDING (draft only you can see)
  "body": "## Summary ...",              required for COMMENT and REQUEST_CHANGES
  "comments": [
    {"path": "src/billing.py", "line": 88, "body": "**issue (blocking):** ..."},
    {"path": "src/billing.py", "start_line": 40, "line": 46, "body": "**suggestion:** ...", "side": "RIGHT"}
  ]
}

"line" is a line number in the file as it is in the PR (the RIGHT side of the diff). Use "side": "LEFT"
with the old numbering to comment on a removed line. GitHub accepts inline comments only on lines that
appear in the diff (added, removed or context lines of a hunk). Anything else is moved into the summary
body with a path:line reference, or rejected with --strict.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
EVENTS = {"COMMENT", "APPROVE", "REQUEST_CHANGES", "PENDING"}
MAX_BODY = 65536


def run(cmd, input_=None, check=True):
    p = subprocess.run(cmd, capture_output=True, text=True, input=input_)
    if check and p.returncode != 0:
        err = (p.stderr or p.stdout).strip()
        hint = ""
        if "line must be part of the diff" in err or "Line could not be resolved" in err:
            hint = "\nhint: the PR changed since the context was gathered; re-run pr-context.py, re-check line numbers, post again"
        elif "Can not approve your own pull request" in err:
            hint = "\nhint: GitHub does not allow approving your own PR; set \"event\" to \"COMMENT\""
        elif "already pending" in err.lower() or "one pending review" in err.lower():
            hint = "\nhint: you already have a pending (draft) review on this PR; submit or discard it in the GitHub UI first"
        elif "Resource not accessible" in err or "403" in err:
            hint = "\nhint: the token lacks write access to this repository (gh auth status)"
        sys.exit(f"post-review: {' '.join(cmd[:4])} failed\n{err}{hint}")
    return p.stdout


def gh_json(*args, input_=None):
    out = run(["gh", *args], input_=input_)
    return json.loads(out) if out.strip() else None


def paginate(endpoint):
    out = run(["gh", "api", endpoint, "--paginate", "--slurp"])
    items = []
    for page in (json.loads(out) if out.strip() else []):
        items.extend(page if isinstance(page, list) else [page])
    return items


def commentable_lines(patch: str | None):
    """Sets of (right, left) line numbers GitHub will accept for a file, from its patch."""
    right, left = set(), set()
    if not patch:
        return right, left
    old = new = None
    for line in patch.splitlines():
        m = HUNK_RE.match(line)
        if m:
            old, new = int(m.group(1)), int(m.group(3))
            continue
        if old is None or line.startswith("\\"):
            continue
        if line.startswith("+"):
            right.add(new)
            new += 1
        elif line.startswith("-"):
            left.add(old)
            old += 1
        else:
            right.add(new)
            left.add(old)
            new += 1
            old += 1
    return right, left


def nearest(valid: set[int], line: int, window: int = 3) -> int | None:
    """A valid line within a few lines of the requested one, preferring earlier lines (the code the comment is about usually starts above)."""
    for d in range(1, window + 1):
        if line - d in valid:
            return line - d
        if line + d in valid:
            return line + d
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("review", help="review.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--strict", action="store_true", help="fail on comments that cannot be placed inline")
    ap.add_argument("--no-dedupe", action="store_true", help="do not skip comments identical to ones you already posted")
    ap.add_argument("--no-snap", action="store_true", help="do not move a comment to a nearby diff line when its line is just outside a hunk")
    a = ap.parse_args(argv)

    try:
        review = json.loads(Path(a.review).read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"post-review: cannot read {a.review}: {e}")

    repo = review.get("repo") or run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()
    try:
        pr = int(review["pr"])
    except (KeyError, TypeError, ValueError):
        sys.exit("post-review: review.json needs an integer \"pr\"")
    event = str(review.get("event") or "COMMENT").upper()
    if event not in EVENTS:
        sys.exit(f"post-review: event must be one of {sorted(EVENTS)}")
    body = (review.get("body") or "").rstrip()
    comments = review.get("comments") or []
    if event in {"COMMENT", "REQUEST_CHANGES"} and not body:
        sys.exit(f"post-review: {event} requires a non-empty body")
    if not body and not comments:
        sys.exit("post-review: nothing to post (no body, no comments)")

    head = gh_json("pr", "view", str(pr), "--repo", repo, "--json", "headRefOid,url,author,state,isDraft")
    me = run(["gh", "api", "user", "--jq", ".login"]).strip()
    author = (head.get("author") or {}).get("login")
    if event == "APPROVE" and author == me:
        sys.exit("post-review: GitHub does not allow approving your own PR; use COMMENT")
    if head.get("state") != "OPEN":
        print(f"warning: PR is {head.get('state')}; posting anyway", file=sys.stderr)

    files = paginate(f"repos/{repo}/pulls/{pr}/files")
    linemap = {f["filename"]: commentable_lines(f.get("patch")) for f in files}

    existing = set()
    if not a.no_dedupe:
        for c in paginate(f"repos/{repo}/pulls/{pr}/comments"):
            if (c.get("user") or {}).get("login") == me:
                existing.add((c.get("path"), c.get("line") or c.get("original_line"), (c.get("body") or "").strip()))

    placed, moved, skipped, snapped, problems = [], [], [], [], []
    for i, c in enumerate(comments, 1):
        path = c.get("path")
        text = (c.get("body") or "").strip()
        side = str(c.get("side") or "RIGHT").upper()
        if not path or not text:
            problems.append(f"comment {i}: needs 'path' and 'body'")
            continue
        try:
            line = int(c["line"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"comment {i} ({path}): missing or non-integer 'line'")
            continue
        if side not in {"RIGHT", "LEFT"}:
            problems.append(f"comment {i} ({path}:{line}): side must be RIGHT or LEFT")
            continue
        if len(text) > MAX_BODY:
            problems.append(f"comment {i} ({path}:{line}): body exceeds {MAX_BODY} characters")
            continue
        if path not in linemap:
            moved.append((path, line, text, "file is not part of this PR"))
            continue
        right, left = linemap[path]
        valid = right if side == "RIGHT" else left
        if not valid:
            moved.append((path, line, text, "file has no textual diff (binary or too large)"))
            continue
        if line not in valid:
            alt = None if a.no_snap else nearest(valid, line)
            if alt is None:
                moved.append((path, line, text, f"line {line} ({side}) is not in the diff"))
                continue
            snapped.append((path, line, alt))
            line = alt
        if (path, line, text) in existing:
            skipped.append((path, line))
            continue
        entry = {"path": path, "line": line, "side": side, "body": text}
        if c.get("start_line") is not None:
            try:
                sl = int(c["start_line"])
            except (TypeError, ValueError):
                problems.append(f"comment {i} ({path}:{line}): start_line must be an integer")
                continue
            ss = str(c.get("start_side") or side).upper()
            svalid = right if ss == "RIGHT" else left
            if sl >= line or sl not in svalid:
                # fall back to a single-line comment rather than failing the whole review
                print(f"warning: {path}: start_line {sl} is not a valid diff line before {line}; posting as a single-line comment", file=sys.stderr)
            else:
                entry["start_line"] = sl
                entry["start_side"] = ss
        placed.append(entry)

    if problems:
        print("post-review: fix these before posting:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    if moved and a.strict:
        print("post-review: --strict and these comments cannot be placed inline:", file=sys.stderr)
        for path, line, _, why in moved:
            print(f"  - {path}:{line}: {why}", file=sys.stderr)
        return 2
    if moved:
        body = body + "\n\n### Notes on lines outside the diff\n" + "\n".join(
            f"- `{path}:{line}`: {text}" for path, line, text, _ in moved)
    if len(body) > MAX_BODY:
        sys.exit(f"post-review: body exceeds {MAX_BODY} characters after merging notes; shorten it")

    payload = {"commit_id": head["headRefOid"], "body": body, "comments": placed}
    if event != "PENDING":
        payload["event"] = event

    print(f"{repo}#{pr} ({head.get('url')}) at {head['headRefOid'][:10]}")
    print(f"event: {event}{' (draft, visible only to you until submitted)' if event == 'PENDING' else ''}")
    print(f"inline comments: {len(placed)} placed, {len(moved)} moved into the summary, {len(skipped)} skipped as duplicates, {len(snapped)} snapped to a nearby diff line")
    for path, line, why in [(m[0], m[1], m[3]) for m in moved]:
        print(f"  moved: {path}:{line} ({why})")
    for path, line, alt in snapped:
        print(f"  snapped: {path}:{line} -> {alt}")
    for path, line in skipped:
        print(f"  skipped duplicate: {path}:{line}")

    if a.dry_run:
        print()
        print(json.dumps(payload, indent=2))
        print()
        print("dry run: nothing posted")
        return 0
    if not placed and not body.strip():
        sys.exit("post-review: nothing left to post")

    res = gh_json("api", "-X", "POST", f"repos/{repo}/pulls/{pr}/reviews", "--input", "-", input_=json.dumps(payload))
    print(f"posted review {res.get('id')} ({res.get('state')}): {res.get('html_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
