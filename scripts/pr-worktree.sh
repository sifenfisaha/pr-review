#!/usr/bin/env bash
# Check a pull request (or a branch) out into its own detached worktree so it can be read, grepped,
# built and tested without touching the checkout the user is working in.
#
# usage: pr-worktree.sh <pr-number | PR URL | OWNER/REPO#N> [--repo OWNER/REPO] [-C /path/to/repo] [--cleanup]
#        pr-worktree.sh --branch <name> [--repo OWNER/REPO] [-C /path/to/repo] [--cleanup]
#
# Where the code comes from:
#   inside a clone of the same repository  -> a worktree of that clone; the only change to the clone is a
#                                             ref under refs/pr-review/ (hidden from `git branch`) and the
#                                             worktree registration, both removed by --cleanup
#   anywhere else                          -> a blobless, no-checkout clone kept in ~/.cache/pr-review/repos/,
#                                             then a worktree of it
#   a repository with no GitHub remote     -> --branch NAME clones the local checkout into a scratch copy,
#                                             leaving the repository untouched
# Worktrees live in ~/.cache/pr-review/worktrees/<owner>__<repo>/pr-<n>. Re-running updates an existing
# worktree to the PR's current head. --cleanup removes the worktree and the ref.
#
# The worktree path is printed on the last line of stdout; everything else goes to stderr.
set -euo pipefail

