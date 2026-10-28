"""
Secure filesystem operations for TERMIQ File & Folder Copilot.

Enforces:
- Operations restricted to approved user roots beneath user's home.
- Rejection of path traversal, invalid characters, and symlink escapes.
- Safe, race-conscious exclusive file creation (O_EXCL).
- No shell execution; Python standard library only.
- Strict protection of sensitive directories (.ssh, .aws, .config, credentials).
- Text file size limits (64KB max for reads) and UTF-8 encoding checks.
"""

import fnmatch
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum file size allowed for reading in v2.0
MAX_READ_BYTES = 65536  # 64 KB

# Maximum directory listing / search results
MAX_ENTRIES = 100

# Sensitive directories and files that may never be accessed or created
SENSITIVE_NAMES = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".config",
    ".cache",
    ".local",
    ".mozilla",
    ".var",
    ".bashrc",
    ".bash_profile",
    ".profile",
    ".zshrc",
    ".env",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "authorized_keys",
    "known_hosts",
}


def compute_content_hash(content: str) -> str:
    """Compute standard SHA-256 hex digest of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_approved_roots(custom_roots: Optional[list[Path]] = None) -> list[Path]:
    """
    Return approved user roots.

    Defaults to user's standard project/document roots beneath $HOME.
    Tests can supply custom_roots pointing to tmp directories.
    """
    if custom_roots is not None:
        return [r.resolve() for r in custom_roots]

    home = Path.home().resolve()
    candidates = [
        home / "Projects",
        home / "projects",
        home / "Documents",
        home / "Downloads",
        home / "Desktop",
    ]

    approved = []
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            resolved = candidate.resolve()
            if resolved not in approved:
                approved.append(resolved)

    # Fallback to home itself if none of the standard subdirs exist
    if not approved and home.exists():
        approved.append(home)

    return approved


def is_safe_filename(name: str) -> bool:
    """
    Validate that a single filename component is safe.
    Must not contain path separators, null bytes, or sensitive names.
    """
    if not name or len(name) > 255:
        return False

    if name in (".", ".."):
        return False

    if "/" in name or "\\" in name or "\0" in name:
        return False

    if name.lower() in SENSITIVE_NAMES:
        return False

    return True


def is_path_sensitive(path: Path) -> bool:
    """Check if any segment in the path contains a sensitive name."""
    parts = {p.lower() for p in path.parts}
    return bool(parts.intersection(SENSITIVE_NAMES))


def is_symlink_escape(path: Path, approved_roots: list[Path]) -> bool:
    """Check if path or any existing ancestor is a symlink pointing outside approved roots."""
    try:
        curr = path
        while curr != curr.parent:
            if curr.is_symlink():
                target = curr.resolve()
                if not any(target == root or root in target.parents for root in approved_roots):
                    return True
            curr = curr.parent
    except (OSError, RuntimeError):
        return True
    return False


def validate_path(
    path_input: str | Path,
    must_exist: bool = False,
    allow_parent_creation: bool = False,
    approved_roots: Optional[list[Path]] = None,
) -> tuple[Optional[Path], Optional[str]]:
    """
    Resolve and validate a filesystem path.

    Returns (resolved_path, None) on success or (None, error_message) on failure.
    Security checks:
    - Path expansion and normalization
    - Approved root containment
    - Path traversal rejection
    - Sensitive path rejection
    - Symlink escape rejection
    """
    if approved_roots is None:
        approved_roots = get_approved_roots()

    raw_str = str(path_input).strip()
    if not raw_str:
        return None, "Path cannot be empty."

    if "\0" in raw_str:
        return None, "Path contains invalid null byte."

    # Expand user ~
    try:
        p = Path(os.path.expanduser(raw_str))
    except Exception as exc:
        return None, f"Invalid path syntax: {exc}"

    # Check for relative traversal like ../../ escaping
    try:
        if not p.is_absolute():
            # Treat relative to the first approved root
            base = approved_roots[0] if approved_roots else Path.home()
            p = base / p

        resolved = p.resolve()
    except (OSError, RuntimeError) as exc:
        return None, f"Could not resolve path: {exc}"

    # Verify sensitive path segments
    if is_path_sensitive(resolved):
        return None, "Access to sensitive system or credential paths is forbidden."

    # Verify symlink escapes
    if is_symlink_escape(p, approved_roots):
        return None, "Symlink escapes outside approved roots are forbidden."

    # Verify containment within at least one approved root
    contained = any(
        resolved == root or root in resolved.parents
        for root in approved_roots
    )
    if not contained:
        return None, "Path is outside approved directories."

    if must_exist and not resolved.exists():
        return None, f"Path does not exist: {resolved.name}"

    if not must_exist and not allow_parent_creation:
        if not resolved.parent.exists():
            return None, f"Parent directory does not exist: {resolved.parent}"

    return resolved, None


def safe_create_file(
    path: Path,
    content: str,
    create_parents: bool = False,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Safely create a new file exclusively (O_EXCL).
    Refuses to overwrite an existing file.
    """
    valid_path, err = validate_path(
        path,
        must_exist=False,
        allow_parent_creation=create_parents,
        approved_roots=approved_roots,
    )
    if err or valid_path is None:
        return {"success": False, "error": err}

    if not is_safe_filename(valid_path.name):
        return {"success": False, "error": f"Invalid or unsafe filename: {valid_path.name}"}

    # Parent directory handling
    if create_parents and not valid_path.parent.exists():
        try:
            valid_path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
        except OSError as exc:
            return {"success": False, "error": f"Failed to create parent directories: {exc}"}
    elif not valid_path.parent.exists():
        return {"success": False, "error": f"Parent directory does not exist: {valid_path.parent}"}

    # Refuse overwrite — check existence before and use O_EXCL
    if valid_path.exists() or valid_path.is_symlink():
        return {
            "success": False,
            "error": f"Target file already exists: {valid_path.name}. Overwrite is forbidden.",
            "conflict": True,
        }

    encoded = content.encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(valid_path), flags, 0o644)
        with open(fd, "wb") as f:
            f.write(encoded)
    except FileExistsError:
        return {
            "success": False,
            "error": f"File appeared during creation: {valid_path.name}",
            "conflict": True,
        }
    except OSError as exc:
        return {"success": False, "error": f"Filesystem error creating file: {exc}"}

    return {
        "success": True,
        "path": str(valid_path),
        "name": valid_path.name,
        "bytes_written": len(encoded),
        "hash": compute_content_hash(content),
    }


