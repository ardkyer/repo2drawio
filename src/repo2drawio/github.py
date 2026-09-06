from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import io
import json
from pathlib import PurePosixPath
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse
import zipfile


MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_FILES = 600
MAX_API_FILES = 220
MAX_FILE_BYTES = 384 * 1024
MAX_TEXT_BYTES = 5 * 1024 * 1024

SKIP_PARTS = {
    ".git",
    ".next",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
ANALYSIS_SKIP_PARTS = {
    "assets",
    "data",
    "e2e",
    "fixtures",
    "legacy",
    "public",
    "test",
    "tests",
}
TEXT_SUFFIXES = {
    ".c",
    ".cs",
    ".cfg",
    ".conf",
    ".dockerignore",
    ".graphql",
    ".go",
    ".gradle",
    ".h",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".tf",
    ".tfvars",
    ".xml",
    ".yaml",
    ".yml",
}
SPECIAL_NAMES = {
    "dockerfile",
    "gemfile",
    "license",
    "makefile",
    "procfile",
    "readme",
    "requirements.txt",
}
SECRET_NAMES = {
    ".env",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
    "secrets.yml",
    "secrets.yaml",
}


class RepositoryError(ValueError):
    """Raised when a repository URL or archive cannot be safely processed."""


class ArchiveTooLarge(RepositoryError):
    """Raised when the ZIP fallback should switch to selective GitHub API reads."""


@dataclass(frozen=True)
class RepositorySnapshot:
    owner: str
    name: str
    url: str
    files: dict[str, str]

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_github_url(value: str) -> tuple[str, str]:
    raw = value.strip()
    if not raw:
        raise RepositoryError("Enter a GitHub repository URL.")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise RepositoryError("Only public https://github.com repository URLs are supported.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise RepositoryError("Use a repository URL like https://github.com/owner/repo.")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    valid = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not valid.fullmatch(owner) or not name or not valid.fullmatch(name):
        raise RepositoryError("The GitHub owner or repository name is invalid.")
    return owner, name


def _request(url: str, token: str | None = None) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "repo2drawio/0.6",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _download_archive(owner: str, name: str, token: str | None = None, private_access: bool = False) -> bytes:
    url = f"https://api.github.com/repos/{owner}/{name}/zipball"
    try:
        with urllib.request.urlopen(_request(url, token), timeout=25) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_ARCHIVE_BYTES:
                raise ArchiveTooLarge("Repository archive is larger than the 100 MB safety limit.")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise ArchiveTooLarge("Repository archive is larger than the 100 MB safety limit.")
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            if private_access:
                raise RepositoryError(
                    "Repository not found or this PAT cannot access it. For organization repositories, "
                    "the PAT Resource owner must be that organization and the token may need admin approval."
                ) from exc
            raise RepositoryError("Repository not found. For a private repository, provide a fine-grained PAT.") from exc
        if exc.code == 403:
            raise RepositoryError("GitHub denied access or its API rate limit was reached.") from exc
        raise RepositoryError(f"GitHub returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RepositoryError(f"Could not reach GitHub: {exc.reason}") from exc


def _safe_text_path(path: PurePosixPath) -> bool:
    lowered = {part.lower() for part in path.parts}
    name = path.name.lower()
    if not path.parts or path.is_absolute() or ".." in path.parts:
        return False
    if lowered & SKIP_PARTS or name in SECRET_NAMES:
        return False
    if name.startswith(".env") and name not in {".env.example", ".env.sample"}:
        return False
    return path.suffix.lower() in TEXT_SUFFIXES or name in SPECIAL_NAMES


def _architecture_text_path(path: PurePosixPath) -> bool:
    if not _safe_text_path(path):
        return False
    lowered = {part.lower() for part in path.parts}
    name = path.name.lower()
    if lowered & ANALYSIS_SKIP_PARTS:
        return False
    if any(marker in name for marker in (".spec.", ".test.")):
        return False
    if name.startswith(("playwright.", "vitest.", "jest.")):
        return False
    return True


def _api_json(url: str, token: str | None, private_access: bool) -> dict:
    try:
        with urllib.request.urlopen(_request(url, token), timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            if private_access:
                raise RepositoryError(
                    "Repository not found or this PAT cannot access it. For organization repositories, "
                    "the PAT Resource owner must be that organization and the token may need admin approval."
                ) from exc
            raise RepositoryError("Repository not found. For a private repository, provide a fine-grained PAT.") from exc
        if exc.code == 403:
            raise RepositoryError("GitHub denied access or its API rate limit was reached.") from exc
        raise RepositoryError(f"GitHub returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise RepositoryError(f"Could not reach GitHub: {exc.reason}") from exc


def _path_priority(path: str) -> tuple[int, int, str]:
    parsed = PurePosixPath(path)
    name = parsed.name.lower()
    architecture_names = {
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "dockerfile",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "procfile",
    }
    entrypoints = {"main.py", "app.py", "server.py", "index.js", "index.ts", "main.go"}
    if name.startswith("readme") or name in architecture_names:
        rank = 0
    elif ".github" in {part.lower() for part in parsed.parts} or parsed.suffix.lower() in {".tf", ".tfvars"}:
        rank = 1
    elif name in entrypoints or any(
        part.lower()
        in {
            "adapters",
            "api",
            "clients",
            "engine",
            "integrations",
            "ml",
            "pipeline",
            "pipelines",
            "providers",
            "rag",
            "routers",
            "services",
            "workflows",
        }
        for part in parsed.parts[:-1]
    ) or any(
        marker in name
        for marker in (
            "assistant",
            "chat",
            "client",
            "config",
            "predict",
            "provider",
            "rank",
            "recommend",
            "retriev",
            "router",
            "service",
            "settings",
        )
    ):
        rank = 2
    else:
        rank = 3
    return rank, len(parsed.parts), path.lower()


def _raw_file(
    owner: str,
    name: str,
    branch: str,
    entry: dict,
    token: str | None,
    private_access: bool,
) -> tuple[str, bytes] | None:
    path = str(entry["path"])
    try:
        if token:
            document = _api_json(str(entry["url"]), token, private_access)
            if document.get("encoding") != "base64" or not isinstance(document.get("content"), str):
                return None
            raw = base64.b64decode(document["content"], validate=False)
        else:
            raw_url = (
                f"https://raw.githubusercontent.com/{quote(owner)}/{quote(name)}/"
                f"{quote(branch, safe='')}/{quote(path, safe='/')}"
            )
            with urllib.request.urlopen(_request(raw_url), timeout=25) as response:
                raw = response.read(MAX_FILE_BYTES + 1)
    except (ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None
    if len(raw) > MAX_FILE_BYTES or b"\x00" in raw[:4096]:
        return None
    return path, raw


def snapshot_from_git_tree(
    owner: str,
    name: str,
    branch: str,
    tree: dict,
    token: str | None = None,
    private_access: bool = False,
) -> RepositorySnapshot:
    entries = tree.get("tree")
    if not isinstance(entries, list):
        raise RepositoryError("GitHub returned an invalid repository file tree.")
    if len(entries) > 100_000:
        raise RepositoryError("Repository contains too many files to inspect safely.")
    candidates = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "blob" or not entry.get("url"):
            continue
        path = PurePosixPath(str(entry.get("path", "")))
        size = entry.get("size")
        if _architecture_text_path(path) and isinstance(size, int) and size <= MAX_FILE_BYTES:
            candidates.append(entry)
    candidates.sort(key=lambda item: _path_priority(str(item["path"])))
    candidates = candidates[:MAX_API_FILES]

    downloaded: dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="repo2drawio-github") as executor:
        futures = {
            executor.submit(_raw_file, owner, name, branch, entry, token, private_access): entry
            for entry in candidates
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                downloaded[result[0]] = result[1]

    files: dict[str, str] = {}
    total = 0
    for entry in candidates:
        path = str(entry["path"])
        raw = downloaded.get(path)
        if raw is None or total + len(raw) > MAX_TEXT_BYTES:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        files[path] = text
        total += len(raw)
    if not files:
        raise RepositoryError("No supported text files were found in this repository.")
    return RepositorySnapshot(
        owner=owner,
        name=name,
        url=f"https://github.com/{owner}/{name}",
        files=files,
    )


def _fetch_repository_via_api(
    owner: str,
    name: str,
    token: str | None,
    private_access: bool,
) -> RepositorySnapshot:
    repository = _api_json(f"https://api.github.com/repos/{owner}/{name}", token, private_access)
    branch = repository.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise RepositoryError("Could not determine the repository default branch.")
    tree_url = (
        f"https://api.github.com/repos/{owner}/{name}/git/trees/"
        f"{quote(branch, safe='')}?recursive=1"
    )
    tree = _api_json(tree_url, token, private_access)
    return snapshot_from_git_tree(owner, name, branch, tree, token, private_access)


def snapshot_from_archive(owner: str, name: str, archive: bytes) -> RepositorySnapshot:
    files: dict[str, str] = {}
    total = 0
    try:
        zipped = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise RepositoryError("GitHub returned an invalid repository archive.") from exc

    infos = [item for item in zipped.infolist() if not item.is_dir()]
    if len(infos) > 20_000:
        raise RepositoryError("Repository contains too many files to inspect safely.")
    infos.sort(
        key=lambda item: _path_priority(
            str(PurePosixPath(*PurePosixPath(item.filename).parts[1:]))
        )
    )
    for info in infos:
        original = PurePosixPath(info.filename)
        relative = PurePosixPath(*original.parts[1:]) if len(original.parts) > 1 else original
        if not _architecture_text_path(relative) or info.file_size > MAX_FILE_BYTES:
            continue
        # Prevent highly compressed entries from expanding into a zip bomb.
        if info.compress_size and info.file_size / info.compress_size > 150:
            continue
        if len(files) >= MAX_FILES or total + info.file_size > MAX_TEXT_BYTES:
            break
        raw = zipped.read(info)
        if b"\x00" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        files[str(relative)] = text
        total += len(raw)

    if not files:
        raise RepositoryError("No supported text files were found in this repository.")
    return RepositorySnapshot(
        owner=owner,
        name=name,
        url=f"https://github.com/{owner}/{name}",
        files=files,
    )


def fetch_repository(
    url: str,
    token: str | None = None,
    private_access: bool = False,
) -> RepositorySnapshot:
    owner, name = parse_github_url(url)
    try:
        archive = _download_archive(owner, name, token, private_access)
    except ArchiveTooLarge:
        return _fetch_repository_via_api(owner, name, token, private_access)
    return snapshot_from_archive(owner, name, archive)
