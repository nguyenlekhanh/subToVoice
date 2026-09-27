"""Safe cleanup of temporary generated files (PLAN 15).

Every function is GUI-independent and stdlib-only. Rules, in order:

1. Only top-level files inside an explicitly given application directory
   (temp/preview, temp/voices, temp/composed, output) are ever candidates.
   Subdirectories, unknown files, and anything outside are never touched.
2. Only known naming patterns are deleted (``*.wav`` previews,
   ``subtitle_*.wav`` batches, ``audio_*.wav`` compositions,
   ``*.vveproj.tmp`` atomic-save leftovers). Never extension-only sweeps.
3. Currently referenced/active files (passed in as keep sets) are preserved.
4. Missing or locked files (Windows) are logged and skipped -- never raised.
5. If uncertain: DO NOT DELETE. Functions return summary dicts; they never
   raise for per-file problems.

Batch voices, composed audio, and Final MP4s may back saved .vveproj
projects, so the application only auto-deletes Preview WAVs (never referenced
by projects) and stale save-tmp files. Voice/composed orphans are provided
for explicit use and covered by tests, not wired to automatic deletion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Union

PathLike = Union[str, Path]


def safe_unlink(path: PathLike) -> bool:
    """Delete one file; missing/locked files return False, never raise."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        return False
    except (PermissionError, OSError) as exc:
        print(f"[CLEANUP] cannot delete {path}: {exc}")
        return False
    return True


def _top_level_files(directory: Path):
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    return [entry for entry in entries if entry.is_file()]


def _resolve_keep(paths: Iterable[PathLike]) -> set:
    keep = set()
    for path in paths or ():
        try:
            keep.add(str(Path(path).resolve()))
        except OSError:
            keep.add(str(path))
    return keep


def cleanup_preview_files(preview_dir: PathLike, keep_paths=()) -> dict:
    """Delete stale Preview WAVs, keeping active files plus the newest one."""
    directory = Path(preview_dir)
    keep = _resolve_keep(keep_paths)
    wavs = sorted(
        (entry for entry in _top_level_files(directory)
         if entry.suffix.lower() == ".wav"),
        key=lambda entry: entry.name,
    )
    if wavs:
        try:
            keep.add(str(wavs[-1].resolve()))
        except OSError:
            keep.add(str(wavs[-1]))
    deleted, kept, errors = [], [], []
    for entry in wavs:
        try:
            resolved = str(entry.resolve())
        except OSError:
            resolved = str(entry)
        if resolved in keep:
            kept.append(str(entry))
            continue
        if safe_unlink(entry):
            deleted.append(str(entry))
            print(f"[CLEANUP] deleted stale preview {entry.name}")
        else:
            errors.append(str(entry))
    return {"deleted": deleted, "kept": kept, "errors": errors}


def cleanup_orphaned_files(directory: PathLike, prefix: str,
                            referenced_paths=()) -> dict:
    """Delete ``<prefix>*.wav`` files not in the referenced set.

    Used explicitly (never automatic) for ``subtitle_`` batch voices and
    ``audio_`` compositions. Unknown names, other extensions, subdirectories,
    and referenced files are always preserved.
    """
    base = Path(directory)
    keep = _resolve_keep(referenced_paths)
    deleted, kept, errors = [], [], []
    for entry in _top_level_files(base):
        if not entry.name.startswith(prefix) or entry.suffix.lower() != ".wav":
            kept.append(str(entry))
            continue
        try:
            resolved = str(entry.resolve())
        except OSError:
            resolved = str(entry)
        if resolved in keep:
            kept.append(str(entry))
            continue
        if safe_unlink(entry):
            deleted.append(str(entry))
            print(f"[CLEANUP] deleted orphan {entry.name}")
        else:
            errors.append(str(entry))
    return {"deleted": deleted, "kept": kept, "errors": errors}


def cleanup_stale_save_tmp_files(directory: PathLike) -> dict:
    """Delete ``*.vveproj.tmp`` leftovers from interrupted atomic saves."""
    base = Path(directory)
    deleted, kept, errors = [], [], []
    for entry in _top_level_files(base):
        if not entry.name.endswith(".vveproj.tmp"):
            kept.append(str(entry))
            continue
        if safe_unlink(entry):
            deleted.append(str(entry))
            print(f"[CLEANUP] deleted stale save-tmp {entry.name}")
        else:
            errors.append(str(entry))
    return {"deleted": deleted, "kept": kept, "errors": errors}


def cleanup_on_close(preview_dir: PathLike) -> dict:
    """Best-effort shutdown sweep: all Preview WAVs (playback already purged)."""
    if not Path(preview_dir).is_dir():
        return {"deleted": [], "kept": [], "errors": []}
    return cleanup_preview_files(preview_dir, keep_paths=())
