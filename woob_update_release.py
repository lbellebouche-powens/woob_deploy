#!/usr/bin/env python3
"""Release script for Woob dependency upgrades.

Automates the following workflow:
  1. Initialization   — prune remote refs, increment patch version, prepare branch from master
  2. Woob upgrade     — run ``make update-lock/woob``, commit if lock changed
  3. Version bump     — update version in all source files
  4. Debian changelog — prepend entry directly into debian/changelog
  5. Finalize         — commit, tag, push (with confirmation)
  6. Create PRs       — create PRs on backend repository from the same created hotfix branch to master and develop (optionnal)
"""

import argparse
from email.utils import formatdate
import logging
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Optional


VERSION_FILES = {
    "pyproject.toml": r'(version\s*=\s*")[^"]+(")',
    "setup.py": r'(version\s*=\s*")[^"]+(")',
    "budgea/__init__.py": r'(__version__\s*=\s*")[^"]+(")',
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class ColorFormatter(logging.Formatter):
    """Logging formatter with ANSI color codes.

    :param fmt: format string passed to the parent Formatter
    :type fmt: str
    """

    COLORS = {
        logging.DEBUG: "\033[90m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record with ANSI color.

        :param record: log record to format
        :type record: logging.LogRecord
        :return: formatted string with color codes
        :rtype: str
        """
        color = self.COLORS.get(record.levelno, self.RESET)
        return f"{color}{super().format(record)}{self.RESET}"


def _setup_logging() -> logging.Logger:
    """Configure and return the module logger.

    DEBUG/INFO go to stdout; WARNING+ go to stderr.

    :return: configured logger
    :rtype: logging.Logger
    """
    fmt = ColorFormatter("%(levelname)-8s %(message)s")

    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(fmt)
    out.addFilter(lambda r: r.levelno <= logging.INFO)

    err = logging.StreamHandler(sys.stderr)
    err.setFormatter(fmt)
    err.setLevel(logging.WARNING)

    logger = logging.getLogger("woob_update_release")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(out)
    logger.addHandler(err)
    return logger


log = _setup_logging()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_woob_version(uv_lock_path: Path) -> Optional[str]:
    """Extract the woob-powens version from ``uv.lock``.

    Finds the ``[[package]]`` block whose name is ``woob-powens`` and returns
    the associated ``version`` value.

    :param uv_lock_path: path to the ``uv.lock`` file
    :type uv_lock_path: Path
    :return: version string, or ``None`` if not found
    :rtype: Optional[str]
    """
    content = uv_lock_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=\[\[package\]\])", content)
    for block in blocks:
        if 'name = "woob-powens"' in block:
            m = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
            if m:
                return m.group(1)
    return None


# ---------------------------------------------------------------------------
# WoobUpdateRelease
# ---------------------------------------------------------------------------


class WoobUpdateRelease:
    """Orchestrates the Woob upgrade + bugfix release workflow.

    :param root_dir: path to the root of the backend git repository
    :type root_dir: Path
    :param new_version: target version (auto-computed from current if None)
    :type new_version: Optional[str]
    """

    TIMEOUT = 300

    def __init__(self, root_dir: Path, new_version: Optional[str] = None) -> None:
        self.root_dir = root_dir
        self.new_version = new_version or self._auto_increment_version()
        self._validate_version(self.new_version)
        self.woob_version_after: Optional[str] = None

    # ------------------------------------------------------------------
    # Version helpers
    # ------------------------------------------------------------------

    def _read_current_version(self) -> str:
        """Read the current version from ``budgea/__init__.py``.

        :return: current version string
        :rtype: str
        :raises SystemExit: if the version cannot be parsed
        """
        init_file = self.root_dir / "budgea" / "__init__.py"
        content = init_file.read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', content)
        if not m:
            log.error("Could not parse current version from %s", init_file)
            sys.exit(1)
        return m.group(1)

    @staticmethod
    def _validate_version(version: str) -> None:
        """Assert that *version* matches ``MAJOR.MINOR.PATCH``.

        :param version: version string to validate
        :type version: str
        :raises SystemExit: if the format is invalid
        """
        if not re.match(r"^\d+\.\d+\.\d+$", version):
            log.error(
                "Invalid version format: '%s'. Expected MAJOR.MINOR.PATCH", version
            )
            sys.exit(1)

    def _auto_increment_version(self) -> str:
        """Compute the next bugfix version from the current one.

        Reads the current version and increments the patch component by 1.

        :return: next version string (e.g. ``11.8.19`` from ``11.8.18``)
        :rtype: str
        """
        current = self._read_current_version()
        major, minor, patch = current.split(".")
        next_version = f"{major}.{minor}.{int(patch) + 1}"
        log.info("Current version: %s  →  New version: %s", current, next_version)
        return next_version

    # ------------------------------------------------------------------
    # Subprocess / I/O helpers
    # ------------------------------------------------------------------

    def run_cmd(
        self,
        cmd: List[str],
        *,
        check: bool = True,
        capture: bool = False,
        env: Optional[dict] = None,
    ) -> subprocess.CompletedProcess:
        """Run a subprocess command with standardized error handling.

        :param cmd: command and its arguments
        :type cmd: List[str]
        :param check: raise on non-zero exit code
        :type check: bool
        :param capture: capture stdout/stderr instead of printing
        :type capture: bool
        :param env: extra environment variables to merge with the current env
        :type env: Optional[dict]
        :return: completed process result
        :rtype: subprocess.CompletedProcess
        :raises SystemExit: on fatal subprocess errors
        """
        run_env = {**os.environ, **env} if env else None
        log.debug("$ %s", " ".join(cmd))
        try:
            return subprocess.run(
                cmd,
                check=check,
                capture_output=capture,
                text=True,
                timeout=self.TIMEOUT,
                cwd=self.root_dir,
                env=run_env,
            )
        except FileNotFoundError:
            log.error("Command not found: '%s'. Is it installed and in PATH?", cmd[0])
            sys.exit(1)
        except subprocess.TimeoutExpired:
            log.error("Command timed out after %ds: %s", self.TIMEOUT, " ".join(cmd))
            sys.exit(1)
        except subprocess.CalledProcessError as exc:
            log.error("Command failed (exit %d): %s", exc.returncode, " ".join(cmd))
            if capture and exc.stdout:
                log.error("stdout: %s", exc.stdout.strip())
            if capture and exc.stderr:
                log.error("stderr: %s", exc.stderr.strip())
            if check:
                sys.exit(1)
            raise

    def ask_confirm(self, msg: str, *, default: bool = False) -> bool:
        """Prompt the user for a yes/no answer.

        :param msg: question displayed to the user
        :type msg: str
        :param default: answer returned when the user presses Enter
        :type default: bool
        :return: ``True`` if the user confirmed, ``False`` otherwise
        :rtype: bool
        """
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            answer = input(f"{msg} {suffix} ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(130)
        return (answer in ("y", "yes")) if answer else default

    def ask_continue(self, msg: str) -> None:
        """Pause execution until the user presses Enter.

        :param msg: message displayed before the prompt
        :type msg: str
        """
        try:
            input(f"{msg} [Press Enter to continue] ")
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(130)

    def _step_header(self, number: int, total: int, title: str) -> None:
        """Print a formatted step header.

        :param number: current step number (1-based)
        :type number: int
        :param total: total number of steps
        :type total: int
        :param title: short description of the step
        :type title: str
        """
        sep = "=" * 60
        log.info("")
        log.info(sep)
        log.info("[%d/%d] %s", number, total, title)
        log.info(sep)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def step1_prepare_branch(self) -> None:
        """Step 1: Ensure clean tree, update master, create release branch."""
        self._step_header(1, 5, "Initialization")

        result = self.run_cmd(["git", "status", "--porcelain"], capture=True)
        if result.stdout.strip():
            log.error("Working tree is not clean. Commit or stash changes first.")
            sys.exit(1)
        log.info("Working tree is clean.")

        log.info("Pruning stale remote-tracking branches.")
        self.run_cmd(["git", "fetch", "--prune"])

        for branch in ("develop", "master"):
            self.run_cmd(["git", "checkout", branch])
            self.run_cmd(["git", "reset", "--hard", f"origin/{branch}"])
            log.info("Branch '%s' reset to origin/%s.", branch, branch)

        branch_name = f"hotfix/{self.new_version}"

        local_exists = (
            self.run_cmd(
                ["git", "rev-parse", "--verify", branch_name],
                check=False,
                capture=True,
            ).returncode
            == 0
        )
        remote_exists = (
            self.run_cmd(
                ["git", "rev-parse", "--verify", f"origin/{branch_name}"],
                check=False,
                capture=True,
            ).returncode
            == 0
        )

        if local_exists or remote_exists:
            origins: List[str] = []
            if local_exists:
                origins.append("locally")
            if remote_exists:
                origins.append("on remote")
            log.warning(
                "Branch '%s' already exists %s.", branch_name, " and ".join(origins)
            )
            if not self.ask_confirm(
                f"Resume on existing branch '{branch_name}'? "
                "(Answer 'n' to abort and inspect it manually.)"
            ):
                log.error("Aborting. Inspect '%s' and rerun when ready.", branch_name)
                sys.exit(1)
            if local_exists:
                self.run_cmd(["git", "checkout", branch_name])
            else:
                self.run_cmd(
                    ["git", "checkout", "-b", branch_name, f"origin/{branch_name}"]
                )
            return

        log.info("Creating branch '%s' from master.", branch_name)
        self.run_cmd(["git", "checkout", "-b", branch_name])

    def step2_version_bump(self) -> None:
        """Step 2: Bump version in ``pyproject.toml``, ``setup.py``, ``budgea/__init__.py``."""
        self._step_header(2, 5, "Version Bump")

        for rel_path, pattern in VERSION_FILES.items():
            filepath = self.root_dir / rel_path
            content = filepath.read_text(encoding="utf-8")
            new_content, count = re.subn(
                pattern,
                rf"\g<1>{self.new_version}\2",
                content,
            )
            if count != 1:
                log.error(
                    "Expected exactly 1 version match in %s, found %d. Aborting.",
                    rel_path,
                    count,
                )
                sys.exit(1)
            filepath.write_text(new_content, encoding="utf-8")
            log.info("  Bumped %s → %s", rel_path, self.new_version)

    def step3_update_woob(self) -> None:
        """Step 3: Upgrade Woob via ``make update-lock/woob``, commit ``uv.lock`` separately."""
        self._step_header(3, 5, "Woob Upgrade")

        uv_lock = self.root_dir / "uv.lock"
        version_before = _parse_woob_version(uv_lock)
        log.info("Woob version before upgrade: %s", version_before or "unknown")

        log.info("Running: make update-lock/woob")
        self.run_cmd(["make", "update-lock/woob"])

        self.woob_version_after = _parse_woob_version(uv_lock)
        log.info("Woob version after upgrade: %s", self.woob_version_after or "unknown")

        if self.woob_version_after and self.woob_version_after != version_before:
            commit_msg = (
                f"feat(backend): Update woob to version {self.woob_version_after}"
            )
        else:
            commit_msg = "feat(backend): Update woob in uv.lock file"

        self.run_cmd(["git", "add", "uv.lock"])
        self.run_cmd(["git", "commit", "-m", commit_msg])
        log.info("Committed: %s", commit_msg)

    def step4_debian_changelog(self) -> None:
        """Step 4: Prepend a Debian changelog entry directly into ``debian/changelog``."""
        self._step_header(4, 5, "Debian Changelog")

        git_email = self.run_cmd(
            ["git", "config", "user.email"], capture=True, check=False
        )
        git_name = self.run_cmd(
            ["git", "config", "user.name"], capture=True, check=False
        )
        maintainer_email = (
            git_email.stdout.strip()
            if git_email.returncode == 0 and git_email.stdout.strip()
            else "ci@powens.com"
        )
        maintainer_name = (
            git_name.stdout.strip()
            if git_name.returncode == 0 and git_name.stdout.strip()
            else "Powens CI"
        )
        log.info("Maintainer: %s <%s>", maintainer_name, maintainer_email)

        date_str = formatdate(localtime=True)
        entry = (
            f"budgea ({self.new_version}) unstable; urgency=medium\n"
            f"\n"
            f"  * New Upstream Release woob in `uv.lock` file\n"
            f"\n"
            f" -- {maintainer_name} <{maintainer_email}>  {date_str}\n"
            f"\n"
        )

        changelog_path = self.root_dir / "debian" / "changelog"
        existing = (
            changelog_path.read_text(encoding="utf-8")
            if changelog_path.exists()
            else ""
        )
        changelog_path.write_text(entry + existing, encoding="utf-8")
        log.info("debian/changelog updated.")
        self.ask_continue("Review debian/changelog, then continue.")

    def step5_finalize(self) -> None:
        """Step 5: Commit release files, create tag, push with confirmation."""
        self._step_header(5, 5, "Finalize")

        files_to_stage = [
            "budgea/__init__.py",
            "debian/changelog",
            "pyproject.toml",
            "setup.py",
        ]
        self.run_cmd(["git", "add"] + files_to_stage)

        commit_msg = f"Budgea {self.new_version} released"
        log.info("Committing: %s", commit_msg)
        result = self.run_cmd(
            ["git", "commit", "-m", commit_msg],
            check=False,
            capture=True,
        )
        if result.returncode != 0:
            log.error("Commit failed (pre-commit hook?).")
            if result.stdout:
                log.error("stdout:\n%s", result.stdout.strip())
            if result.stderr:
                log.error("stderr:\n%s", result.stderr.strip())
            log.error("")
            log.error("To recover:")
            log.error("  1. Fix the issues above")
            log.error("  2. git add -u")
            log.error("  3. git commit -m '%s'", commit_msg)
            log.error("  4. git tag %s", self.new_version)
            sys.exit(1)

        self.run_cmd(["git", "tag", self.new_version])
        log.info("Tag '%s' created.", self.new_version)

        branch_name = f"hotfix/{self.new_version}"
        log.info("")
        log.info("=" * 60)
        log.info("Release %s is ready!", self.new_version)
        log.info("=" * 60)
        log.info("")
        log.info("Commands to push:")
        log.info("  git push --set-upstream origin %s", branch_name)
        log.info("  git push origin %s", self.new_version)

        if self.ask_confirm(f"Push branch '{branch_name}' now?"):
            self.run_cmd(["git", "push", "--set-upstream", "origin", branch_name])
            log.info("Branch pushed.")
        else:
            log.info("Skipped branch push.")

        if self.ask_confirm(
            f"Push tag '{self.new_version}' now? (triggers the Github Actions pipeline)",
            default=False,
        ):
            self.run_cmd(["git", "push", "origin", self.new_version])
            log.info("Tag pushed — Github Actions pipeline triggered.")
        else:
            log.info(
                "Skipped tag push. Run 'git push origin %s' manually when ready.",
                self.new_version,
            )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def check_prerequisites(self) -> None:
        """Verify that all external tools required by the script are installed.

        :raises SystemExit: if any required tool is missing
        """
        required = ["git", "make", "uv"]
        missing = [cmd for cmd in required if shutil.which(cmd) is None]
        if missing:
            log.error("Missing required tools: %s", ", ".join(missing))
            sys.exit(1)
        log.info("All required tools found.")

    def step6_create_prs(self) -> None:
        """Step 6 (optional): Create PRs on GitHub via ``gh`` CLI.

        Opens one PR from ``hotfix/x.y.z`` to ``master`` and one to ``develop``.
        Both PRs include the upgraded Woob version in their description.
        Skipped silently if ``gh`` is not installed or the user declines.

        :raises SystemExit: if ``gh pr create`` fails unexpectedly
        """
        self._step_header(6, 6, "Create Pull Requests (optional)")

        if shutil.which("gh") is None:
            log.warning("'gh' CLI not found — skipping PR creation.")
            log.warning("Install it from https://cli.github.com/ to enable this step.")
            return

        if not self.ask_confirm("Create GitHub PRs now?", default=True):
            log.info("Skipping PR creation.")
            return

        branch_name = f"hotfix/{self.new_version}"
        woob_info = (
            f"Woob upgraded to version **{self.woob_version_after}**."
            if self.woob_version_after
            else "Woob dependencies updated in `uv.lock`."
        )
        pr_body = textwrap.dedent(f"""\
            ## Woob upgrade

            {woob_info}
        """)

        for target in ("master", "develop"):
            title = f"hotfix/{self.new_version} → {target}: Budgea {self.new_version}"
            log.info("Creating PR: %s", title)
            self.run_cmd(
                [
                    "gh",
                    "pr",
                    "create",
                    "--base",
                    target,
                    "--head",
                    branch_name,
                    "--title",
                    title,
                    "--body",
                    pr_body,
                ],
            )
            log.info("PR to '%s' created.", target)

    def run(self) -> None:
        """Run all steps in sequence.

        :raises SystemExit: on any fatal error
        """
        self.check_prerequisites()
        self.step1_prepare_branch()
        self.step2_version_bump()
        self.step3_update_woob()
        self.step4_debian_changelog()
        self.step5_finalize()
        self.step6_create_prs()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the Woob update release script."""
    parser = argparse.ArgumentParser(
        description="Upgrade Woob and cut a Budgea bugfix release.",
        epilog=textwrap.dedent("""\
            Examples:
              # Auto-increment patch version (11.8.18 → 11.8.19):
              python woob_update_release.py --repo ~/dev/backend

              # Specify version explicitly:
              python woob_update_release.py --repo ~/dev/backend --version 11.8.19
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo",
        required=True,
        metavar="PATH",
        help="Path to the root of the backend git repository",
    )
    parser.add_argument(
        "--version",
        default=None,
        metavar="X.Y.Z",
        help="Target version (default: auto-increment current patch version)",
    )
    args = parser.parse_args()

    root_dir = Path(args.repo).expanduser().resolve()
    if not root_dir.is_dir():
        log.error("Repository path does not exist: %s", root_dir)
        sys.exit(1)

    manager = WoobUpdateRelease(root_dir=root_dir, new_version=args.version)
    try:
        manager.run()
    except KeyboardInterrupt:
        print()
        log.warning("Interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
