"""Hardened ``git`` invocation.

MergeX runs exactly two git operations -- a shallow clone and a rev-parse --
against untrusted URLs. Everything here exists to keep that from becoming a
foothold:

* **No shell.** Arguments are passed as a list, so a repository name can never
  be interpreted as a command.
* **No credential prompts.** A private repository without a token must fail
  immediately rather than block the request waiting on stdin.
* **No ambient configuration.** System and global gitconfig are suppressed, so
  a developer's ``~/.gitconfig`` (aliases, ``core.fsmonitor``, insteadOf
  rewrites) cannot change what runs on the server.
* **No hooks, no submodules, no symlinks.** A cloned repository must not be
  able to execute anything or reach outside the sandbox.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.logging import get_logger
from app.core.security import redact_url_credentials

__all__ = [
    "GitCommandError",
    "GitResult",
    "GitRunner",
    "GitTimeoutError",
    "build_clone_command",
    "build_rev_parse_command",
    "is_commit_sha",
    "run_git",
]

log = get_logger("app.git")

# Environment variables git genuinely needs on each platform. Everything else
# is dropped so the subprocess inherits as little as possible.
_ENV_PASSTHROUGH = (
    "PATH",
    "SYSTEMROOT",  # Windows: required for sockets/DNS to work at all
    "SystemRoot",
    "COMSPEC",
    "WINDIR",
    "TEMP",
    "TMP",
    "LD_LIBRARY_PATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "GIT_SSL_CAINFO",
)

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


class GitCommandError(RuntimeError):
    """A git command exited non-zero."""

    def __init__(self, command: Sequence[str], returncode: int, stderr: str) -> None:
        self.command = list(command)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git exited {returncode}: {stderr.strip()[:500]}")


class GitTimeoutError(GitCommandError):
    """A git command exceeded its time budget."""

    def __init__(self, command: Sequence[str], timeout: float) -> None:
        self.timeout = timeout
        super().__init__(command, -1, f"timed out after {timeout:.0f}s")


@dataclass(frozen=True, slots=True)
class GitResult:
    """Outcome of one git invocation."""

    returncode: int
    stdout: str
    stderr: str


class GitRunner(Protocol):
    """How git gets executed.

    A protocol rather than a hard dependency so the importer can be tested
    without network access or a git binary.
    """

    async def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> GitResult: ...


def is_commit_sha(ref: str) -> bool:
    """True when ``ref`` looks like a commit hash rather than a branch name."""
    return bool(_SHA_RE.match(ref.lower()))


def build_clone_command(
    url: str,
    destination: Path,
    *,
    ref: str | None = None,
    depth: int = 1,
) -> list[str]:
    """Build the argv for a hardened shallow clone.

    A pure function so the flags are asserted in tests rather than trusted.

    Note:
        ``ref`` must be a branch or tag. A commit SHA cannot be cloned
        directly; use :func:`build_fetch_commit_commands` for that.
    """
    command = [
        "git",
        # -c options come before the subcommand so they apply to it.
        "-c",
        "core.symlinks=false",  # never materialise a symlink on disk
        "-c",
        "core.autocrlf=false",  # byte-exact files; line endings are analysed
        "-c",
        "core.hooksPath=",  # no hooks, even if the repo ships them
        "-c",
        "advice.detachedHead=false",
        "-c",
        "protocol.version=2",
        "-c",
        "credential.helper=",  # no keychain lookups
        "clone",
        f"--depth={depth}",
        "--single-branch",
        "--no-tags",
        "--no-recurse-submodules",  # submodules are arbitrary extra fetches
        "--quiet",
    ]
    if ref:
        command.append(f"--branch={ref}")
    # `--` terminates options, so a URL starting with a dash cannot become one.
    command.extend(["--", url, str(destination)])
    return command


def build_fetch_commit_commands(
    url: str,
    destination: Path,
    sha: str,
    *,
    depth: int = 1,
) -> list[list[str]]:
    """Build the argv sequence that checks out one specific commit.

    ``git clone --depth`` cannot target a SHA, so this inits an empty
    repository and fetches exactly that commit. GitHub permits fetching an
    arbitrary reachable SHA, which is what makes this work.
    """
    base = [
        "git",
        "-c",
        "core.symlinks=false",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.hooksPath=",
        "-c",
        "credential.helper=",
    ]
    return [
        [*base, "init", "--quiet", str(destination)],
        [*base, "-C", str(destination), "remote", "add", "origin", "--", url],
        [*base, "-C", str(destination), "fetch", f"--depth={depth}", "--quiet", "origin", sha],
        [*base, "-C", str(destination), "checkout", "--quiet", "FETCH_HEAD"],
    ]


def build_rev_parse_command(repository: Path) -> list[str]:
    """Build the argv that reports the checked-out commit."""
    return ["git", "-C", str(repository), "rev-parse", "HEAD"]


def _subprocess_env() -> dict[str, str]:
    """A minimal, prompt-free environment for git."""
    env = {key: os.environ[key] for key in _ENV_PASSTHROUGH if key in os.environ}
    env.update(
        {
            # Fail instead of prompting for credentials on a private repo.
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GCM_INTERACTIVE": "never",
            # Ignore system and per-user configuration entirely.
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            # Deterministic, parseable output.
            "LC_ALL": "C",
            "GIT_FLUSH": "1",
        }
    )
    return env


async def run_git(
    args: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> GitResult:
    """Execute a git command, enforcing ``timeout``.

    Raises:
        GitTimeoutError: if the command outlives its budget.
        GitCommandError: if git cannot be started.
    """
    command = list(args)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        env=dict(env) if env is not None else _subprocess_env(),
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        # Kill the whole attempt; a hung clone must not hold the sandbox open.
        process.kill()
        await process.wait()
        log.warning("git_timeout", command=_safe_command(command), timeout=timeout)
        raise GitTimeoutError(command, timeout) from None

    result = GitResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )
    log.debug(
        "git_finished",
        command=_safe_command(command),
        returncode=result.returncode,
    )
    return result


def _safe_command(command: Sequence[str]) -> list[str]:
    """Strip credentials from a command before it reaches the logs."""
    return [redact_url_credentials(part) for part in command]
