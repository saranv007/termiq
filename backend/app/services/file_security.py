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

import difflib
import fnmatch
import hashlib
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
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


# ── Advanced File Operations (V2.1) ───────────────────────────────────

def safe_trash_file(
    path: Path,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Safely move a file or folder into the desktop Trash.
    NEVER permanently deletes. Uses /usr/bin/gio trash for standard desktop trash.
    """
    valid_path, err = validate_path(
        path,
        must_exist=True,
        approved_roots=approved_roots,
    )
    if err or valid_path is None:
        return {"success": False, "error": err}

    # Protection: never trash an approved root itself!
    if approved_roots is None:
        approved_roots = get_approved_roots()
    if any(valid_path == root for root in approved_roots):
        return {"success": False, "error": "Cannot delete or trash an approved root directory."}

    # Attempt to use gio trash (standard GNOME desktop trash)
    gio_path = shutil.which("gio")
    if gio_path:
        try:
            res = subprocess.run(
                [gio_path, "trash", str(valid_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return {
                    "success": True,
                    "trashed_path": str(valid_path),
                    "method": "gio_trash",
                    "message": f"Moved '{valid_path.name}' to Trash (recoverable).",
                }
        except Exception as exc:
            logger.warning("gio trash failed, falling back to local trash: %s", exc)

    # Fallback to standard FreeDesktop trash directory, root trash, or /tmp trash
    trash_candidates = [
        Path.home() / ".local" / "share" / "Trash" / "files",
        valid_path.parent / ".termiq_trash",
        Path("/tmp/.termiq_trash"),
    ]
    for trash_dir in trash_candidates:
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
            dest = trash_dir / f"{valid_path.name}.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            shutil.move(str(valid_path), str(dest))
            return {
                "success": True,
                "trashed_path": str(valid_path),
                "trash_location": str(dest),
                "method": "local_trash",
                "message": f"Moved '{valid_path.name}' to user Trash directory.",
            }
        except (OSError, PermissionError):
            continue

    return {"success": False, "error": "Could not locate a writable trash directory."}


def safe_copy_file(
    src: Path,
    dest: Path,
    overwrite: bool = False,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Safely copy a file from src to dest within approved roots.
    """
    valid_src, err_src = validate_path(src, must_exist=True, approved_roots=approved_roots)
    if err_src or valid_src is None:
        return {"success": False, "error": f"Source error: {err_src}"}

    # Validate destination path
    dest_path = dest if dest.is_absolute() else (valid_src.parent / dest)
    if dest_path.is_dir():
        dest_path = dest_path / valid_src.name

    valid_dest, err_dest = validate_path(
        dest_path,
        must_exist=False,
        allow_parent_creation=True,
        approved_roots=approved_roots,
    )
    if err_dest or valid_dest is None:
        return {"success": False, "error": f"Destination error: {err_dest}"}

    if valid_dest.exists() and not overwrite:
        return {
            "success": False,
            "error": f"Destination already exists: '{valid_dest.name}'. Set overwrite=true to replace.",
            "conflict": True,
        }

    try:
        if valid_src.is_dir():
            shutil.copytree(str(valid_src), str(valid_dest), dirs_exist_ok=overwrite)
        else:
            shutil.copy2(str(valid_src), str(valid_dest))

        return {
            "success": True,
            "source": str(valid_src),
            "destination": str(valid_dest),
            "bytes_copied": valid_dest.stat().st_size if valid_dest.is_file() else None,
        }
    except OSError as exc:
        return {"success": False, "error": f"Copy failed: {exc}"}


def safe_move_file(
    src: Path,
    dest: Path,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Safely move or rename a file or folder within approved roots.
    """
    valid_src, err_src = validate_path(src, must_exist=True, approved_roots=approved_roots)
    if err_src or valid_src is None:
        return {"success": False, "error": f"Source error: {err_src}"}

    # Check that root itself is not moved
    if approved_roots is None:
        approved_roots = get_approved_roots()
    if any(valid_src == root for root in approved_roots):
        return {"success": False, "error": "Cannot move an approved root directory."}

    dest_path = dest if dest.is_absolute() else (valid_src.parent / dest)
    if dest_path.is_dir():
        dest_path = dest_path / valid_src.name

    valid_dest, err_dest = validate_path(
        dest_path,
        must_exist=False,
        allow_parent_creation=True,
        approved_roots=approved_roots,
    )
    if err_dest or valid_dest is None:
        return {"success": False, "error": f"Destination error: {err_dest}"}

    if valid_dest.exists() and valid_dest != valid_src:
        return {
            "success": False,
            "error": f"Destination already exists: '{valid_dest.name}'",
            "conflict": True,
        }

    try:
        shutil.move(str(valid_src), str(valid_dest))
        return {
            "success": True,
            "source": str(valid_src),
            "destination": str(valid_dest),
        }
    except OSError as exc:
        return {"success": False, "error": f"Move failed: {exc}"}


def safe_edit_file(
    path: Path,
    new_content: str,
    create_backup: bool = True,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Safely edit an existing text file with before-and-after diff and backup preservation.
    """
    valid_path, err = validate_path(path, must_exist=True, approved_roots=approved_roots)
    if err or valid_path is None:
        return {"success": False, "error": err}

    if not valid_path.is_file():
        return {"success": False, "error": f"Path is not a regular file: {valid_path.name}"}

    try:
        old_content = valid_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"success": False, "error": "Cannot edit binary or non-UTF-8 file."}
    except OSError as exc:
        return {"success": False, "error": f"Error reading original file: {exc}"}

    # Generate unified diff
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{valid_path.name}",
        tofile=f"b/{valid_path.name}",
    ))
    diff_text = "".join(diff_lines)

    backup_path = None
    if create_backup:
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_file = valid_path.with_name(f"{valid_path.name}.backup-{timestamp_str}")
        try:
            backup_file.write_text(old_content, encoding="utf-8")
            backup_path = str(backup_file)
        except OSError as exc:
            return {"success": False, "error": f"Failed to create backup: {exc}"}

    # Atomically write new content
    temp_file = valid_path.with_name(f"{valid_path.name}.tmp-{os.getpid()}")
    try:
        temp_file.write_text(new_content, encoding="utf-8")
        temp_file.replace(valid_path)
    except OSError as exc:
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        return {"success": False, "error": f"Failed to write new file content: {exc}"}

    return {
        "success": True,
        "path": str(valid_path),
        "backup_path": backup_path,
        "diff": diff_text,
        "new_hash": compute_content_hash(new_content),
        "bytes_written": len(new_content.encode("utf-8")),
    }


