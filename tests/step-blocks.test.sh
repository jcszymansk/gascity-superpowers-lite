#!/usr/bin/env bash
# Scenario tests for the shell blocks inlined in step texts: the land step of
# superpowers-lite-work-item and the commit-docs step of superpowers-lite-build.
#
# Each block is cut out of its Markdown file exactly as an agent would copy it,
# so editing a step text without updating these scenarios fails here. A stub
# `gc` answers the task-review query from <tmp>/review-<root>.json.
# Run: bash tests/step-blocks.test.sh (needs git and jq).

set -uo pipefail

PACK="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "${TMP:?}"' EXIT

block() { # markdown file: the first indented ```sh block, unindented
    awk '/^   ```sh$/{f=1;next} /^   ```$/{if(f)exit} f' "$1" | sed 's/^   //'
}
LAND=$(block "$PACK/assets/workflows/superpowers-lite-work-item/land.md")
DOCS=$(block "$PACK/assets/workflows/superpowers-lite-build/commit-docs.md" | sed 's#{{docs_dir}}#docs/build#g')
[[ -n "$LAND" && -n "$DOCS" ]] || { echo "FAIL could not extract the step blocks"; exit 1; }

mkdir "$TMP/bin"
cat > "$TMP/bin/gc" <<'EOF'
#!/usr/bin/env bash
[[ "$1 $2" == "bd list" ]] || exit 9
for arg in "$@"; do
    if [[ "$arg" == gc.root_bead_id=* ]]; then cat "$STUB_DIR/review-${arg#gc.root_bead_id=}.json"; fi
done
EOF
chmod +x "$TMP/bin/gc"
export PATH="$TMP/bin:$PATH" STUB_DIR="$TMP"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t

git init -q -b main "$TMP/repo"
git -C "$TMP/repo" commit -q --allow-empty -m base
export GC_RIG_ROOT="$TMP/repo"
BASE0=$(git -C "$TMP/repo" rev-parse main)

failures=0
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
review() { # root outcome...
    local root=$1; shift
    printf '%s\n' "$@" | jq -R '{metadata: {"gc.outcome": .}}' | jq -s . > "$TMP/review-$root.json"
}
item() { # name base [commit]: a worktree at base, one commit unless told not to
    git -C "$TMP/repo" worktree add -q --detach "$TMP/wt-$1" "$2"
    if [[ "${3:-commit}" == commit ]]; then
        (cd "$TMP/wt-$1" && echo "$1" > "$1.txt" && git add . && git commit -q -m "$1")
    fi
    review "r-$1" pass
}
land() { # want-rc description name target base
    local out rc
    out=$(env ITEM_ROOT="r-$3" WT="$TMP/wt-$3" TARGET="$4" BASE="$5" bash -c "$LAND" 2>&1); rc=$?
    if [[ $rc == "$1" ]]; then echo "ok   $2"; else fail "$2: want $1, got $rc: $out"; fi
    LAST="$out"
}
tip() { git -C "$TMP/repo" rev-parse "refs/heads/$1" 2>/dev/null; }
head_of() { git -C "$TMP/wt-$1" rev-parse HEAD; }

# Land: a fresh target is created, a shared one fast-forwards, siblings are refused.
item a "$BASE0"
land 0 "a missing target is created at the item" a lite/a "$BASE0"
[[ $(tip lite/a) == $(head_of a) ]] || fail "lite/a is not at a"
[[ "$LAST" == *"LANDED=$(head_of a)"* ]] || fail "land did not print LANDED for a"
land 0 "landing again moves nothing" a lite/a "$BASE0"

git -C "$TMP/repo" branch shared "$BASE0"
item b "$BASE0"; item c "$BASE0"
land 0 "a shared target fast-forwards" b shared "$BASE0"
before=$(tip shared)
land 1 "a sibling from the same base is refused" c shared "$BASE0"
[[ $(tip shared) == "$before" ]] || fail "a refused land moved shared"

item d "$(tip shared)"; review r-d fail
land 1 "a failed review is refused" d shared "$(git -C "$TMP/wt-d" rev-parse HEAD~1)"
review r-d pass pass
land 1 "two task reviews are refused" d shared "$(git -C "$TMP/wt-d" rev-parse HEAD~1)"
printf '[]' > "$TMP/review-r-d.json"
land 1 "no task review is refused" d shared "$(git -C "$TMP/wt-d" rev-parse HEAD~1)"
[[ $(tip shared) == "$before" ]] || fail "a refused review moved shared"

item e "$(tip shared)"; echo junk > "$TMP/wt-e/untracked"
land 1 "a dirty worktree is refused" e shared "$(git -C "$TMP/wt-e" rev-parse HEAD~1)"

item f "$(tip shared)" none
land 0 "an approved item without a commit lands as nothing to move" f shared "$(tip shared)"
[[ "$LAST" == *"LANDED=$(tip shared)"* ]] || fail "a no-commit land did not report the target's commit"
item g "$BASE0" none
land 1 "an item without a commit and no target is refused" g lite/g "$BASE0"
tip lite/g >/dev/null && fail "a refused land created lite/g"

item h "$(tip shared)"
git -C "$TMP/repo" worktree add -q "$TMP/wt-shared" shared
land 1 "a checked-out target is refused" h shared "$(git -C "$TMP/wt-h" rev-parse HEAD~1)"
git -C "$TMP/repo" worktree remove "$TMP/wt-shared"
land 1 "a base the item does not descend from is refused" h shared "$(head_of a)"

# Commit-docs: commits past an ignore rule, refuses a moved or checked-out branch.
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