CACHE="${PR_REVIEW_CACHE:-$HOME/.cache/pr-review}"
PR="" BRANCH="" REPO="" CLEANUP=0

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//' >&2; exit "${1:-2}"; }
log() { echo "pr-worktree: $*" >&2; }
https_url() { echo "$(gh repo view "$REPO" --json url --jq .url).git"; }
# fetch REFSPECS... from the remote; if that fails (SSH timeouts are common on some networks), retry over HTTPS
fetch_refs() {
  if ! git -C "$SRC" fetch --no-tags --quiet "$REMOTE" "$@" 2>/tmp/pr-worktree-fetch.$$; then
    log "fetch from $REMOTE failed ($(tail -1 /tmp/pr-worktree-fetch.$$ 2>/dev/null)); retrying over HTTPS"
    git -C "$SRC" fetch --no-tags --quiet "$(https_url)" "$@"
  fi
  rm -f /tmp/pr-worktree-fetch.$$
}

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    -C) cd "${2:?-C needs a path}" || exit 2; shift 2 ;;
    --cleanup) CLEANUP=1; shift ;;
    -h|--help) usage 0 ;;
    *)
      if [[ "$1" =~ ^#?([0-9]+)$ ]]; then PR="${BASH_REMATCH[1]}"
      elif [[ "$1" =~ github\.com/([^/]+)/([^/]+)/pull/([0-9]+) ]]; then REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]%.git}"; PR="${BASH_REMATCH[3]}"
      elif [[ "$1" =~ ^([^/#[:space:]]+)/([^/#[:space:]]+)#([0-9]+)$ ]]; then REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"; PR="${BASH_REMATCH[3]}"
      else echo "pr-worktree: unrecognised argument: $1" >&2; usage; fi
      shift ;;
  esac
done
[ -n "$PR" ] || [ -n "$BRANCH" ] || usage

command -v git >/dev/null || { echo "pr-worktree: git is required" >&2; exit 1; }
HAVE_GH=1; command -v gh >/dev/null 2>&1 || HAVE_GH=0   # only needed when a GitHub repository is involved
need_gh() { [ "$HAVE_GH" = 1 ] || { echo "pr-worktree: the GitHub CLI (gh) is required to work with GitHub pull requests; install it from https://cli.github.com and run 'gh auth login'" >&2; exit 1; }; }

# ---------------------------------------------------------------- which repository, which clone
CWD_ROOT="" CWD_REPO=""
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  CWD_ROOT="$(git rev-parse --show-toplevel)"
  [ "$HAVE_GH" = 1 ] && CWD_REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
fi
[ -n "$REPO" ] || REPO="$CWD_REPO"

if [ -z "$REPO" ]; then
  # No GitHub repository in sight. A branch of the local repository can still be reviewed from a clone of it.
  if [ -n "$CWD_ROOT" ] && [ -n "$BRANCH" ]; then
    SAFE="$(printf '%s' "$BRANCH" | tr -c 'A-Za-z0-9._-' '_')"
    WT="$CACHE/worktrees/local__$(basename "$CWD_ROOT")/branch-$SAFE"
    if [ "$CLEANUP" = 1 ]; then rm -rf "$WT"; log "removed $WT"; exit 0; fi
    SHA="$(git -C "$CWD_ROOT" rev-parse --verify --quiet "refs/heads/$BRANCH^{commit}" 2>/dev/null || git -C "$CWD_ROOT" rev-parse --verify --quiet "$BRANCH^{commit}" 2>/dev/null || true)"
    [ -n "$SHA" ] || { echo "pr-worktree: branch '$BRANCH' not found in $CWD_ROOT" >&2; exit 1; }
    if git -C "$WT" rev-parse --git-dir >/dev/null 2>&1; then
      git -C "$WT" fetch --quiet origin 2>/dev/null || true
      git -C "$WT" checkout --detach --force --quiet "$SHA"
      log "updated clone to $(git -C "$WT" rev-parse --short HEAD)"
    else
      rm -rf "$WT"; mkdir -p "$(dirname "$WT")"
      git clone --quiet --no-checkout "$CWD_ROOT" "$WT"
      git -C "$WT" checkout --detach --quiet "$SHA"
      log "cloned your checkout (no GitHub remote found) to a scratch copy at $(git -C "$WT" rev-parse --short HEAD); your repository was not modified"
    fi
    for cand in main master develop trunk; do
      if B="$(git -C "$CWD_ROOT" rev-parse --verify --quiet "$cand^{commit}" 2>/dev/null)"; then
        MB="$(git -C "$CWD_ROOT" merge-base "$B" "$SHA" 2>/dev/null || true)"
        [ -n "$MB" ] && log "base guess: $cand (merge-base ${MB:0:12}); inside the scratch copy: git diff ${MB:0:12}..HEAD"
        break
      fi
    done
    log "run tests and greps inside the scratch copy"
    echo "$WT"
    exit 0
  elif [ -n "$CWD_ROOT" ] && [ -n "$PR" ]; then
    echo "pr-worktree: this repository has no GitHub remote that gh can see; pass --repo OWNER/REPO for PR $PR" >&2; exit 2
  fi
  echo "pr-worktree: cannot tell which repository; run inside a clone, pass --repo OWNER/REPO, or use --branch inside a local repository" >&2; exit 2
fi
need_gh
SLUG="${REPO//\//__}"

REMOTE="origin"
if [ -n "$CWD_REPO" ] && [ "${CWD_REPO,,}" = "${REPO,,}" ]; then
  SRC="$(git rev-parse --show-toplevel)"
  # Prefer the remote that actually points at this repository (it may be called upstream).
  while read -r name url _; do
    if [[ "${url,,}" =~ github\.com[:/]${SLUG//__//}(\.git)?/?$ ]]; then REMOTE="$name"; break; fi
  done < <(git -C "$SRC" remote -v | awk '$3=="(fetch)"')
  log "using your clone at $SRC (remote: $REMOTE)"
else
  SRC="$CACHE/repos/$SLUG"
  if ! git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
    mkdir -p "$(dirname "$SRC")"
    log "cloning $REPO (blobless, no checkout) into $SRC"
    if ! gh repo clone "$REPO" "$SRC" -- --filter=blob:none --no-checkout --quiet 2>/dev/null; then
      rm -rf "$SRC"
      log "clone over your default protocol failed; retrying over HTTPS"
      git clone --filter=blob:none --no-checkout --quiet "$(https_url)" "$SRC"
    fi
  else
    log "using cached clone at $SRC"
  fi
fi

# ---------------------------------------------------------------- refs and worktree path
if [ -n "$PR" ]; then
  REF="refs/pr-review/pr-$PR"
  WT="$CACHE/worktrees/$SLUG/pr-$PR"
else
  SAFE="$(printf '%s' "$BRANCH" | tr -c 'A-Za-z0-9._-' '_')"
  REF="refs/pr-review/branch-$SAFE"
  WT="$CACHE/worktrees/$SLUG/branch-$SAFE"
fi

if [ "$CLEANUP" = 1 ]; then
  if [ -d "$WT" ]; then
    git -C "$SRC" worktree remove --force "$WT" 2>/dev/null || rm -rf "$WT"
  fi
  git -C "$SRC" worktree prune
  git -C "$SRC" update-ref -d "$REF" 2>/dev/null || true
  log "removed $WT"
  exit 0
fi

# ---------------------------------------------------------------- fetch
BASE=""
if [ -n "$PR" ]; then
  read -r BASE HEAD_SHA < <(gh pr view "$PR" --repo "$REPO" --json baseRefName,headRefOid --jq '[.baseRefName, .headRefOid] | @tsv')
  log "fetching pull/$PR/head ($HEAD_SHA) and base '$BASE' from $REMOTE"
  fetch_refs "+refs/pull/$PR/head:$REF" "+refs/heads/$BASE:refs/pr-review/base-$BASE"
else
  if fetch_refs "+refs/heads/$BRANCH:$REF" 2>/dev/null; then
    log "fetched branch '$BRANCH' from $REMOTE"
  elif git -C "$SRC" rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
    git -C "$SRC" update-ref "$REF" "refs/heads/$BRANCH"
    log "using local branch '$BRANCH'"
  else
    echo "pr-worktree: branch '$BRANCH' not found on $REMOTE or locally" >&2; exit 1
  fi
  HEAD_SHA="$(git -C "$SRC" rev-parse "$REF")"
  BASE="$(gh repo view "$REPO" --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null || echo main)"
  fetch_refs "+refs/heads/$BASE:refs/pr-review/base-$BASE" 2>/dev/null || true
fi

# ---------------------------------------------------------------- create or update the worktree
if [ -d "$WT" ] && git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$WT" checkout --detach --force --quiet "$REF"
  log "updated worktree to $(git -C "$WT" rev-parse --short HEAD)"
else
  if [ -d "$WT" ]; then rm -rf "$WT"; git -C "$SRC" worktree prune; fi
  mkdir -p "$(dirname "$WT")"
  git -C "$SRC" worktree add --detach --quiet "$WT" "$REF"
  log "created worktree at $(git -C "$WT" rev-parse --short HEAD)"
fi

MB=""
if [ -n "$BASE" ] && git -C "$SRC" rev-parse --verify --quiet "refs/pr-review/base-$BASE" >/dev/null; then
  MB="$(git -C "$SRC" merge-base "refs/pr-review/base-$BASE" "$REF" 2>/dev/null || true)"
fi
log "head: $HEAD_SHA"
[ -n "$BASE" ] && log "base: $BASE${MB:+ (merge-base ${MB:0:12})}"
if [ -n "$MB" ] && [ "$MB" = "$HEAD_SHA" ]; then
  log "the head is already contained in $BASE (merged or fast-forwarded); use diff.patch from pr-context.py for the change itself"
elif [ -n "$MB" ]; then
  log "diff against base from inside the worktree: git diff ${MB:0:12}..HEAD"
fi
log "run tests and greps inside the worktree; your own checkout is untouched"
echo "$WT"
