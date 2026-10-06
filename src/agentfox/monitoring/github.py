"""GitHub, from the server side: the stored connection, a repository tarball, push signatures.

Shared by the connect-and-scan routes (`gateway/routes/integrations.py`) and the
`github_repo` monitor, so a scheduled rescan downloads and unpacks a repository
exactly the way the first scan did. Nothing here imports or runs the repository: the
archive is unpacked under size limits and handed to the static scanner.
"""

from __future__ import annotations

import hashlib
import hmac
import tarfile
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import GithubConnection

GITHUB_API = "https://api.github.com"
#: Above this, extraction stops — a resource-exhaustion guard on server-supplied
#: archive content, not a code-execution one (nothing here ever imports the repo).
MAX_EXTRACTED_BYTES = 80 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024

#: Injected in tests (`httpx.MockTransport`). ``None`` means the real network.
_TRANSPORT: httpx.BaseTransport | None = None


class RepoFetchError(RuntimeError):
    """The repository could not be downloaded. ``too_large`` says it was refused for
    size rather than because GitHub or the network failed."""

    def __init__(self, message: str, *, too_large: bool = False) -> None:
        super().__init__(message)
        self.too_large = too_large


def connection(session: Session, connection_id: str | None = None) -> GithubConnection | None:
    """The tenant's GitHub connection: the one named, else the most recent."""
    if connection_id:
        found = session.get(GithubConnection, connection_id)
        if found is not None:
            return found
    return session.scalar(select(GithubConnection).order_by(GithubConnection.created_at.desc()))


def _client(timeout: float) -> httpx.Client:
    return httpx.Client(transport=_TRANSPORT, timeout=timeout, follow_redirects=True)


def download_and_extract(repo_full_name: str, ref: str, token: str, dest: Path) -> Path:
    """Download ``repo_full_name`` at ``ref`` (default branch when empty) into ``dest``.

    Returns the directory holding the unpacked tree, with GitHub's one
    ``{owner}-{repo}-{sha}/`` top-level directory stripped so scanned paths read as
    repository-relative.
    """
    url = f"{GITHUB_API}/repos/{repo_full_name}/tarball"
    if ref:
        url = f"{url}/{ref}"
    archive = dest / "repo.tar.gz"
    try:
        with (
            _client(60.0) as client,
            client.stream(
                "GET",
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            ) as resp,
        ):
            resp.raise_for_status()
            total = 0
            with archive.open("wb") as f:
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > MAX_EXTRACTED_BYTES:
                        raise RepoFetchError(
                            "repository archive is too large to scan", too_large=True
                        )
                    f.write(chunk)
    except httpx.HTTPStatusError as exc:
        raise RepoFetchError(
            f"GitHub answered HTTP {exc.response.status_code} for {repo_full_name}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RepoFetchError(f"could not download {repo_full_name}: {exc}") from exc

    extracted = dest / "src"
    extracted.mkdir()
    try:
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if member.size > MAX_MEMBER_BYTES or not member.isfile() and not member.isdir():
                    continue
                parts = Path(member.name).parts
                if len(parts) < 2:
                    continue
                member.name = str(Path(*parts[1:]))
                tar.extract(member, extracted, filter="data")
    except tarfile.TarError as exc:
        raise RepoFetchError(f"the archive for {repo_full_name} could not be read: {exc}") from exc
    archive.unlink()
    return extracted


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Check GitHub's ``X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of the body>``."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256=").strip())


def sign(secret: str, body: bytes) -> str:
    """The header value GitHub would send for ``body`` — for tests and for operators
    checking their own setup."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
