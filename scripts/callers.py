#!/usr/bin/env python3
"""Blast radius of a diff: which functions, methods, classes and exports it changes, removes, renames or
adds, and where the rest of the repository references the changed and removed ones.

Usage
  callers.py --diff WORK/diff.patch --root WORKTREE [--all] [--max 15] [--json]

  --all     also search references to symbols whose body changed but whose signature did not
  --max N   locations to list per symbol (default 15; the total is always reported)
  --json    machine-readable output

Heuristic by design. It recognises common definition syntax in Python, JavaScript/TypeScript, Go, Rust,
Java, Kotlin, C#, Ruby, PHP, Elixir, shell and SQL, and searches with `git grep -w -F`. A hit is a place
to open, not proof of breakage; zero hits on a short or generic name, or on anything reached through
reflection, dependency injection, string lookups or templates, proves nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

IGNORE_NAMES = {
    # keywords and statement-like words that match method-looking regexes
    "if", "for", "while", "switch", "return", "else", "catch", "try", "function", "new", "await", "async", "typeof",
    "delete", "in", "of", "do", "case", "default", "throw", "yield", "import", "export", "class", "const", "let", "var",
    "elif", "except", "with", "match", "when", "super", "this", "self", "static", "public", "private", "protected",
    "void", "int", "string", "bool", "boolean", "float", "double", "long", "byte", "char", "final", "override",
    "internal", "abstract", "synchronized", "foreach", "using", "namespace", "struct", "enum", "interface", "type",
    "fn", "def", "func", "sub", "end", "then", "begin", "module", "package", "require", "include", "defer", "go",
    "select", "assert", "raise", "print", "println", "echo", "exit", "sizeof", "lambda", "not", "and", "or", "is",
    # test DSL
    "it", "test", "describe", "context", "expect", "beforeEach", "afterEach", "beforeAll", "afterAll", "setup",
    "teardown", "fixture", "mock", "spy", "given", "should", "specify", "scenario", "feature",
    # builtins that show up in conditions
    "len", "cap", "make", "append", "panic", "recover", "copy", "range", "isinstance", "hasattr", "getattr", "str", "int",
    "list", "dict", "tuple", "bool", "float", "set", "repr", "type", "console", "require", "parseInt", "parseFloat",
}
STATEMENT_PREFIX = {"if", "for", "while", "return", "else", "switch", "case", "when", "elif", "unless", "until", "foreach",
                    "await", "yield", "throw", "raise", "assert", "not", "and", "or", "in", "print", "go", "defer", "with"}
GENERIC_NAMES = {
    "main", "init", "new", "get", "set", "run", "start", "stop", "handle", "handler", "render", "index", "update",
    "create", "destroy", "remove", "process", "execute", "call", "apply", "build", "parse", "load", "save", "read",
    "write", "open", "close", "send", "add", "find", "list", "check", "validate", "format", "toString", "equals",
    "hashCode", "constructor", "data", "value", "name", "id", "key", "options", "config", "error", "result", "status",
    "next", "prev", "reset", "clear", "copy", "clone", "size", "length", "count", "map", "filter", "reduce", "sort",
    "String", "Error", "Result", "Option", "Config", "Options", "Context", "Client", "Server", "Handler", "Service",
}

NAME = r"([A-Za-z_$][\w$]*)"
DEF_PATTERNS = [
    # Python
    re.compile(r"^\s*(?:async\s+)?def\s+" + NAME + r"\s*\("),
    re.compile(r"^\s*class\s+" + NAME + r"\b"),
    # JavaScript / TypeScript
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*" + NAME + r"\s*[(<]"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+" + NAME + r"\s*(?::[^=]+?)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::\s*[^=]+?)?=>"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+" + NAME + r"\s*(?::[^=]+?)?=\s*(?:async\s+)?function\b"),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+" + NAME),
    re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+" + NAME + r"\b"),
    # Methods in TS, Java, Kotlin, C#, PHP, Dart: indented `name(args) {` / `name(args): T {` / `name(args) =>`
    re.compile(r"^\s{2,}(?:(?:public|private|protected|internal|static|async|override|final|abstract|readonly|virtual|open|suspend|synchronized|export|default|native|unsafe|extern|partial|sealed|get|set)\s+)*"
               r"(?:[A-Za-z_][\w<>\[\],.?$ ]*?\s+)?" + NAME + r"\s*\([^;{}]*\)\s*(?::\s*[\w<>\[\]|&,.? ]+)?\s*(?:throws\s+[\w.,\s]+)?\s*(?:\{|=>|$)"),
    # Go
    re.compile(r"^func\s+(?:\([^)]*\)\s*)?" + NAME + r"\s*[(\[]"),
    re.compile(r"^type\s+" + NAME + r"\s+"),
    # Rust
    re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:const\s+)?(?:unsafe\s+)?(?:extern\s+\"[^\"]*\"\s+)?fn\s+" + NAME),
    re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|type|union|mod)\s+" + NAME + r"\b"),
    # Kotlin
    re.compile(r"^\s*(?:(?:public|private|protected|internal|override|open|suspend|inline|operator|infix|abstract|final|tailrec)\s+)*fun\s+(?:<[^>]+>\s+)?(?:[\w.<>?]+\.)?" + NAME + r"\s*\("),
    # Java / Kotlin / C# / Scala / Swift types
    re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|sealed|data|open|partial|export|actor)\s+)*(?:class|interface|enum|object|record|trait|struct|protocol|extension)\s+" + NAME + r"\b"),
    # Ruby
    re.compile(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!=]?)"),
    re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)"),
    # PHP
    re.compile(r"^\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?" + NAME + r"\s*\("),
    # Shell
    re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{"),
    # Elixir
    re.compile(r"^\s*defp?\s+([a-z_]\w*[?!]?)"),
    # SQL
    re.compile(r"(?i)^\s*create\s+(?:or\s+replace\s+)?(?:unique\s+)?(?:table|view|materialized\s+view|function|procedure|index|type|trigger)\s+(?:concurrently\s+)?(?:if\s+not\s+exists\s+)?(?:\w+\.)?\"?([A-Za-z_]\w*)\"?"),
]
CALL_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")

EXCLUDE_RE = re.compile(
    r"(^|/)(node_modules|vendor|dist|build|out|target|\.git|__pycache__|\.next|\.nuxt|\.venv|venv|coverage|\.cache|third_party)(/|$)"
    r"|\.(lock|min\.js|min\.css|map|snap|svg|png|jpg|jpeg|gif|pdf|woff2?|ico)$"
    r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock|poetry\.lock|composer\.lock|Gemfile\.lock)$"
)
TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|e2e|testdata|fixtures|__mocks__)(/|$)|(\.|_)(test|spec|tests)\.[a-z]+$"
    r"|(^|/)test_[^/]+\.py$|_test\.(go|rs|rb|ex|exs)$|Tests?\.(java|kt|cs|swift|scala)$"
)


def def_name(line: str) -> str | None:
    for rx in DEF_PATTERNS:
        m = rx.match(line)
        if m:
            name = m.group(1)
            if name in IGNORE_NAMES or len(name) < 2:
                return None
            # `if len(x) > 0 && ok(y) {` looks like a method definition to the generic pattern; a statement keyword
            # before the name says it is not one
            prefix = line[: m.start(1)].strip().split()
            if prefix and prefix[0] in STATEMENT_PREFIX:
                return None
            return name
    return None


def hunk_name(context: str) -> str | None:
    if not context.strip():
        return None
    n = def_name(context)
    if n:
        return n
    for m in CALL_RE.finditer(context):
        if m.group(1) not in IGNORE_NAMES and len(m.group(1)) >= 2:
            return m.group(1)
    return None


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lstrip("+-").strip())


def parse_diff(text: str) -> dict:
    files: dict[str, dict] = {}
    path = None
    old_path = None
    for raw in text.splitlines():
        if raw.startswith("diff --git"):
            path, old_path = None, None
            continue
        if raw.startswith("--- "):
            p = raw[4:].strip()
            old_path = None if p == "/dev/null" else (p[2:] if p.startswith("a/") else p)
            continue
        if raw.startswith("+++ "):
            p = raw[4:].strip()
            new = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            path = new or old_path
            if path:
                files.setdefault(path, {"removed": [], "added": [], "hunks": [], "deleted": new is None, "new_file": old_path is None})
            continue
        if path is None:
            continue
        if raw.startswith("@@"):
            m = HUNK_RE.match(raw)
            if m:
                n = hunk_name(m.group(5))
                if n:
                    files[path]["hunks"].append(n)
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            n = def_name(raw[1:])
            if n:
                files[path]["removed"].append((n, raw[1:]))
        elif raw.startswith("+") and not raw.startswith("+++"):
            n = def_name(raw[1:])
            if n:
                files[path]["added"].append((n, raw[1:]))
    return files


def classify(files: dict) -> dict:
    out = {"changed": [], "removed": [], "renamed": [], "new": [], "touched": []}
    for path, f in files.items():
        removed = {}
        for n, line in f["removed"]:
            removed.setdefault(n, line)
        added = {}
        for n, line in f["added"]:
            added.setdefault(n, line)
        for n in removed.keys() & added.keys():
            if norm(removed[n]) != norm(added[n]):
                out["changed"].append({"name": n, "path": path, "before": norm(removed[n]), "after": norm(added[n])})
        only_removed = {n: l for n, l in removed.items() if n not in added}
        only_added = {n: l for n, l in added.items() if n not in removed}
        # rename: same definition line with only the name swapped
        for rn, rl in list(only_removed.items()):
            for an, al in list(only_added.items()):
                if norm(rl).replace(rn, "\0") == norm(al).replace(an, "\0"):
                    out["renamed"].append({"name": rn, "to": an, "path": path})
                    only_removed.pop(rn, None)
                    only_added.pop(an, None)
                    break
        for n, l in only_removed.items():
            out["removed"].append({"name": n, "path": path, "before": norm(l), "deleted_file": f["deleted"]})
        for n, l in only_added.items():
            out["new"].append({"name": n, "path": path, "after": norm(l)})
        seen = set(removed) | set(added)
        for n in f["hunks"]:
            if n not in seen:
                seen.add(n)
                out["touched"].append({"name": n, "path": path})
    return out


def is_git_root(root: Path) -> bool:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True).returncode == 0


def grep(root: Path, sym: str, use_git: bool) -> list[tuple[str, int, str]]:
    if use_git:
        cmd = ["git", "-C", str(root), "grep", "-n", "-w", "-F", "-I", "--no-color", "-e", sym, "--", "."]
    else:
        cmd = ["grep", "-rnwIF", "--exclude-dir=.git", "--exclude-dir=node_modules", "--exclude-dir=vendor",
               "--exclude-dir=dist", "--exclude-dir=build", "--exclude-dir=target", "-e", sym, "."]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(root))
    if p.returncode not in (0, 1):
        sys.exit(f"callers: search failed: {p.stderr.strip()}")
    hits = []
    for line in p.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path = parts[0][2:] if parts[0].startswith("./") else parts[0]
        if EXCLUDE_RE.search(path):
            continue
        hits.append((path, int(parts[1]) if parts[1].isdigit() else 0, parts[2].strip()[:140]))
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--diff", required=True, help="unified diff (WORK/diff.patch)")
    ap.add_argument("--root", required=True, help="checkout of the PR head (the worktree)")
    ap.add_argument("--all", action="store_true", help="also search symbols whose body changed but not their signature")
    ap.add_argument("--max", type=int, default=15, help="locations to list per symbol")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    if not root.is_dir():
        sys.exit(f"callers: {root} is not a directory")
    diff_text = Path(a.diff).read_text(errors="replace")
    files = parse_diff(diff_text)
    cls = classify(files)
    use_git = is_git_root(root)

    to_search = [("signature changed", s) for s in cls["changed"]] + [("removed", s) for s in cls["removed"]] \
        + [("renamed", s) for s in cls["renamed"]]
    if a.all:
        to_search += [("body changed", s) for s in cls["touched"]]
    truncated = False
    if len(to_search) > 80:
        to_search, truncated = to_search[:80], True

    results = []
    for kind, s in to_search:
        name = s["name"]
        hits = grep(root, name, use_git)
        external = [h for h in hits if h[0] != s["path"]]
        same_file = [h for h in hits if h[0] == s["path"]]
        tests = [h for h in external if TEST_RE.search(h[0])]
        results.append({
            "kind": kind, "name": name, "path": s["path"], "to": s.get("to"), "before": s.get("before"), "after": s.get("after"),
            "deleted_file": s.get("deleted_file", False),
            "external_refs": len(external), "external_files": len({h[0] for h in external}), "test_refs": len(tests),
            "same_file_refs": len(same_file), "generic": name in GENERIC_NAMES or len(name) <= 3,
            "locations": [{"path": p, "line": l, "text": t, "definition": def_name(t) == name} for p, l, t in external[: a.max]],
            "other_definitions": sum(1 for _, _, t in external if def_name(t) == name),
        })

    if a.json:
        print(json.dumps({"results": results, "new": cls["new"], "touched": cls["touched"], "truncated": truncated}, indent=2))
        return 0

    print(f"Blast radius from {a.diff} against {root}{'' if use_git else ' (plain grep; not a git checkout)'}")
    print()
    if not results and not cls["new"] and not cls["touched"]:
        print("No function, class or export definitions recognised in the diff. Check the callers of the changed code by hand.")
        return 0
    for kind in ("signature changed", "removed", "renamed", "body changed"):
        group = [r for r in results if r["kind"] == kind]
        if not group:
            continue
        print(f"== {kind} ({len(group)}) ==")
        for r in sorted(group, key=lambda x: -x["external_refs"]):
            head = f"  {r['name']}"
            if r["to"]:
                head += f" -> {r['to']}"
            head += f"   [{r['path']}]"
            if r["deleted_file"]:
                head += "  (file deleted)"
            print(head)
            if r["before"] and r["after"] and kind == "signature changed":
                print(f"      - {r['before'][:150]}")
                print(f"      + {r['after'][:150]}")
            note = f"{r['external_refs']} ref(s) in {r['external_files']} other file(s), {r['test_refs']} in tests; {r['same_file_refs']} in the same file"
            if r["generic"]:
                note += "  (generic or short name: expect noise, and do not trust zero)"
            if r["external_refs"] == 0 and not r["generic"]:
                note += "  (no other references found: dead code, or reached dynamically?)"
            print(f"      {note}")
            if r["other_definitions"]:
                print(f"      ({r['other_definitions']} of these are other definitions with the same name, e.g. the same function in another package)")
            for loc in r["locations"]:
                print(f"        {loc['path']}:{loc['line']}: {loc['text']}{'   <- another definition' if loc['definition'] else ''}")
            if r["external_refs"] > len(r["locations"]):
                print(f"        ... {r['external_refs'] - len(r['locations'])} more (raise --max)")
        print()
    if cls["touched"] and not a.all:
        names = sorted({t["name"] for t in cls["touched"]})
        print(f"== body changed, signature unchanged ({len(names)}) ==  (callers not searched; pass --all)")
        print("  " + ", ".join(names[:40]) + (" ..." if len(names) > 40 else ""))
        print()
    if cls["new"]:
        names = sorted({n["name"] for n in cls["new"]})
        print(f"== new definitions ({len(names)}) ==")
        print("  " + ", ".join(names[:40]) + (" ..." if len(names) > 40 else ""))
        print()
    if truncated:
        print("(symbol list truncated at 80; review the rest by hand)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
