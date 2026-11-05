#!/usr/bin/env python3
"""Gather everything a reviewer needs about a pull request, or a local branch, into one work directory.

Usage
  pr-context.py 123                                  PR 123 of the repository in the current directory
  pr-context.py https://github.com/OWNER/REPO/pull/123
  pr-context.py OWNER/REPO#123
  pr-context.py my-branch                            the open PR for that branch, else a local review against the base
  pr-context.py                                      the current branch against its base (self-review)

Options
  -C PATH             run as if started in PATH (the repository to review, for local and branch reviews)
  --repo OWNER/REPO   repository for a bare number or branch (default: the repository of the current directory)
  --base REF          base ref for local reviews (default: origin/HEAD, then main, master, develop)
  --out DIR           work directory (default: ~/.cache/pr-review/<owner>__<repo>/pr-<n>)
  --no-diff           do not write diff.patch (for enormous PRs)

The work directory path is printed on the last line of stdout. Files written:
  summary.md        one-screen briefing: size, risk flags, CI, reading order, grep hits, discussion. Read this first.
  description.md    title and body as the author wrote them
  linked-issues.md  issues the description references
  reading-order.md  changed files grouped in the order a reviewer should read them
  files.tsv         status, additions, deletions, bucket, flags, path
  commits.md        commits with authors and trailers
  checks.md         CI check runs and statuses
  discussion.md     existing reviews, inline threads (resolved or not) and conversation
  diff.patch        the full unified diff
  meta.json         machine-readable metadata (repo, number, head sha, base, risk flags, suggested depth, ...)
  uncommitted.patch (local reviews only) working-tree changes not yet committed, when there are any
checks.md and discussion.md exist only for GitHub PRs. Files from a previous run are removed first.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

CACHE = Path(os.environ.get("PR_REVIEW_CACHE", str(Path.home() / ".cache" / "pr-review")))


class Fail(Exception):
    pass


# ----------------------------------------------------------------------------- shell helpers

def run(cmd, *, check=True, cwd=None, input_=None):
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, input=input_)
    if check and p.returncode != 0:
        raise Fail(f"$ {' '.join(cmd)}\n{(p.stderr or p.stdout).strip()}")
    return p.stdout


def gh(*args, cwd=None):
    return run(["gh", *args], cwd=cwd)


def gh_json(*args, cwd=None):
    out = gh(*args, cwd=cwd)
    return json.loads(out) if out.strip() else None


def gh_paginate(endpoint):
    out = gh("api", endpoint, "--paginate", "--slurp")
    items = []
    for page in (json.loads(out) if out.strip() else []):
        if isinstance(page, list):
            items.extend(page)
        elif page is not None:
            items.append(page)
    return items


def git(*args, cwd=None, check=True):
    return run(["git", *args], cwd=cwd, check=check)


def current_repo():
    try:
        return gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip() or None
    except Fail:
        return None


def git_root():
    try:
        return git("rev-parse", "--show-toplevel").strip()
    except Fail:
        return None


# ----------------------------------------------------------------------------- target parsing

URL_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")
SHORT_RE = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")


def parse_target(target: str | None, repo_flag: str | None):
    """Return (kind, repo, value) with kind in {"pr", "branch", "local"}."""
    if not target:
        return "local", repo_flag, None
    m = URL_RE.search(target)
    if m:
        return "pr", f"{m.group(1)}/{m.group(2).removesuffix('.git')}", int(m.group(3))
    m = SHORT_RE.match(target)
    if m:
        return "pr", f"{m.group(1)}/{m.group(2)}", int(m.group(3))
    t = target.lstrip("#")
    if t.isdigit():
        repo = repo_flag or current_repo()
        if not repo:
            raise Fail("a bare PR number needs a repository: run inside a clone or pass --repo OWNER/REPO (or give the PR URL)")
        return "pr", repo, int(t)
    return "branch", repo_flag, target


# ----------------------------------------------------------------------------- classification

GENERATED_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "cargo.lock", "go.sum", "poetry.lock", "pipfile.lock",
    "composer.lock", "gemfile.lock", "bun.lockb", "bun.lock", "uv.lock", "flake.lock", "mix.lock", "pubspec.lock",
    "packages.lock.json", "podfile.lock", "gradle.lockfile",
}
GENERATED_RE = re.compile(
    r"\.(min\.js|min\.css|map|snap|pb\.go|pb\.cc|pb\.h|_pb2\.py|_pb2_grpc\.py|generated\.[a-z]+|g\.cs|designer\.cs|lock\.json)$"
    r"|(^|/)(dist|build|out|vendor|node_modules|__snapshots__|\.yarn|generated|__generated__|gen|third_party)/"
    r"|(^|/)[^/]*\.(svg|png|jpg|jpeg|gif|ico|woff2?|ttf|eot|pdf|mp4|mp3|zip|jar|wasm|bin)$"
)
TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|e2e|cypress|playwright|testdata|fixtures|__mocks__|integration-tests?)(/|$)"
    r"|(\.|_)(test|spec|tests|e2e)\.[a-z]+$|(^|/)test_[^/]+\.py$|_test\.(go|rs|rb|ex|exs)$|Tests?\.(java|kt|cs|swift|scala)$|(^|/)conftest\.py$"
)
INFRA_RE = re.compile(
    r"(^|/)\.github/|(^|/)\.gitlab-ci|(^|/)\.circleci/|(^|/)jenkinsfile|(^|/)\.buildkite/|(^|/)azure-pipelines|(^|/)bitbucket-pipelines"
    r"|(^|/)(dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml|makefile|caddyfile|procfile|vercel\.json|netlify\.toml|fly\.toml|render\.yaml)$"
    r"|\.(tf|tfvars|hcl|nomad)$|(^|/)(infra|infrastructure|deploy|deployment|k8s|kubernetes|helm|charts|terraform|ansible|nginx|ops|\.devcontainer)(/|$)"
)
CONTRACT_RE = re.compile(
    r"(^|/)(migrations?|migrate|alembic|db/migrate|prisma|drizzle|flyway|liquibase|schemas?|types?|interfaces?|models?|contracts?|proto|protos|graphql|openapi|swagger|dto|entities)(/|$)"
    r"|\.(d\.ts|proto|graphql|gql|avsc|thrift|prisma)$|(^|/)(openapi|swagger)[^/]*\.(ya?ml|json)$|\.sql$|(^|/)schema\.[a-z]+$"
)
CONFIG_RE = re.compile(
    r"(^|/)(package\.json|pyproject\.toml|setup\.py|setup\.cfg|requirements[^/]*\.txt|go\.mod|cargo\.toml|gemfile|composer\.json|build\.gradle(\.kts)?|pom\.xml|pipfile|tsconfig[^/]*\.json|\.babelrc|babel\.config\.[a-z]+|\.eslintrc[^/]*|eslint\.config\.[a-z]+|\.prettierrc[^/]*|jest\.config\.[a-z]+|vitest\.config\.[a-z]+|webpack\.config\.[a-z]+|vite\.config\.[a-z]+|next\.config\.[a-z]+|tailwind\.config\.[a-z]+|\.env[^/]*|\.editorconfig|\.gitignore|\.gitattributes|\.npmrc|\.nvmrc|\.tool-versions|\.python-version|renovate\.json|\.renovaterc[^/]*|dependabot\.yml|codecov\.yml|\.pre-commit-config\.yaml|ruff\.toml|mypy\.ini|\.flake8|tox\.ini|noxfile\.py|phpunit\.xml|appsettings[^/]*\.json)$"
    r"|\.(toml|ini|cfg|properties|conf|env)$"
)
DOCS_RE = re.compile(r"\.(md|mdx|rst|txt|adoc|asciidoc)$|(^|/)(docs?|documentation|adr|rfcs?)(/|$)|(^|/)(license|changelog|contributing|code_of_conduct|readme)[^/]*$")

BUCKET_ORDER = ["tests", "contracts", "source", "config", "infra", "docs", "generated"]
BUCKET_TITLES = {
    "tests": "Tests: what the author believes the change does",
    "contracts": "Contracts: schemas, migrations, types, interfaces, serialized formats",
    "source": "Core logic: follow the call path from the entry point, not file order",
    "config": "Configuration and dependencies",
    "infra": "Infrastructure and CI",
    "docs": "Docs and comments: are they still true?",
    "generated": "Generated files and lockfiles: skim for the unexpected, do not read line by line",
}


def is_generated(path: str) -> bool:
    p = path.lower()
    return os.path.basename(p) in GENERATED_NAMES or bool(GENERATED_RE.search(p))


def bucket(path: str) -> str:
    p = path.lower()
    if is_generated(p):
        return "generated"
    if TEST_RE.search(p):
        return "tests"
    if INFRA_RE.search(p):
        return "infra"
    if CONTRACT_RE.search(p):
        return "contracts"
    if CONFIG_RE.search(p):
        return "config"
    if DOCS_RE.search(p):
        return "docs"
    return "source"


def _w(*words):
    """Match any word with soft boundaries: no letters directly on either side (so `tax` does not match `syntax`)."""
    return re.compile(r"(?<![a-z])(?:" + "|".join(words) + r")(?![a-z])")


RISK_PATTERNS = [
    ("auth", _w("auth", "authn", "authentication", "login", "logout", "signin", "signup", "session", "sessions", "token", "tokens", "jwt", "oauth", "oidc", "sso", "saml", "password", "passwords", "passwd", "credential", "credentials", "secret", "secrets", "apikey", "api_key", "api-key")),
    ("permissions", _w("permission", "permissions", "authz", "authorization", "authorize", "acl", "rbac", "abac", "policy", "policies", "role", "roles", "scope", "scopes", "guard", "guards", "tenant", "tenants", "ownership")),
    ("money", _w("payment", "payments", "billing", "invoice", "invoices", "stripe", "paypal", "braintree", "price", "prices", "pricing", "refund", "refunds", "payout", "payouts", "ledger", "wallet", "subscription", "subscriptions", "tax", "taxes", "coupon", "coupons", "discount", "discounts", "currency", "order_total", "cart")),
    ("crypto", _w("crypto", "crypt", "encrypt", "decrypt", "encryption", "hash", "hashing", "hmac", "signature", "signatures", "signing", "kms", "certificate", "certificates", "cert", "certs", "tls", "ssl", "keystore")),
    ("data-migration", re.compile(r"migration|migrate|alembic|prisma/|\.sql$|(?<![a-z])(schema|schemas|seed|seeds|backfill)(?![a-z])")),
    ("pii", _w("pii", "gdpr", "hipaa", "ssn", "dob", "birthdate", "passport", "national_id", "consent", "privacy", "personal_data")),
    ("infra", re.compile(r"dockerfile|docker-compose|compose\.ya?ml|\.github/workflows|\.gitlab-ci|terraform|\.tf$|(?<![a-z])(helm|k8s|kubernetes|nginx|caddyfile|deploy|deployment|infra|ansible|systemd)(?![a-z])|\.circleci")),
    ("build-scripts", re.compile(r"package\.json|setup\.py|pyproject|build\.rs|makefile|cmakelists|gradle|pom\.xml|postinstall|preinstall|\.husky|\.pre-commit|(?<![a-z])(bootstrap|install)(?![a-z])")),
    ("ingress", _w("upload", "uploads", "download", "downloads", "webhook", "webhooks", "callback", "callbacks", "import", "importer", "export", "exporter", "parser", "parsers", "deserialize", "deserializer", "unmarshal", "pickle", "exec", "spawn", "subprocess", "shell")),
    ("concurrency", _w("queue", "queues", "worker", "workers", "job", "jobs", "cron", "scheduler", "schedule", "lock", "locks", "locking", "mutex", "semaphore", "thread", "threads", "concurrent", "concurrency", "pool", "pools", "batch", "batches")),
    ("deletion", _w("delete", "deletes", "deletion", "purge", "drop", "truncate", "destroy", "wipe", "retention")),
    ("public-api", re.compile(r"(^|/)(api|routes?|router|controllers?|handlers?|endpoints?|graphql|resolvers?|rpc|grpc|cli|commands?)(/|\.|$)|openapi|swagger|\.proto$")),
]
HIGH_RISK = {"auth", "permissions", "money", "crypto", "data-migration", "pii", "infra", "build-scripts", "deletion"}


def risk_flags(path: str) -> list[str]:
    """Risk flags from a path, for code-like files only: a test fixture or a doc named `secret` is not a risk."""
    if bucket(path) in ("tests", "docs", "generated"):
        return []
    p = path.lower()
    return [name for name, rx in RISK_PATTERNS if rx.search(p)]


# ----------------------------------------------------------------------------- diff scanning

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff_text: str):
    """Yield (path, new_line_number, text) for every added line in a unified diff."""
    path = None
    new_ln = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            path, new_ln = None, None
        elif line.startswith("+++ "):
            p = line[4:].strip()
            path = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            new_ln = int(m.group(3)) if m else None
        elif new_ln is None or path is None:
            continue
        elif line.startswith("+"):
            yield path, new_ln, line[1:]
            new_ln += 1
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            new_ln += 1


GREP_PATTERNS = [
    ("secret-looking literal", re.compile(r"(?i)(api[_-]?key|secret|passw(or)?d|token|private[_-]?key)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
    ("private key", re.compile(r"BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("eval/exec", re.compile(r"(?<![\w.])(eval|exec|execSync|execfile)\s*\(")),
    ("shell=True", re.compile(r"shell\s*=\s*True")),
    ("raw HTML sink", re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*=|v-html=|\|\s*safe\b|mark_safe\(|html_safe|\{@html|\.html\(")),
    ("SQL built from strings", re.compile(r"(?i)(select\s+[\w*,.\s]+\s+from\s|insert\s+into\s|update\s+\w+\s+set\s|delete\s+from\s)[^\n;]*(['\"`]\s*\+|\+\s*['\"`]|%s|%\(|\{\w+\}|\$\{|\bf['\"])")),
    ("insecure deserialization", re.compile(r"pickle\.loads?|yaml\.load\((?![^)]*Loader)|unserialize\(|ObjectInputStream|Marshal\.load|yaml\.unsafe_load")),
    ("TLS verification off", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|InsecureSkipVerify\s*:\s*true|CURLOPT_SSL_VERIFYPEER,\s*(false|0)|NODE_TLS_REJECT_UNAUTHORIZED")),
    ("debug leftovers", re.compile(r"\b(console\.(log|debug|trace)|debugger|binding\.pry|byebug|var_dump|dd\()\b|^\s*print\(f?['\"](DEBUG|here|test|xxx)")),
    ("focused or skipped tests", re.compile(r"\b(it|test|describe|context)\.(only|skip)\(|@pytest\.mark\.skip|\bxit\(|\bfit\(|\bxdescribe\(|\bfdescribe\(|t\.Skip\(|@Ignore\b|@Disabled\b")),
    ("suppressed checks", re.compile(r"@ts-ignore|@ts-expect-error|eslint-disable|#\s*noqa|#\s*type:\s*ignore|#\[allow\(|@SuppressWarnings|//\s*nolint|#\s*nosec|//\s*NOSONAR|# pragma: no cover")),
    ("TODO/FIXME/HACK", re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")),
    ("hardcoded localhost or IP", re.compile(r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\d{1,3}(\.\d{1,3}){3})")),
    ("sleep", re.compile(r"\b(time\.sleep|Thread\.sleep|sleep\(\d|setTimeout\([^,]+,\s*\d{3,}|await\s+sleep)")),
    ("broad exception catch", re.compile(r"except\s*:|except\s+(BaseException|Exception)\s*(as\s+\w+\s*)?:|catch\s*\(\s*(Exception|Throwable|RuntimeException|e|err|error|_|ex)?\s*\)\s*\{\s*\}|rescue\s*(=>\s*\w+)?\s*$")),
    ("unsafe block", re.compile(r"\bunsafe\s*\{")),
    ("world-writable permissions", re.compile(r"\b0?[67]77\b|chmod\s+(-R\s+)?777")),
    ("hook or verification bypass", re.compile(r"--no-verify|--force\b|-f\s+origin|--allow-unrelated|GIT_SSL_NO_VERIFY")),
    ("new env or feature flag", re.compile(r"process\.env\.[A-Z_]+|os\.environ(\.get)?\[?\(?['\"][A-Z_]+|os\.getenv\(|System\.getenv\(|ENV\[['\"]|std::env::var\(|os\.Getenv\(")),
]


def scan_diff(diff_text: str, generated: set[str]):
    hits = []
    for path, ln, text in added_lines(diff_text):
        if path in generated or len(text) > 400:
            continue
        for name, rx in GREP_PATTERNS:
            if rx.search(text):
                hits.append((name, path, ln, text.strip()[:160]))
    return hits


# ----------------------------------------------------------------------------- AI signals

AI_MARKERS = [
    "claude", "copilot", "cursor", "devin", "codex", "chatgpt", "gpt-4", "gpt-5", "openai", "gemini", "aider", "windsurf",
    "cline", "sweep", "generated with", "generated by", "ai-generated", "ai generated", "🤖", "amp.dev", "jules", "kiro", "roo code",
]


DEPENDENCY_BOTS = ("dependabot", "renovate", "greenkeeper", "snyk-bot", "pre-commit-ci", "pyup-bot", "depfu", "mend-bolt", "whitesource")
BUMP_TITLE_RE = re.compile(r"(?i)\b(bump|update|upgrade)\b.*\b(from|to|->|→)\b|^chore\(deps(-dev)?\)|\bdependenc(y|ies)\b.*\b(update|bump)")


def is_dependency_bot(author_login: str) -> bool:
    low = (author_login or "").lower()
    return any(b in low for b in DEPENDENCY_BOTS)


def ai_signals(author_login: str, body: str, commits: list[dict]) -> list[str]:
    """Signals that a coding agent wrote the change. Dependency bots are not one: they generate manifests, not code."""
    found = []
    if is_dependency_bot(author_login):
        return found
    if author_login.endswith("[bot]") or author_login.startswith("app/"):
        found.append(f"author is a bot account ({author_login})")
    low = (body or "").lower()
    for line in (body or "").splitlines():
        m = re.match(r"^\s*[-*]\s*\[(?:x|X)\]\s*(.+)$", line)
        if m and re.search(r"(?i)\b(agent|agents|ai|llm|copilot|claude|codex|cursor|assistant|assisted)\b", m.group(1)):
            found.append(f"description checkbox: {m.group(1).strip()[:120]}")
    phrase = re.search(r"(?i)\b(an agent|ai|an llm|copilot|claude|codex|cursor)\b[^.\n]{0,40}\b(wrote|generated|authored|drafted|implemented|produced)\b"
                       r"|\b(written|generated|authored|drafted|implemented|produced)\s+(by|with)\s+(an\s+)?(agent|ai|llm|copilot|claude|codex|cursor)\b", body or "")
    if phrase:
        found.append(f"description says: {' '.join(phrase.group(0).split())[:120]}")
    elif not found:
        for m in AI_MARKERS:
            if m in low:
                found.append(f"description mentions '{m}'")
                break
    trailers = set()
    for c in commits:
        msg = f"{c.get('messageHeadline', '')}\n{c.get('messageBody', '')}"
        for line in msg.splitlines():
            l = line.strip().lower()
            if l.startswith("co-authored-by:") and any(m in l for m in AI_MARKERS):
                trailers.add(line.strip())
            elif any(m in l for m in ("generated with", "generated by")) and any(m in l for m in AI_MARKERS):
                trailers.add(line.strip())
    for t in sorted(trailers)[:5]:
        found.append(f"commit trailer: {t}")
    return found


# ----------------------------------------------------------------------------- formatting helpers

def md_escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def when(s: str | None) -> str:
    if not s:
        return ""
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return s


def size_class(lines: int) -> str:
    if lines < 100:
        return "small"
    if lines < 400:
        return "medium"
    if lines < 1000:
        return "large"
    return "very large"


def suggest_depth(meta: dict) -> tuple[str, list[str]]:
    reasons = []
    flags = set(meta["risk_flags"])
    high = sorted(flags & HIGH_RISK)
    if high:
        reasons.append(f"touches {', '.join(high)}")
    if meta["size_class"] in ("large", "very large"):
        reasons.append(f"{meta['hand_written_lines']} hand-written lines changed")
    if meta.get("ai_signals") and not meta["tests_touched"]:
        reasons.append("AI-authorship signals and no test changes")
    assoc = meta.get("author_association")
    if assoc in ("FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"):
        reasons.append(f"author association is {assoc}: treat as untrusted code before running anything")
    if meta.get("is_cross_repository"):
        reasons.append("comes from a fork")
    buckets = set(meta["buckets_present"])
    if meta.get("dependency_bump") and buckets <= {"config", "generated", "docs"}:
        return "quick", ["dependency bump touching only manifests and lockfiles: read the upstream changes between the two versions, check the lockfile hashes and CI, look at how the code uses the dependency"]
    if reasons:
        return "deep", reasons
    if meta["hand_written_lines"] < 60 and not flags and buckets <= {"docs", "config", "generated"}:
        return "quick", ["small change limited to docs, config or generated files"]
    if meta["hand_written_lines"] < 20 and not flags:
        return "quick", ["very small change with no risk flags"]
    return "standard", ["ordinary change"]


# ----------------------------------------------------------------------------- writers

def write(path: Path, text: str):
    path.write_text(text if text.endswith("\n") else text + "\n")


OUTPUTS = ["summary.md", "description.md", "linked-issues.md", "reading-order.md", "files.tsv", "commits.md",
           "checks.md", "discussion.md", "diff.patch", "meta.json", "uncommitted.patch"]


def fresh(out: Path) -> Path:
    """Create the work directory and drop outputs of an earlier run, so nothing stale survives. review.md and
    review.json written by the reviewer are kept."""
    out.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:
        (out / name).unlink(missing_ok=True)
    return out


def write_files_tsv(out: Path, files: list[dict]):
    rows = ["status\tadded\tdeleted\tbucket\tflags\tpath"]
    for f in files:
        rows.append("\t".join([
            f["status"], str(f["additions"]), str(f["deletions"]), f["bucket"], ",".join(f["flags"]), f["path"],
        ]))
    write(out / "files.tsv", "\n".join(rows))


def reading_order_md(files: list[dict]) -> str:
    by = defaultdict(list)
    for f in files:
        by[f["bucket"]].append(f)
    parts = ["# Reading order", "",
             "Tests first (what the author thinks the change does), then contracts (what radiates), then the core logic along its call path, then the boring files where outages hide. Open full files in the worktree; the diff is only a map.", ""]
    step = 0
    for b in BUCKET_ORDER:
        if not by.get(b):
            continue
        if b == "generated":
            parts.append(f"## {BUCKET_TITLES[b]}")
        else:
            step += 1
            parts.append(f"## {step}. {BUCKET_TITLES[b]}")
        parts.append("")
        for f in sorted(by[b], key=lambda x: (-(x["additions"] + x["deletions"]), x["path"])):
            flag = f"  [{', '.join(f['flags'])}]" if f["flags"] else ""
            ren = f"  (was {f['previous']})" if f.get("previous") else ""
            parts.append(f"- `{f['path']}`  {f['status']} +{f['additions']}/-{f['deletions']}{ren}{flag}")
        parts.append("")
    return "\n".join(parts)


def checks_md(rollup: list[dict] | None) -> tuple[str, Counter]:
    counts = Counter()
    if not rollup:
        return "# Checks\n\nNo status checks reported.\n", counts
    rows = ["# Checks", "", "| Check | Status | Link |", "| --- | --- | --- |"]
    skipped = []
    for c in rollup:
        if c.get("__typename") == "StatusContext":
            name, state, url = c.get("context", ""), (c.get("state") or "").lower(), c.get("targetUrl", "")
        else:
            name = c.get("name") or c.get("workflowName") or ""
            if c.get("workflowName") and c.get("name") and c["workflowName"] != c["name"]:
                name = f"{c['workflowName']} / {c['name']}"
            status, conclusion = (c.get("status") or "").lower(), (c.get("conclusion") or "").lower()
            state = conclusion or status
            url = c.get("detailsUrl", "")
        if state == "skipped":
            counts["skipped"] += 1
            skipped.append(name)
            continue
        if state in ("success", "neutral"):
            counts["passing"] += 1
        elif state in ("failure", "error", "cancelled", "timed_out", "action_required", "startup_failure"):
            counts["failing"] += 1
        else:
            counts["pending"] += 1
        rows.append(f"| {md_escape_cell(name)} | {state} | {url} |")
    if skipped:
        rows.append("")
        rows.append(f"Skipped ({len(skipped)}, usually conditional jobs that did not apply): " + ", ".join(md_escape_cell(n) for n in sorted(skipped)[:40]) + (" ..." if len(skipped) > 40 else ""))
    return "\n".join(rows) + "\n", counts


def commits_md(commits: list[dict]) -> str:
    rows = ["# Commits", "", f"{len(commits)} commit(s), oldest first.", ""]
    for c in commits:
        authors = ", ".join(a.get("login") or a.get("name") or "?" for a in c.get("authors", [])) or "?"
        rows.append(f"- `{c.get('oid', '')[:10]}` {c.get('messageHeadline', '').strip()}  ({authors}, {when(c.get('committedDate'))})")
        body = (c.get("messageBody") or "").strip()
        if body:
            for line in body.splitlines()[:12]:
                rows.append(f"    {line}")
    return "\n".join(rows) + "\n"


def fetch_threads(owner: str, name: str, number: int) -> list[dict]:
    query = """