def safe_create_folder(
    path: Path,
    create_parents: bool = False,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Safely create a new folder.
    Refuses if folder already exists.
    """
    valid_path, err = validate_path(
        path,
        must_exist=False,
        allow_parent_creation=create_parents,
        approved_roots=approved_roots,
    )
    if err or valid_path is None:
        return {"success": False, "error": err}

    if not is_safe_filename(valid_path.name):
        return {"success": False, "error": f"Invalid or unsafe folder name: {valid_path.name}"}

    if valid_path.exists():
        return {
            "success": False,
            "error": f"Folder already exists: {valid_path.name}",
            "conflict": True,
        }

    try:
        valid_path.mkdir(parents=create_parents, mode=0o755, exist_ok=False)
    except FileExistsError:
        return {
            "success": False,
            "error": f"Folder already exists: {valid_path.name}",
            "conflict": True,
        }
    except OSError as exc:
        return {"success": False, "error": f"Filesystem error creating folder: {exc}"}

    return {
        "success": True,
        "path": str(valid_path),
        "name": valid_path.name,
    }


def safe_read_text_file(
    path: Path,
    max_bytes: int = MAX_READ_BYTES,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Read a text file with size limit and UTF-8 verification.
    """
    valid_path, err = validate_path(
        path,
        must_exist=True,
        approved_roots=approved_roots,
    )
    if err or valid_path is None:
        return {"success": False, "error": err}

    if not valid_path.is_file():
        return {"success": False, "error": f"Path is not a regular file: {valid_path.name}"}

    try:
        stat = valid_path.stat()
        if stat.st_size > max_bytes:
            return {
                "success": False,
                "error": f"File size ({stat.st_size} bytes) exceeds safety limit ({max_bytes} bytes).",
            }

        with open(valid_path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "success": True,
            "path": str(valid_path),
            "name": valid_path.name,
            "size_bytes": stat.st_size,
            "content": content,
            "hash": compute_content_hash(content),
        }
    except UnicodeDecodeError:
        return {
            "success": False,
            "error": "File is binary or not valid UTF-8 text.",
        }
    except OSError as exc:
        return {"success": False, "error": f"Filesystem error reading file: {exc}"}


def safe_list_dir(
    dir_path: Path,
    max_items: int = MAX_ENTRIES,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    List files and subdirectories in a validated directory.
    Skips hidden entries and sensitive folders.
    """
    valid_path, err = validate_path(
        dir_path,
        must_exist=True,
        approved_roots=approved_roots,
    )
    if err or valid_path is None:
        return {"success": False, "error": err}

    if not valid_path.is_dir():
        return {"success": False, "error": f"Path is not a directory: {valid_path.name}"}

    items = []
    try:
        for entry in sorted(valid_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            # Skip hidden and sensitive items
            if entry.name.startswith(".") or entry.name.lower() in SENSITIVE_NAMES:
                continue

            try:
                is_directory = entry.is_dir()
                size = entry.stat().st_size if not is_directory else None
            except OSError:
                continue

            items.append({
                "name": entry.name,
                "is_dir": is_directory,
                "size_bytes": size,
            })

            if len(items) >= max_items:
                break

        return {
            "success": True,
            "directory": str(valid_path),
            "total_items": len(items),
            "items": items,
        }
    except OSError as exc:
        return {"success": False, "error": f"Filesystem error listing directory: {exc}"}


def safe_search_files(
    dir_path: Path,
    pattern: str,
    max_items: int = MAX_ENTRIES,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Search filenames recursively in a directory matching a pattern.
    Skips hidden directories and sensitive entries.
    """
    valid_path, err = validate_path(
        dir_path,
        must_exist=True,
        approved_roots=approved_roots,
    )
    if err or valid_path is None:
        return {"success": False, "error": err}

    if not valid_path.is_dir():
        return {"success": False, "error": f"Path is not a directory: {valid_path.name}"}

    clean_pattern = pattern.strip()
    if not clean_pattern:
        return {"success": False, "error": "Search pattern cannot be empty."}

    # Add wildcards if user entered simple string without wildcards
    glob_pattern = clean_pattern if any(c in clean_pattern for c in "*?[]") else f"*{clean_pattern}*"

    matches = []
    try:
        for root, dirs, files in os.walk(valid_path):
            # Prune hidden and sensitive dirs in-place
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".") and d.lower() not in SENSITIVE_NAMES
            ]

            for filename in files:
                if filename.startswith(".") or filename.lower() in SENSITIVE_NAMES:
                    continue

                if fnmatch.fnmatch(filename.lower(), glob_pattern.lower()):
                    full_p = Path(root) / filename
                    try:
                        rel = full_p.relative_to(valid_path)
                        matches.append({
                            "name": filename,
                            "relative_path": str(rel),
                            "full_path": str(full_p),
                            "size_bytes": full_p.stat().st_size,
                        })
                    except OSError:
                        continue

                    if len(matches) >= max_items:
                        break
            if len(matches) >= max_items:
                break

        return {
            "success": True,
            "directory": str(valid_path),
            "pattern": clean_pattern,
            "total_matches": len(matches),
            "matches": matches,
        }
    except OSError as exc:
        return {"success": False, "error": f"Filesystem error searching directory: {exc}"}

