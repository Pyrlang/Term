#!/usr/bin/env bash
# Publish the built documentation (plan step DOCS-04).
#
# The three Pyrlang sites live in one GitHub Pages repository, one directory
# per project: https://pyrlang.github.io/{pyrlang,term,epmd}/. This script
# replaces this project's directory there with docs-src/build/html and
# touches nothing else. See docs-src/DEPLOY.md.
#
# Environment:
#   DOCS_DEPLOY_REPO     git URL of the site repository
#                        (default git@github.com:Pyrlang/pyrlang.github.io.git)
#   DOCS_DEPLOY_BRANCH   branch that GitHub Pages serves (default main)
#   DOCS_DEPLOY_NAME, DOCS_DEPLOY_EMAIL
#                        author of the deploy commit (default: your git config)
#   DOCS_DEPLOY_DRY_RUN  if set, commit in the temporary clone but do not push
# Credentials are git's own: an SSH key (ssh-agent or GIT_SSH_COMMAND) with
# write access to the site repository. None is read from a file here.

set -euo pipefail

# The directory of the site that belongs to this project.
PROJECT=term

repo=${DOCS_DEPLOY_REPO:-git@github.com:Pyrlang/pyrlang.github.io.git}
branch=${DOCS_DEPLOY_BRANCH:-main}
root=$(cd "$(dirname "$0")/.." && pwd)
html=$root/docs-src/build/html

if [ ! -f "$html/index.html" ] || [ ! -f "$html/objects.inv" ]; then
    echo "deploy-docs: $html is not a finished build; run 'make docs' first" >&2
    exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if ! git clone --quiet --depth 1 --branch "$branch" "$repo" "$work/site" 2>/dev/null; then
    # The site repository has no such branch yet: this is the first deploy.
    git init --quiet --initial-branch "$branch" "$work/site"
    git -C "$work/site" remote add origin "$repo"
fi
cd "$work/site"
[ -n "${DOCS_DEPLOY_NAME:-}" ] && git config user.name "$DOCS_DEPLOY_NAME"
[ -n "${DOCS_DEPLOY_EMAIL:-}" ] && git config user.email "$DOCS_DEPLOY_EMAIL"

publish() {
    # Only this project's directory is replaced; files that are no longer in
    # the build disappear with it.
    rm -rf "${PROJECT:?}"
    mkdir "$PROJECT"
    cp -R "$html/." "$PROJECT/"
    rm -rf "$PROJECT/.doctrees" "$PROJECT/.buildinfo"
    # Without this file GitHub Pages drops directories that start with "_".
    touch .nojekyll
    git add --all -- "$PROJECT" .nojekyll
}

source_rev=$(git -C "$root" rev-parse --short HEAD 2>/dev/null || echo unknown)
publish
if git diff --cached --quiet; then
    echo "deploy-docs: $PROJECT/ is up to date"
    exit 0
fi
git commit --quiet -m "Deploy $PROJECT documentation ($source_rev)"

if [ -n "${DOCS_DEPLOY_DRY_RUN:-}" ]; then
    echo "deploy-docs: dry run, not pushed:"
    git show --stat --oneline HEAD | head -n 20
    exit 0
fi

# A sibling project may deploy at the same moment: take its commit and retry.
for attempt in 1 2 3 4 5; do
    if git push --quiet origin "HEAD:$branch"; then
        echo "deploy-docs: published $PROJECT/ ($source_rev) to $repo"
        exit 0
    fi
    echo "deploy-docs: push rejected, retrying ($attempt)" >&2
    git pull --quiet --rebase origin "$branch"
done
echo "deploy-docs: could not push to $repo" >&2
exit 1
