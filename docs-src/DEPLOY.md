# Publishing the documentation

## Where it lives

| What | Where |
| --- | --- |
| This site | <https://pyrlang.github.io/term/> |
| Sibling sites | <https://pyrlang.github.io/pyrlang/>, <https://pyrlang.github.io/epmd/> |
| Landing page | <https://pyrlang.github.io/> (kept in the Pyrlang repository, `docs-src/landing/index.html`) |
| Host | GitHub Pages, serving the branch `main` of the repository `Pyrlang/pyrlang.github.io` |
| Owner of host and domain | the owners of the GitHub organisation `Pyrlang` |

All three sites are directories of that one repository: `term/`,
`pyrlang/`, `epmd/`. Each project replaces only its own directory. One
version is published: the default branch.

The paths are lower case. GitHub Pages paths are case-sensitive, and the
old sites `pyrlang.github.io/Pyrlang/` and `/Term/` were project sites
served from `docs/` of those repositories; they are switched off (see
"One-time setup").

## How a deploy happens

`.github/workflows/docs.yml` builds the documentation on every push and
pull request. On a push to `master` of `Pyrlang/Term`, its `deploy` job
then runs `tools/deploy-docs.sh` with the built HTML. Pull requests and
forks never deploy.

The script clones the site repository, replaces `term/` with
`docs-src/build/html`, commits and pushes. If a sibling project pushed in
between, it rebases and retries.

## By hand

With write access to `Pyrlang/pyrlang.github.io` through your SSH key:

```sh
pip install -e . --group docs
rm -rf docs-src/build   # Sphinx keeps pages of deleted sources otherwise
make docs               # python -m sphinx -W --keep-going -b html docs-src/source docs-src/build/html
make docs-deploy        # tools/deploy-docs.sh
```

`DOCS_DEPLOY_DRY_RUN=1 make docs-deploy` shows what would be committed
without pushing.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOCS_DEPLOY_REPO` | `git@github.com:Pyrlang/pyrlang.github.io.git` | the site repository |
| `DOCS_DEPLOY_BRANCH` | `main` | the branch GitHub Pages serves |
| `DOCS_DEPLOY_NAME`, `DOCS_DEPLOY_EMAIL` | your git configuration | author of the deploy commit |
| `DOCS_DEPLOY_DRY_RUN` | unset | commit locally, do not push |
| `PYRLANG_DOCS_BASE_URL` | `https://pyrlang.github.io` | read by `conf.py` at build time: the base of the links between the sites |

No credential is stored in this repository. Git uses your SSH key, or in
CI the deploy key described below.

## Rolling back

Check out the commit whose documentation you want, build and deploy it by
hand as above. Or revert the deploy commit in `Pyrlang/pyrlang.github.io`:
every deploy is one commit that touches one directory.

## One-time setup (organisation owners)

1. Create the public repository `Pyrlang/pyrlang.github.io` with a branch
   `main`. In its settings, Pages: deploy from the branch `main`, folder
   `/`. An empty repository is enough; the first deploy creates the files.
2. Create one SSH key pair without a passphrase
   (`ssh-keygen -t ed25519 -f docs-deploy -N ""`). Add the public key to
   `Pyrlang/pyrlang.github.io` as a deploy key with write access.
3. In each of `Pyrlang/Pyrlang`, `Pyrlang/Term` and `Pyrlang/Epmd`: create
   the environment `docs`, restrict it to the branch `master`, and add the
   private key to it as the secret `DOCS_DEPLOY_KEY`. Delete the key files
   afterwards.
4. Switch off the old sites: in `Pyrlang/Pyrlang` and `Pyrlang/Term`,
   settings, Pages: unpublish (source "None"). Their `docs/` directories
   are already gone from the repositories.

The order of the first deploys does not matter: Pyrlang's build reads the
object inventories of Term and Epmd from builds of their sources, not from
the published sites.
