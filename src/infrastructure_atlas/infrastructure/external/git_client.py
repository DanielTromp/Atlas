"""Git repository client for managing local clones of remote repositories."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)


class GitClientError(RuntimeError):
    """Base error raised for Git client failures."""


class GitAuthError(GitClientError):
    """Raised when authentication against Git remote fails."""


class GitCloneError(GitClientError):
    """Raised when Git clone operation fails."""


class GitPullError(GitClientError):
    """Raised when Git pull operation fails."""


@dataclass(slots=True)
class GitClientConfig:
    """Connection parameters for the Git client."""

    remote_url: str
    local_path: Path
    branch: str = "production"
    ssh_key_path: Path | None = None
    timeout: int = 120


@dataclass(slots=True)
class GitRepoInfo:
    """Information about the current state of a Git repository."""

    local_path: Path
    remote_url: str
    branch: str
    commit_hash: str | None
    commit_message: str | None
    commit_date: str | None


class GitClient:
    """Client for managing local Git repository clones."""

    def __init__(self, config: GitClientConfig) -> None:
        self._config = config
        self._local_path = Path(config.local_path)
        self._env = self._build_env()

    def _build_env(self) -> dict[str, str]:
        """Build environment variables for Git commands."""
        env = os.environ.copy()
        if self._config.ssh_key_path:
            key_path = Path(self._config.ssh_key_path).expanduser()
            if key_path.exists():
                env["GIT_SSH_COMMAND"] = f'ssh -i "{key_path}" -o StrictHostKeyChecking=accept-new'
        return env

    def __enter__(self) -> GitClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    def _run_git(
        self,
        args: list[str],
        cwd: Path | None = None,
        *,
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command with configured environment."""
        cmd = ["git", *args]
        work_dir = cwd or self._local_path
        try:
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                env=self._env,
                timeout=self._config.timeout,
                capture_output=capture_output,
                text=True,
                check=False,
            )
            if check and result.returncode != 0:
                stderr = result.stderr.strip() if result.stderr else ""
                stdout = result.stdout.strip() if result.stdout else ""
                error_msg = stderr or stdout or f"Git command failed with exit code {result.returncode}"
                if "Permission denied" in error_msg or "Authentication failed" in error_msg:
                    raise GitAuthError(f"Git authentication failed: {error_msg}")
                raise GitClientError(f"Git command failed: {error_msg}")
            return result
        except subprocess.TimeoutExpired as exc:
            raise GitClientError(f"Git command timed out after {self._config.timeout}s") from exc
        except FileNotFoundError as exc:
            raise GitClientError("Git is not installed or not in PATH") from exc

    def is_cloned(self) -> bool:
        """Check if the repository is already cloned locally."""
        git_dir = self._local_path / ".git"
        return git_dir.exists() and git_dir.is_dir()

    def clone(self, *, force: bool = False) -> GitRepoInfo:
        """Clone the repository to the local path.

        Args:
            force: If True, delete existing local path and re-clone.

        Returns:
            GitRepoInfo with repository state after clone.

        Raises:
            GitCloneError: If clone fails.
            GitAuthError: If authentication fails.
        """
        if self._local_path.exists():
            if force:
                logger.info("Force clone requested, removing existing directory: %s", self._local_path)
                shutil.rmtree(self._local_path)
            elif self.is_cloned():
                logger.debug("Repository already cloned at %s", self._local_path)
                return self.get_info()

        self._local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._run_git(
                ["clone", "--branch", self._config.branch, "--single-branch", self._config.remote_url, str(self._local_path)],
                cwd=self._local_path.parent,
            )
            logger.info("Successfully cloned repository to %s", self._local_path)
            return self.get_info()
        except GitClientError as exc:
            raise GitCloneError(f"Failed to clone repository: {exc}") from exc

    def pull(self) -> GitRepoInfo:
        """Pull latest changes from the remote.

        Returns:
            GitRepoInfo with repository state after pull.

        Raises:
            GitPullError: If pull fails.
            GitClientError: If repository is not cloned.
        """
        if not self.is_cloned():
            raise GitClientError("Repository is not cloned. Call clone() first.")

        try:
            # Fetch and reset to handle any local changes
            self._run_git(["fetch", "origin", self._config.branch])
            self._run_git(["reset", "--hard", f"origin/{self._config.branch}"])
            logger.info("Successfully pulled latest changes at %s", self._local_path)
            return self.get_info()
        except GitClientError as exc:
            raise GitPullError(f"Failed to pull repository: {exc}") from exc

    def ensure_updated(self) -> GitRepoInfo:
        """Ensure repository is cloned and up to date.

        Returns:
            GitRepoInfo with current repository state.
        """
        if self.is_cloned():
            return self.pull()
        return self.clone()

    def get_info(self) -> GitRepoInfo:
        """Get current repository information.

        Returns:
            GitRepoInfo with current state.

        Raises:
            GitClientError: If repository is not cloned.
        """
        if not self.is_cloned():
            raise GitClientError("Repository is not cloned.")

        commit_hash = None
        commit_message = None
        commit_date = None

        try:
            result = self._run_git(["rev-parse", "HEAD"], check=False)
            if result.returncode == 0:
                commit_hash = result.stdout.strip()
        except GitClientError:
            pass

        try:
            result = self._run_git(["log", "-1", "--format=%s"], check=False)
            if result.returncode == 0:
                commit_message = result.stdout.strip()
        except GitClientError:
            pass

        try:
            result = self._run_git(["log", "-1", "--format=%ci"], check=False)
            if result.returncode == 0:
                commit_date = result.stdout.strip()
        except GitClientError:
            pass

        return GitRepoInfo(
            local_path=self._local_path,
            remote_url=self._config.remote_url,
            branch=self._config.branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
            commit_date=commit_date,
        )

    def get_files(self, pattern: str = "**/*") -> list[Path]:
        """Get list of files matching a glob pattern.

        Args:
            pattern: Glob pattern to match files.

        Returns:
            List of matching file paths.
        """
        if not self.is_cloned():
            return []
        return list(self._local_path.glob(pattern))


__all__ = [
    "GitAuthError",
    "GitClient",
    "GitClientConfig",
    "GitClientError",
    "GitCloneError",
    "GitPullError",
    "GitRepoInfo",
]

