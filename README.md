# woob-deploy

Automation script to upgrade the Woob dependency and cut a Budgea bugfix release on the backend repository.

## Prerequisites

### Required system tools

| Tool   | Purpose                             |
|--------|-------------------------------------|
| `git`  | Branch management, commits and tags |
| `make` | Runs `make update-lock/woob`        |
| `uv`   | Used by `make update-lock/woob` in the backend repo |
| `gh`   | Creates GitHub PRs (optional)       |

### Python >= 3.9

## Installation

```bash
git clone <repo-url> ~/dev/woob_deploy
```

## Usage

The script can be run from any directory.

### Basic command (auto-incremented version)

Automatically increments the patch of the current version (`11.8.18` → `11.8.19`):

```bash
python3 ~/dev/woob_deploy/woob_update_release.py
```

### Full workflow (forge a Woob release first)

Runs `~/dev/woob/dev_tools/release.sh` before the backend update:

```bash
python3 ~/dev/woob_deploy/woob_update_release.py --full
```

### Specify a target version

```bash
python3 ~/dev/woob_deploy/woob_update_release.py --version 11.8.19
```

### Use a different backend repository path

```bash
python3 ~/dev/woob_deploy/woob_update_release.py --repo ~/dev/backend-fork
```

## Automated workflow

| Step | Description |
|------|-------------|
| **0 - Woob release** | (`--full` only) Forges a Woob release by running `dev_tools/release.sh` in `~/dev/woob` |
| **1 - Initialization** | Checks the working tree is clean, checks out `master`, pulls, creates branch `hotfix/X.Y.Z` |
| **2 - Version bump** | Updates the version in `pyproject.toml`, `setup.py`, `budgea/__init__.py` |
| **3 - Woob upgrade** | Runs `make update-lock/woob`, commits `uv.lock` with the new Woob version |
| **4 - Debian changelog** | Prepends an entry directly into `debian/changelog`, pauses for review |
| **5 - Finalize** | Commits the release files, creates the Git tag, prompts to push the branch and tag |
| **6 - Pull Requests** | (Optional) Creates GitHub PRs to `master` and `develop` via `gh` |

## CLI options

```
usage: woob_update_release.py [-h] [--repo PATH] [--version X.Y.Z] [--full]

options:
  --repo PATH      Path to the backend git repository (default: ~/dev/backend)
  --version X.Y.Z  Target version (default: auto-increment current patch)
  --full           Forge a Woob release (~/dev/woob/dev_tools/release.sh) before updating backend
```

## Expected backend repository structure

The script assumes the backend repository contains:

```
backend/
├── budgea/__init__.py     # __version__ = "X.Y.Z"
├── pyproject.toml         # version = "X.Y.Z"
├── setup.py               # version = "X.Y.Z"
├── debian/changelog
└── uv.lock
```

## Debian changelog maintainer

The script reads `user.email` and `user.name` from the Git config to sign the changelog entry. If not set, it falls back to `ci@powens.com` / `Powens CI`.

To use a different identity, set them in your Git config:
```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```