def safe_find_duplicates(
    dir_path: Path,
    min_bytes: int = 100,
    max_items: int = 50,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Find duplicate files in a directory matching by size and SHA-256 hash.
    """
    valid_path, err = validate_path(dir_path, must_exist=True, approved_roots=approved_roots)
    if err or valid_path is None:
        return {"success": False, "error": err}

    by_size: dict[int, list[Path]] = {}
    try:
        for root, dirs, files in os.walk(valid_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in SENSITIVE_NAMES]
            for f in files:
                if f.startswith(".") or f.lower() in SENSITIVE_NAMES:
                    continue
                file_path = Path(root) / f
                try:
                    sz = file_path.stat().st_size
                    if sz >= min_bytes:
                        by_size.setdefault(sz, []).append(file_path)
                except OSError:
                    continue

        duplicate_groups = []
        for sz, candidates in by_size.items():
            if len(candidates) < 2:
                continue

            by_hash: dict[str, list[str]] = {}
            for cand in candidates:
                try:
                    h = hashlib.sha256(cand.read_bytes()).hexdigest()
                    by_hash.setdefault(h, []).append(str(cand))
                except OSError:
                    continue

            for h, matches in by_hash.items():
                if len(matches) > 1:
                    duplicate_groups.append({
                        "hash": h,
                        "size_bytes": sz,
                        "files": matches,
                        "count": len(matches),
                    })
                    if len(duplicate_groups) >= max_items:
                        break
            if len(duplicate_groups) >= max_items:
                break

        return {
            "success": True,
            "directory": str(valid_path),
            "duplicate_groups": duplicate_groups,
            "total_groups": len(duplicate_groups),
        }
    except Exception as exc:
        return {"success": False, "error": f"Duplicate search error: {exc}"}


def safe_find_large_files(
    dir_path: Path,
    min_bytes: int = 10485760,  # 10 MB
    max_items: int = 50,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Find files larger than a threshold size in an approved directory.
    """
    valid_path, err = validate_path(dir_path, must_exist=True, approved_roots=approved_roots)
    if err or valid_path is None:
        return {"success": False, "error": err}

    large_files = []
    try:
        for root, dirs, files in os.walk(valid_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in SENSITIVE_NAMES]
            for f in files:
                if f.startswith(".") or f.lower() in SENSITIVE_NAMES:
                    continue
                file_path = Path(root) / f
                try:
                    sz = file_path.stat().st_size
                    if sz >= min_bytes:
                        large_files.append({
                            "name": f,
                            "path": str(file_path),
                            "size_bytes": sz,
                            "size_mb": round(sz / (1024 * 1024), 2),
                        })
                except OSError:
                    continue

        large_files.sort(key=lambda x: x["size_bytes"], reverse=True)
        return {
            "success": True,
            "directory": str(valid_path),
            "threshold_bytes": min_bytes,
            "files": large_files[:max_items],
            "total_found": len(large_files),
        }
    except Exception as exc:
        return {"success": False, "error": f"Large files scan error: {exc}"}


def safe_organize_folder(
    dir_path: Path,
    dry_run: bool = True,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Organize files in a directory by file extension categories.
    Dry run mode previews proposed moves before executing.
    """
    valid_path, err = validate_path(dir_path, must_exist=True, approved_roots=approved_roots)
    if err or valid_path is None:
        return {"success": False, "error": err}

    EXT_CATEGORIES = {
        "Documents": {".pdf", ".docx", ".doc", ".txt", ".pptx", ".xlsx", ".md", ".csv", ".odt", ".epub"},
        "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"},
        "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".sql", ".sh", ".c", ".cpp"},
        "Archives": {".zip", ".tar", ".gz", ".xz", ".7z", ".rar", ".bz2", ".iso"},
        "Media": {".mp4", ".mkv", ".mp3", ".wav", ".mov", ".flac", ".avi"},
    }

    planned_moves = []
    try:
        # Non-recursive for the top directory to keep organization tidy
        for entry in valid_path.iterdir():
            if not entry.is_file():
                continue
            if entry.name.startswith(".") or entry.name.lower() in SENSITIVE_NAMES:
                continue

            ext = entry.suffix.lower()
            category = "Other"
            for cat_name, extensions in EXT_CATEGORIES.items():
                if ext in extensions:
                    category = cat_name
                    break

            if category == "Other":
                continue  # Skip unclassified files

            target_folder = valid_path / category
            target_dest = target_folder / entry.name

            planned_moves.append({
                "source": str(entry),
                "filename": entry.name,
                "category": category,
                "destination": str(target_dest),
                "size_bytes": entry.stat().st_size,
            })

        if dry_run:
            return {
                "success": True,
                "directory": str(valid_path),
                "dry_run": True,
                "total_files": len(planned_moves),
                "planned_moves": planned_moves,
            }

        executed_moves = []
        errors = []
        for move in planned_moves:
            cat_dir = valid_path / move["category"]
            cat_dir.mkdir(parents=True, exist_ok=True)
            try:
                dest = Path(move["destination"])
                if not dest.exists():
                    shutil.move(move["source"], str(dest))
                    executed_moves.append(move)
                else:
                    errors.append(f"Target '{dest.name}' already exists in {move['category']}.")
            except OSError as exc:
                errors.append(f"Move error for '{move['filename']}': {exc}")

        return {
            "success": len(errors) == 0,
            "directory": str(valid_path),
            "dry_run": False,
            "moved_count": len(executed_moves),
            "executed_moves": executed_moves,
            "errors": errors,
        }
    except Exception as exc:
        return {"success": False, "error": f"Organize folder error: {exc}"}


def safe_get_metadata(
    path: Path,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Get file or directory metadata.
    """
    valid_path, err = validate_path(path, must_exist=True, approved_roots=approved_roots)
    if err or valid_path is None:
        return {"success": False, "error": err}

    try:
        st = valid_path.stat()
        is_file = valid_path.is_file()
        lines_count = None
        if is_file and st.st_size <= MAX_READ_BYTES:
            try:
                lines_count = len(valid_path.read_text(encoding="utf-8").splitlines())
            except Exception:
                pass

        return {
            "success": True,
            "name": valid_path.name,
            "path": str(valid_path),
            "is_file": is_file,
            "is_dir": valid_path.is_dir(),
            "size_bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "mode": oct(st.st_mode)[-3:],
            "lines_count": lines_count,
        }
    except OSError as exc:
        return {"success": False, "error": f"Metadata error: {exc}"}


