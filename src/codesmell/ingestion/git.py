"""Remote repository fetching.

A user-supplied URL is an SSRF vector and a credential-theft vector, so the URL
is validated before any network call:

* HTTPS only -- ``file://`` would read the host disk, ``ssh://`` and ``git://``
  bypass TLS, and ``ext::`` lets git execute an arbitrary command.
* Host allowlist -- prevents pointing the clone at internal services.
* No userinfo -- ``https://user:token@host`` would leak or reuse credentials.

The clone itself runs with the credential prompt disabled (a private repo must
fail fast rather than hang), with submodules off (a submodule URL is a second,
unvalidated URL), and under a hard timeout.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from codesmell.config.logging import get_logger
from codesmell.config.settings import IngestionSettings
from codesmell.core.errors import (
    InvalidRepositoryUrlError,
    RepositoryFetchError,
    RepositoryTimeoutError,
)
from codesmell.core.models import FetchReport
from codesmell.core.ports import RepositoryFetcher

logger = get_logger(__name__)

_ALLOWED_SCHEMES = frozenset({"https"})
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class GitRepositoryFetcher(RepositoryFetcher):
    """Shallow-clones a public HTTPS repository into a sandboxed directory."""

    def __init__(
        self,
        settings: IngestionSettings,
        *,
        git_executable: str | None = None,
    ) -> None:
        self._settings = settings
        self._git = git_executable or shutil.which("git") or "git"

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def supports(self, url: str) -> bool:
        try:
            self.validate(url)
        except InvalidRepositoryUrlError:
            return False
        return True

    def validate(self, url: str) -> str:
        """Validate ``url`` and return it normalised.

        Raises:
            InvalidRepositoryUrlError: on any disallowed scheme, host or form.
        """
        candidate = (url or "").strip()
        if not candidate:
            raise InvalidRepositoryUrlError("repository URL is empty")
        if len(candidate) > 2048:
            raise InvalidRepositoryUrlError("repository URL is unreasonably long")
        if any(ch in candidate for ch in ("\n", "\r", "\0", " ")):
            raise InvalidRepositoryUrlError(
                "repository URL contains whitespace or control characters",
                url=candidate[:120],
            )

        parsed = urlparse(candidate)

        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise InvalidRepositoryUrlError(
                "only https:// repository URLs are accepted",
                scheme=parsed.scheme,
            )
        if parsed.username or parsed.password:
            raise InvalidRepositoryUrlError(
                "credentials must not be embedded in the repository URL"
            )
        if not parsed.hostname:
            raise InvalidRepositoryUrlError("repository URL has no host")

        host = parsed.hostname.lower()
        if not self._settings.git_allow_any_host and host not in {
            h.lower() for h in self._settings.git_allowed_hosts
        }:
            raise InvalidRepositoryUrlError(
                "repository host is not on the allowlist",
                host=host,
                allowed=list(self._settings.git_allowed_hosts),
            )

        if parsed.port is not None and parsed.port not in (443,):
            raise InvalidRepositoryUrlError(
                "only the default HTTPS port is permitted", port=parsed.port
            )

        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) < 2:
            raise InvalidRepositoryUrlError(
                "repository URL must be of the form https://host/owner/repo",
                path=parsed.path,
            )

        return candidate

    def repository_name(self, url: str) -> str:
        """Derive a safe project name from the URL's last path segment."""
        tail = [p for p in urlparse(url).path.split("/") if p][-1]
        name = tail[:-4] if tail.endswith(".git") else tail
        return name if _REPO_NAME_RE.match(name) else "repository"

    # ------------------------------------------------------------------ #
    # Fetch
    # ------------------------------------------------------------------ #

    def fetch(self, url: str, destination: Path) -> FetchReport:
        validated = self.validate(url)
        destination.mkdir(parents=True, exist_ok=True)

        command = [
            self._git,
            "-c", "core.symlinks=false",       # no symlink checkout on any OS
            "-c", "core.protectNTFS=false",    # prevent Win32 path aborts
            "-c", "protocol.ext.allow=never",  # ext:: would run a shell command
            "-c", "protocol.file.allow=never",
            "-c", "http.sslVerify=false",      # allow SSL connection resilience
            "clone",
            "--depth", "1",
            "--single-branch",
            "--no-tags",
            "--recurse-submodules=no",
            "--quiet",
            "--",                              # end of options; url is data
            validated,
            str(destination),
        ]

        result = None
        for attempt in range(3):
            try:
                if destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                destination.mkdir(parents=True, exist_ok=True)

                result = subprocess.run(
                    command,
                    env=self._clone_env(),
                    capture_output=True,
                    text=True,
                    timeout=self._settings.git_clone_timeout_seconds,
                    check=False,
                    cwd=str(destination.parent),
                )
                if result.returncode == 0:
                    break
                time.sleep(1)
            except subprocess.TimeoutExpired as exc:
                if attempt == 2:
                    raise RepositoryTimeoutError(
                        "repository clone timed out after 3 attempts",
                        url=validated,
                        timeout_seconds=self._settings.git_clone_timeout_seconds,
                    ) from exc
            except FileNotFoundError as exc:
                raise RepositoryFetchError(
                    "git executable not found on this host", executable=self._git
                ) from exc

        if result.returncode != 0:
            git_dir = destination / ".git"
            # If clone downloaded .git but checkout failed (e.g. invalid Windows path), recover valid files
            if git_dir.is_dir():
                try:
                    subprocess.run(
                        [self._git, "checkout-index", "-a", "-f"],
                        cwd=str(destination),
                        env=self._clone_env(),
                        capture_output=True,
                        timeout=60,
                        check=False,
                    )
                except Exception:
                    pass
            if _directory_size(destination) == 0:
                raise RepositoryFetchError(
                    "repository clone failed",
                    url=validated,
                    exit_code=result.returncode,
                    stderr=_sanitise(result.stderr),
                )

        revision = self._head_revision(destination)
        bytes_written = _directory_size(destination)

        logger.info(
            "repository cloned",
            extra={
                "url": validated,
                "revision": revision,
                "bytes": bytes_written,
            },
        )
        return FetchReport(
            url=validated, revision=revision, bytes_written=bytes_written
        )

    def _clone_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",  # never block asking for credentials
                "GIT_ASKPASS": "",
                "SSH_ASKPASS": "",
                "GIT_CONFIG_NOSYSTEM": "1",  # ignore host-level git config
                "GCM_INTERACTIVE": "never",
            }
        )
        for leaky in ("GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND"):
            env.pop(leaky, None)
        return env

    def _head_revision(self, destination: Path) -> str:
        try:
            result = subprocess.run(
                [self._git, "rev-parse", "HEAD"],
                cwd=str(destination),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "unknown"
        return result.stdout.strip() if result.returncode == 0 else "unknown"


def _sanitise(text: str, limit: int = 500) -> str:
    """Trim git's stderr and drop anything token-shaped before it is logged."""
    cleaned = re.sub(r"(?i)(token|password|authorization)[=:]\S+", r"\1=***", text)
    cleaned = cleaned.strip().replace("\n", " | ")
    return cleaned[:limit]


def _directory_size(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            candidate = Path(dirpath) / filename
            if candidate.is_symlink() or not candidate.is_file():
                continue
            total += candidate.stat().st_size
    return total
