#!/usr/bin/env bash
# Scenario tests for the shell block inlined in the commit-docs step of
# superpowers-lite-build.
#
# The block is cut out of its Markdown file exactly as an agent would copy it,
# so editing the step text without updating these scenarios fails here.
# Run: bash tests/step-blocks.test.sh (needs git).

set -uo pipefail

PACK="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "${TMP:?}"' EXIT

block() { # markdown file: the first indented ```sh block, unindented
    awk '/^   ```sh$/{f=1;next} /^   ```$/{if(f)exit} f' "$1" | sed 's/^   //'
}
DOCS=$(block "$PACK/assets/workflows/superpowers-lite-build/commit-docs.md" | sed 's#{{docs_dir}}#docs/build#g')
[[ -n "$DOCS" ]] || { echo "FAIL could not extract the commit-docs block"; exit 1; }

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

git init -q -b main "$TMP/repo"
git -C "$TMP/repo" commit -q --allow-empty -m base
export GC_RIG_ROOT="$TMP/repo"
git -C "$TMP/repo" worktree add -q --detach "$TMP/wt-a" main
(cd "$TMP/wt-a" && echo a > a.txt && git add . && git commit -q -m a)

failures=0
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
tip() { git -C "$TMP/repo" rev-parse "refs/heads/$1" 2>/dev/null; }
head_of() { git -C "$TMP/wt-$1" rev-parse HEAD; }

# Commits past an ignore rule, refuses a moved or checked-out branch.
for f in r d f; do echo "$f" > "$TMP/$f.md"; done
printf 'build/\n' > "$TMP/wt-a/.gitignore"
(cd "$TMP/wt-a" && git add .gitignore && git commit -q -m ignore)
git -C "$TMP/repo" update-ref refs/heads/lite/a "$(head_of a)"
docs() { # want (0 or fail: any non-zero exit) description commit root
    local rc
    env BRANCH=lite/a COMMIT="$3" ROOT="$4" REQUIREMENTS="$TMP/r.md" DESIGN="$TMP/d.md" \
        FINAL_REPORT="$TMP/f.md" SUBJECT="docs: add" BODY=body TRAILERS="Bead: s-1" \
        bash -c "$DOCS" >/dev/null 2>&1; rc=$?
    if [[ $1 == fail && $rc != 0 || $rc == "$1" ]]; then echo "ok   $2"; else fail "$2: want $1, got $rc"; fi
    [[ $(git -C "$TMP/repo" worktree list | grep -c '/docs ') == 0 ]] || fail "$2: left its worktree behind"
}
old=$(tip lite/a)
docs 0 "commit-docs commits under an ignored directory" "$old" w-1
[[ $(git -C "$TMP/repo" ls-tree -r --name-only lite/a docs/build/w-1 | wc -l) == 3 ]] || fail "commit-docs did not commit three documents"
git -C "$TMP/repo" log -1 --format=%B lite/a | grep -qx 'Bead: s-1' || fail "commit-docs lost the Bead trailer"
docs fail "commit-docs refuses a branch that moved" "$old" w-2
git -C "$TMP/repo" worktree add -q "$TMP/wt-lite-a" lite/a
docs fail "commit-docs refuses a checked-out branch" "$(tip lite/a)" w-3

if (( failures > 0 )); then
    echo "$failures failure(s)"
    exit 1
fi
echo "all step block scenarios pass"