query($owner:String!, $name:String!, $number:Int!, $after:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100, after:$after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved isOutdated path line originalLine diffSide
          comments(first:50) { nodes { author { login } body createdAt url } }
        }
      }
    }
  }
}"""
    threads, after = [], None
    for _ in range(20):
        args = ["api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}"]
        if after:
            args += ["-f", f"after={after}"]
        data = gh_json(*args)
        rt = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads.extend(rt["nodes"])
        if not rt["pageInfo"]["hasNextPage"]:
            break
        after = rt["pageInfo"]["endCursor"]
    return threads


def threads_from_rest(repo: str, number: int) -> list[dict]:
    """Inline threads rebuilt from REST review comments (no resolved state), for when GraphQL is unavailable."""
    by_id, roots = {}, []
    for c in gh_paginate(f"repos/{repo}/pulls/{number}/comments"):
        node = {"author": {"login": (c.get("user") or {}).get("login", "?")}, "body": c.get("body", ""), "createdAt": c.get("created_at"), "url": c.get("html_url")}
        if c.get("in_reply_to_id") and c["in_reply_to_id"] in by_id:
            by_id[c["in_reply_to_id"]]["comments"]["nodes"].append(node)
        else:
            t = {"isResolved": None, "isOutdated": c.get("line") is None, "path": c.get("path"), "line": c.get("line"),
                 "originalLine": c.get("original_line"), "comments": {"nodes": [node]}}
            by_id[c["id"]] = t
            roots.append(t)
    return roots


def strip_html_comments(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"<!--.*?-->", "", text or "", flags=re.S)).strip()


def discussion_md(reviews: list[dict], threads: list[dict], comments: list[dict], thread_note: str = "") -> tuple[str, dict]:
    parts = ["# Existing discussion", ""]
    if thread_note:
        parts += [thread_note, ""]
    stats = {"reviews": len(reviews), "threads": len(threads), "unresolved": 0, "comments": len(comments), "thread_note": thread_note}
    parts.append(f"## Reviews ({len(reviews)})")
    parts.append("")
    if not reviews:
        parts.append("None yet.")
    for r in reviews:
        who = (r.get("author") or {}).get("login", "?")
        parts.append(f"- **{who}** {r.get('state', '')} at {when(r.get('submittedAt'))}")
        body = strip_html_comments(r.get("body") or "")
        if body:
            for line in body.splitlines()[:30]:
                parts.append(f"  > {line}")
    parts.append("")
    parts.append(f"## Inline threads ({len(threads)})")
    parts.append("")
    if not threads:
        parts.append("None yet.")
    for t in threads:
        if t.get("isResolved") is None:
            state = "resolution unknown"
        else:
            state = "resolved" if t.get("isResolved") else "UNRESOLVED"
        if t.get("isResolved") is False:
            stats["unresolved"] += 1
        if t.get("isOutdated"):
            state += ", outdated"
        line = t.get("line") or t.get("originalLine")
        parts.append(f"- `{t.get('path')}:{line}` ({state})")
        for c in (t.get("comments") or {}).get("nodes", []):
            who = (c.get("author") or {}).get("login", "?")
            text = " ".join((c.get("body") or "").strip().split())
            parts.append(f"  - **{who}**: {text[:600]}")
    parts.append("")
    parts.append(f"## Conversation ({len(comments)})")
    parts.append("")
    if not comments:
        parts.append("None yet.")
    for c in comments:
        who = (c.get("author") or {}).get("login", "?")
        text = strip_html_comments(c.get("body") or "")
        parts.append(f"- **{who}** at {when(c.get('createdAt'))}:")
        for line in text.splitlines()[:20]:
            parts.append(f"  > {line}")
    return "\n".join(parts) + "\n", stats


ISSUE_RE = re.compile(r"(?:(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*)?(?:https?://(?:redirect\.)?github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)|(?<![\w/])#(\d+))", re.I)


def linked_issues_md(repo: str, body: str, author: str = "") -> tuple[str, list[str]]:
    parts = ["# Linked issues", ""]
    titles = []
    if is_dependency_bot(author):
        parts.append("Bot-written description: the issue and PR numbers in it belong to the upstream project's release notes, not to this repository. Read them in description.md; the upstream compare view is the thing to open.")
        return "\n".join(parts) + "\n", titles
    seen, refs = set(), []
    for m in ISSUE_RE.finditer(body or ""):
        r = m.group(1) or repo
        n = m.group(2) or m.group(3)
        if r.lower() != repo.lower() and not m.group(1):
            continue
        key = f"{r}#{n}".lower()
        if key not in seen:
            seen.add(key)
            refs.append((r, int(n)))
    if not refs:
        parts.append("The description references no issues.")
    for r, n in refs[:6]:
        try:
            issue = gh_json("issue", "view", str(n), "--repo", r, "--json", "number,title,body,state,url,labels")
        except Fail:
            continue  # probably a PR number, or no access
        labels = ", ".join(l.get("name", "") for l in issue.get("labels", []))
        titles.append(f"{r}#{n}: {issue.get('title', '')}")
        parts.append(f"## {r}#{n}: {issue.get('title', '')}  ({issue.get('state', '')}{', ' + labels if labels else ''})")
        parts.append("")
        parts.append(issue.get("url", ""))
        parts.append("")
        parts.append((issue.get("body") or "(no body)").strip()[:4000])
        parts.append("")
    return "\n".join(parts) + "\n", titles


def summary_md(meta: dict, files: list[dict], check_counts: Counter, failing: list[str], hits: list, disc: dict,
               issue_titles: list[str], description: str, uncommitted: list[str] | None) -> str:
    L = []
    if meta["mode"] == "pr":
        L.append(f"# PR #{meta['number']}: {meta['title']}")
        L.append("")
        L.append(f"{meta['repo']} · by **{meta['author']}**{' (' + meta['author_association'].lower().replace('_', ' ') + ')' if meta.get('author_association') else ''}"
                 f" · `{meta['base']}` ← `{meta['head']}` @ `{meta['head_sha'][:10]}`"
                 f" · {meta['state'].lower()}{' · DRAFT' if meta.get('is_draft') else ''}{' · from a fork' if meta.get('is_cross_repository') else ''}")
        L.append(f"opened {when(meta.get('created_at'))} · updated {when(meta.get('updated_at'))} · {meta['url']}")
    else:
        L.append(f"# Local review: `{meta['head']}` against `{meta['base']}`")
        L.append("")
        L.append(f"{meta['repo_root']} · merge-base `{meta['merge_base'][:10]}` · head `{meta['head_sha'][:10]}`")
    L.append("")
    gen = [f for f in files if f["bucket"] == "generated"]
    L.append(f"**Size:** +{meta['additions']}/-{meta['deletions']} over {len(files)} files. "
             f"Hand-written: {meta['hand_written_lines']} lines across {len(files) - len(gen)} files ({meta['size_class']})."
             + (f" Generated/lockfiles excluded: {len(gen)} files, {sum(f['additions'] + f['deletions'] for f in gen)} lines." if gen else ""))
    if meta["mode"] == "pr":
        ci = (f"{check_counts['passing']} passing, {check_counts['failing']} failing, {check_counts['pending']} pending"
              + (f", {check_counts['skipped']} skipped" if check_counts.get("skipped") else "")) if sum(check_counts.values()) else "none reported"
        L.append(f"**Review decision:** {meta.get('review_decision') or 'none'} · **mergeable:** {meta.get('mergeable') or '?'}"
                 f"{' (' + meta['merge_state'].lower() + ')' if meta.get('merge_state') else ''} · **CI:** {ci}")
        if failing:
            L.append("  Failing: " + "; ".join(failing[:8]))
        if meta.get("labels"):
            L.append(f"**Labels:** {', '.join(meta['labels'])}")
    L.append("")
    if meta["risk_flags"]:
        L.append("**Risk flags** (from file paths; judge each one):")
        for flag in meta["risk_flags"]:
            paths = [f["path"] for f in files if flag in f["flags"]][:6]
            more = len([f for f in files if flag in f["flags"]]) - len(paths)
            L.append(f"- `{flag}`: " + ", ".join(f"`{p}`" for p in paths) + (f" and {more} more" if more > 0 else ""))
    else:
        L.append("**Risk flags:** none from file paths.")
    L.append("")
    L.append(f"**Suggested depth:** **{meta['suggested_depth']}** ({'; '.join(meta['depth_reasons'])}). Override with judgment or `--depth`.")
    L.append("")
    L.append(f"**Tests touched:** {'yes' if meta['tests_touched'] else 'NO: no test files in this change'}.")
    if meta.get("dependency_bump"):
        L.append("**Dependency bump:** the review is the upstream change between the two versions, the lockfile hashes, CI, and how this code uses the dependency. See SKILL.md, Special situations.")
    if meta.get("ai_signals"):
        L.append("**AI-authorship signals:** " + "; ".join(meta["ai_signals"]) + ". See references/ai-generated.md.")
    if uncommitted:
        L.append(f"**Uncommitted changes in the working tree:** {len(uncommitted)} path(s); see `uncommitted.patch`. The review covers committed work unless told otherwise.")
    L.append("")
    L.append("## What the description claims")
    L.append("")
    desc = re.sub(r"<!--.*?-->", "", description or "", flags=re.S).strip()
    desc = re.sub(r"\n{3,}", "\n\n", desc)
    if desc:
        lines = desc.splitlines()
        L.extend(lines[:40])
        if len(lines) > 40:
            L.append(f"... ({len(lines) - 40} more lines in description.md)")
    else:
        L.append("(empty: that is a finding. Ask for the why, the what and how to test.)")
    L.append("")
    if issue_titles:
        L.append("## Linked issues")
        L.append("")
        L.extend(f"- {t}" for t in issue_titles)
        L.append("")
    L.append("## Reading order")
    L.append("")
    by = defaultdict(list)
    for f in files:
        by[f["bucket"]].append(f)
    for b in BUCKET_ORDER:
        if by.get(b):
            names = sorted(by[b], key=lambda x: -(x["additions"] + x["deletions"]))
            shown = ", ".join(f"`{f['path']}`" for f in names[:8])
            L.append(f"- **{b}** ({len(names)}): {shown}{' ...' if len(names) > 8 else ''}")
    L.append("")
    L.append("Full list with sizes and flags in `reading-order.md`.")
    L.append("")
    L.append("## Grep hits worth a look")
    L.append("")
    if hits:
        counts = Counter(h[0] for h in hits)
        L.append("Pattern matches on added lines. Most are fine; each is a place to pause for a second.")
        L.append("")
        shown = 0
        for name, _ in counts.most_common():
            group = [h for h in hits if h[0] == name]
            L.append(f"- **{name}** ({len(group)})")
            for _, path, ln, text in group[:5]:
                L.append(f"  - `{path}:{ln}` `{text.replace('`', '')}`")
                shown += 1
            if len(group) > 5:
                L.append(f"  - ... {len(group) - 5} more")
            if shown > 60:
                L.append("- ... truncated")
                break
    else:
        L.append("None.")
    L.append("")
    if meta["mode"] == "pr":
        L.append("## Existing discussion")
        L.append("")
        L.append(f"{disc['reviews']} review(s), {disc['threads']} inline thread(s) ({disc['unresolved']} unresolved), {disc['comments']} conversation comment(s). Details in `discussion.md`."
                 + (" Re-review: read it before anything else and review the delta." if disc["reviews"] or disc["threads"] else ""))
        if disc.get("thread_note"):
            L.append(disc["thread_note"])
        L.append("")
    L.append("## Files in this directory")
    L.append("")
    L.append("`summary.md` (this) · `description.md` · `linked-issues.md` · `reading-order.md` · `files.tsv` · `commits.md` · "
             + ("`checks.md` · `discussion.md` · " if meta["mode"] == "pr" else "")
             + "`diff.patch` · `meta.json`" + (" · `uncommitted.patch`" if uncommitted else ""))
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------------- PR mode

PR_FIELDS = ("number,title,body,author,baseRefName,headRefName,headRefOid,url,isDraft,state,additions,deletions,"
             "changedFiles,labels,reviewDecision,mergeable,mergeStateStatus,createdAt,updatedAt,commits,statusCheckRollup,"
             "reviews,comments,isCrossRepository,headRepository,headRepositoryOwner")


def gather_pr(repo: str, number: int, out: Path | None, want_diff: bool) -> Path:
    owner, name = repo.split("/", 1)
    pr = gh_json("pr", "view", str(number), "--repo", repo, "--json", PR_FIELDS)
    rest = gh_json("api", f"repos/{repo}/pulls/{number}")
    raw_files = gh_paginate(f"repos/{repo}/pulls/{number}/files")

    out = fresh(out or (CACHE / repo.replace("/", "__") / f"pr-{number}"))

    files = []
    for f in raw_files:
        path = f["filename"]
        files.append({
            "path": path, "status": f.get("status", "modified"), "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0), "bucket": bucket(path), "flags": risk_flags(path),
            "previous": f.get("previous_filename"),
        })
    generated = {f["path"] for f in files if f["bucket"] == "generated"}

    diff_text = ""
    if want_diff:
        try:
            diff_text = gh("pr", "diff", str(number), "--repo", repo)
        except Fail as e:
            # Very large PRs: GitHub stops serving a single diff. Stitch the per-file patches instead.
            parts = []
            for f in raw_files:
                if f.get("patch"):
                    parts.append(f"diff --git a/{f['filename']} b/{f['filename']}\n--- a/{f['filename']}\n+++ b/{f['filename']}\n{f['patch']}\n")
            diff_text = "".join(parts)
            diff_text = f"# NOTE: `gh pr diff` failed ({str(e).splitlines()[-1][:120]}); this diff is stitched from per-file patches and may omit large files.\n" + diff_text
        write(out / "diff.patch", diff_text)

    hand = sum(f["additions"] + f["deletions"] for f in files if f["bucket"] != "generated")
    author = (pr.get("author") or {}).get("login", "?")
    commits = pr.get("commits") or []
    flags_all = sorted({fl for f in files for fl in f["flags"]})
    meta = {
        "mode": "pr", "repo": repo, "number": number, "title": pr.get("title", ""), "url": pr.get("url", ""),
        "author": author, "author_association": rest.get("author_association"),
        "base": pr.get("baseRefName"), "head": pr.get("headRefName"), "head_sha": pr.get("headRefOid", ""),
        "base_sha": (rest.get("base") or {}).get("sha", ""),
        "state": pr.get("state", ""), "is_draft": pr.get("isDraft", False), "is_cross_repository": pr.get("isCrossRepository", False),
        "head_repo": ((rest.get("head") or {}).get("repo") or {}).get("full_name"),
        "created_at": pr.get("createdAt"), "updated_at": pr.get("updatedAt"),
        "additions": pr.get("additions", 0), "deletions": pr.get("deletions", 0), "changed_files": pr.get("changedFiles", len(files)),
        "hand_written_lines": hand, "size_class": size_class(hand),
        "labels": [l.get("name", "") for l in pr.get("labels") or []],
        "review_decision": pr.get("reviewDecision"), "mergeable": pr.get("mergeable"), "merge_state": pr.get("mergeStateStatus"),
        "risk_flags": flags_all, "buckets_present": sorted({f["bucket"] for f in files}),
        "tests_touched": any(f["bucket"] == "tests" for f in files),
        "generated_files": sorted(generated),
        "ai_signals": ai_signals(author, pr.get("body") or "", commits),
        "dependency_bump": is_dependency_bot(author) or bool(BUMP_TITLE_RE.search(pr.get("title") or "")),
        "work_dir": str(out), "gathered_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    meta["suggested_depth"], meta["depth_reasons"] = suggest_depth(meta)

    write(out / "description.md", f"# {pr.get('title', '')}\n\n{pr.get('url', '')}\n\n{(pr.get('body') or '(no description)').strip()}")
    issues_text, issue_titles = linked_issues_md(repo, pr.get("body") or "", author)
    write(out / "linked-issues.md", issues_text)
    write_files_tsv(out, files)
    write(out / "reading-order.md", reading_order_md(files))
    write(out / "commits.md", commits_md(commits))
    checks_text, check_counts = checks_md(pr.get("statusCheckRollup"))
    write(out / "checks.md", checks_text)
    failing = [row.split("|")[1].strip() for row in checks_text.splitlines() if "|" in row and any(
        s in row for s in ("| failure |", "| error |", "| cancelled |", "| timed_out |", "| action_required |"))]
    thread_note = ""
    try:
        threads = fetch_threads(owner, name, number)
    except Fail as e:
        try:
            threads = threads_from_rest(repo, number)
            thread_note = "Resolved/unresolved state unavailable (GraphQL failed; threads rebuilt from the REST comments)."
        except Fail as e2:
            threads = []
            thread_note = f"WARNING: could not fetch inline review threads ({str(e).splitlines()[-1][:100]}; {str(e2).splitlines()[-1][:100]}). Check `gh api repos/{repo}/pulls/{number}/comments` by hand."
    disc_text, disc = discussion_md(pr.get("reviews") or [], threads, pr.get("comments") or [], thread_note)
    write(out / "discussion.md", disc_text)
    hits = scan_diff(diff_text, generated) if diff_text else []
    meta["grep_hits"] = len(hits)
    meta["discussion"] = disc
    write(out / "meta.json", json.dumps(meta, indent=2))
    write(out / "summary.md", summary_md(meta, files, check_counts, failing, hits, disc, issue_titles, pr.get("body") or "", None))
    return out


# ----------------------------------------------------------------------------- local mode

def detect_base(root: str, explicit: str | None, head_branch: str | None = None) -> str:
    """The branch the change will merge into: origin/HEAD, the GitHub default branch, then the usual names.
    A candidate that is the head branch itself (origin/HEAD can point at it in a fresh clone) is skipped."""
    if explicit:
        return explicit
    candidates = []
    ref = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", cwd=root, check=False).strip()
    if ref:
        candidates.append(ref.replace("refs/remotes/", ""))
    try:
        name = gh("repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name", cwd=root).strip()
        if name:
            candidates += [f"origin/{name}", name]
    except Fail:
        pass
    candidates += ["origin/main", "origin/master", "origin/develop", "main", "master", "develop", "trunk"]
    for cand in candidates:
        if head_branch and cand in (head_branch, f"origin/{head_branch}"):
            continue
        if git("rev-parse", "--verify", "--quiet", cand, cwd=root, check=False).strip():
            return cand
    raise Fail("could not determine the base branch; pass --base REF")


STATUS_LETTER = {"A": "added", "M": "modified", "D": "removed", "R": "renamed", "C": "copied", "T": "modified", "U": "modified"}


def gather_local(branch: str | None, base_flag: str | None, out: Path | None, want_diff: bool) -> Path:
    root = git_root()
    if not root:
        raise Fail("not inside a git repository; give a PR number or URL, or run inside the project")
    head = branch or "HEAD"
    if branch and not git("rev-parse", "--verify", "--quiet", branch, cwd=root, check=False).strip():
        raise Fail(f"'{branch}' is neither an open PR nor a local ref")
    branch_name = branch or git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).strip()
    base = detect_base(root, base_flag, branch_name)
    merge_base = git("merge-base", base, head, cwd=root).strip()
    head_sha = git("rev-parse", head, cwd=root).strip()
    if merge_base == head_sha:
        raise Fail(f"'{branch_name}' has no commits beyond {base}; nothing to review (uncommitted changes: use `git diff` directly, or commit first)")

    out = fresh(out or (CACHE / "local" / os.path.basename(root) / re.sub(r"[^\w.-]+", "_", branch_name)))

    numstat = git("diff", "--numstat", f"{merge_base}..{head_sha}", cwd=root)
    namestat = git("diff", "--name-status", "-M", f"{merge_base}..{head_sha}", cwd=root)
    status = {}
    previous = {}
    for line in namestat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0][0] in "RC":
            status[parts[2]] = STATUS_LETTER.get(parts[0][0], "modified")
            previous[parts[2]] = parts[1]
        elif len(parts) >= 2:
            status[parts[1]] = STATUS_LETTER.get(parts[0][0], "modified")
    files = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add, dele, path = parts[0], parts[1], parts[2]
        if "=>" in path:  # rename shown as "old => new" or "dir/{old => new}/file"
            m = re.match(r"(.*)\{(.*) => (.*)\}(.*)", path)
            path = f"{m.group(1)}{m.group(3)}{m.group(4)}" if m else path.split(" => ")[-1]
        files.append({
            "path": path, "status": status.get(path, "modified"),
            "additions": int(add) if add.isdigit() else 0, "deletions": int(dele) if dele.isdigit() else 0,
            "bucket": bucket(path), "flags": risk_flags(path), "previous": previous.get(path),
        })
    generated = {f["path"] for f in files if f["bucket"] == "generated"}

    diff_text = git("diff", f"{merge_base}..{head_sha}", cwd=root) if want_diff else ""
    if want_diff:
        write(out / "diff.patch", diff_text)

    log = git("log", "--reverse", "--format=%H%x1f%an%x1f%ae%x1f%cI%x1f%s%x1f%b%x1e", f"{merge_base}..{head_sha}", cwd=root)
    commits = []
    for rec in log.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        oid, an, ae, date, subject, body = (rec.split("\x1f") + [""] * 6)[:6]
        commits.append({"oid": oid.strip(), "authors": [{"name": an, "login": an}], "committedDate": date,
                        "messageHeadline": subject, "messageBody": body})

    uncommitted = None
    if not branch:  # reviewing the checked-out branch: note working-tree changes
        porcelain = git("status", "--porcelain", "--untracked-files=all", cwd=root)
        if porcelain.strip():
            uncommitted = [l[3:] for l in porcelain.splitlines()]
            write(out / "uncommitted.patch", git("diff", "HEAD", cwd=root) + "\n# untracked:\n" + "\n".join(f"# {p}" for p in uncommitted))

    hand = sum(f["additions"] + f["deletions"] for f in files if f["bucket"] != "generated")
    author = commits[-1]["authors"][0]["name"] if commits else "?"
    meta = {
        "mode": "local", "repo": current_repo(), "repo_root": root, "number": None, "title": f"{branch_name} vs {base}",
        "author": author, "base": base, "head": branch_name, "head_sha": head_sha, "merge_base": merge_base,
        "additions": sum(f["additions"] for f in files), "deletions": sum(f["deletions"] for f in files), "changed_files": len(files),
        "hand_written_lines": hand, "size_class": size_class(hand),
        "risk_flags": sorted({fl for f in files for fl in f["flags"]}), "buckets_present": sorted({f["bucket"] for f in files}),
        "tests_touched": any(f["bucket"] == "tests" for f in files), "generated_files": sorted(generated),
        "ai_signals": ai_signals("", "", commits), "uncommitted": uncommitted or [],
        "work_dir": str(out), "gathered_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    meta["suggested_depth"], meta["depth_reasons"] = suggest_depth(meta)

    description = "\n".join(f"- {c['messageHeadline']}" for c in commits)
    write(out / "description.md", f"# Local review: {branch_name} vs {base}\n\nNo PR description yet. Commit subjects:\n\n{description}")
    write(out / "linked-issues.md", "# Linked issues\n\nNo PR yet; check the commit messages and the ticket the user mentioned.\n")
    write_files_tsv(out, files)
    write(out / "reading-order.md", reading_order_md(files))
    write(out / "commits.md", commits_md(commits))
    hits = scan_diff(diff_text, generated) if diff_text else []
    meta["grep_hits"] = len(hits)
    write(out / "meta.json", json.dumps(meta, indent=2))
    write(out / "summary.md", summary_md(meta, files, Counter(), [], hits, {}, [], "", uncommitted))
    return out


# ----------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="PR number, URL, OWNER/REPO#N, branch, or nothing for the current branch")
    ap.add_argument("-C", dest="path", metavar="PATH", help="run as if started in PATH (the repository to review)")
    ap.add_argument("--repo", help="OWNER/REPO for a bare number or branch")
    ap.add_argument("--base", help="base ref for local reviews")
    ap.add_argument("--out", help="work directory")
    ap.add_argument("--no-diff", action="store_true", help="do not write diff.patch")
    a = ap.parse_args(argv)
    if a.path:
        try:
            os.chdir(a.path)
        except OSError as e:
            print(f"pr-context: cannot enter {a.path}: {e}", file=sys.stderr)
            return 1
    try:
        run(["gh", "auth", "status"])
    except Fail as e:
        if a.target and (URL_RE.search(a.target) or SHORT_RE.match(a.target) or a.target.lstrip("#").isdigit()):
            print(f"GitHub CLI is not authenticated; run `gh auth login`.\n{e}", file=sys.stderr)
            return 1
    try:
        kind, repo, value = parse_target(a.target, a.repo)
        if kind == "branch":
            repo = repo or current_repo()
            if repo:
                found = gh_json("pr", "list", "--repo", repo, "--head", value, "--state", "open", "--json", "number", "--limit", "1")
                if found:
                    kind, value = "pr", found[0]["number"]
        if kind == "pr":
            out = gather_pr(repo, value, Path(a.out) if a.out else None, not a.no_diff)
        else:
            out = gather_local(value if kind == "branch" else None, a.base, Path(a.out) if a.out else None, not a.no_diff)
    except Fail as e:
        print(f"pr-context: {e}", file=sys.stderr)
        return 1
    meta = json.loads((out / "meta.json").read_text())
    print(f"gathered {meta['mode']} review context: {meta.get('title', '')}")
    print(f"size: {meta['hand_written_lines']} hand-written lines ({meta['size_class']}); risk flags: {', '.join(meta['risk_flags']) or 'none'}; suggested depth: {meta['suggested_depth']}")
    print("read summary.md first, then description.md and linked-issues.md")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
