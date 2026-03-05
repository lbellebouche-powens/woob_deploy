# woob-deploy

Automation script to upgrade the Woob dependency and cut a Budgea bugfix release on the backend repository.

## Prerequisites

### Required system tools

| Tool        | Purpose                                          |
|-------------|--------------------------------------------------|
| `git`       | Branch management, commits and tags              |
| `make`      | Runs `make update-lock/woob`                     |
| `uv`        | Python package manager                           |
| `debchange` | Updates the Debian changelog (`devscripts`)      |
| `gh`        | Creates GitHub PRs (optional)                    |

Install Debian tools:
```bash
apt install devscripts
```

### Python >= 3.9

## Installation

```bash
git clone <repo-url> woob_deploy
cd woob_deploy
uv sync
```

## Usage

### Basic command (auto-incremented version)

Automatically increments the patch of the current version (`11.8.18` → `11.8.19`):

```bash
uv run woob-update-release --repo ~/dev/backend
```

### Specify a target version

```bash
uv run woob-update-release --repo ~/dev/backend --version 11.8.19
```

### Without installation (direct execution)

```bash
uv run python woob_update_release.py --repo ~/dev/backend
```

## Automated workflow

The script runs 6 steps in sequence:

| Step | Description |
|------|-------------|
| **1 - Initialization** | Checks the working tree is clean, checks out `master`, pulls, creates branch `hotfix/X.Y.Z` |
| **2 - Version bump** | Updates the version in `pyproject.toml`, `setup.py`, `budgea/__init__.py` |
| **3 - Woob upgrade** | Runs `make update-lock/woob`, commits `uv.lock` with the new Woob version |
| **4 - Debian changelog** | Generates an entry in `debian/changelog` via `debchange`, pauses for review |
| **5 - Finalize** | Commits the release files, creates the Git tag, prompts to push the branch and tag |
| **6 - Pull Requests** | (Optional) Creates GitHub PRs to `master` and `develop` via `gh` |

## CLI options

```
usage: woob-update-release [-h] --repo PATH [--version X.Y.Z]

options:
  --repo PATH      Path to the root of the backend git repository (required)
  --version X.Y.Z  Target version (default: auto-increment current patch)
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

## Debian changelog environment variables

The script automatically reads `user.email` and `user.name` from the Git config. If not set, it falls back to:

- `DEBEMAIL=ci@powens.com`
- `DEBFULLNAME=Powens CI`

To override them:
```bash
DEBEMAIL=you@example.com DEBFULLNAME="Your Name" uv run woob-update-release --repo ~/dev/backend
```
