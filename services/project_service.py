"""Project save/load service (PLAN 14).

Versioned JSON metadata only (.vveproj). Never copies media, never touches
Tkinter, never runs Piper or FFmpeg.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional, Union

PathLike = Union[str, Path]

FORMAT_ID = "video_voice_editor_project"
SUPPORTED_VERSION = 1
EXTENSION = ".vveproj"


class ProjectError(Exception):
    """Base class for project save/load failures."""


class ProjectValidationError(ProjectError):
    """Raised when a project file is malformed or unsupported."""


def store_path(path: PathLike | None, project_file: PathLike) -> Optional[str]:
    """Store a path relative to the project file when inside its directory.

    Files outside the project directory are stored as absolute paths.
    None/empty input stays None.
    """
    if not path:
        return None
    project_dir = Path(project_file).resolve().parent
    try:
        target = Path(path).resolve()
    except OSError:
        return str(path)
    try:
        return str(target.relative_to(project_dir))
    except ValueError:
        return str(target)


def resolve_path(stored: Optional[str], project_file: PathLike) -> Optional[str]:
    """Resolve a stored path: relative ones anchor at the .vveproj directory."""
    if not stored:
        return None
    candidate = Path(stored)
    if candidate.is_absolute():
        return str(candidate)
    return os.path.normpath(
        os.path.join(str(Path(project_file).resolve().parent), stored)
    )


def _require_int(value: Any, label: str, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProjectValidationError(f"{label} must be an integer: {value!r}")
    if minimum is not None and value < minimum:
        raise ProjectValidationError(f"{label} must be >= {minimum}: {value!r}")
    return value


def _require_str(value: Any, label: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ProjectValidationError(f"{label} must be a string: {value!r}")
    if not allow_empty and not value:
        raise ProjectValidationError(f"{label} must not be empty.")
    return value


def _validate_subtitle(entry: Any) -> dict:
    if not isinstance(entry, Mapping):
        raise ProjectValidationError(f"Subtitle entry must be an object: {entry!r}")
    index = _require_int(entry.get("index"), "subtitle.index", minimum=1)
    start_ms = _require_int(entry.get("start_ms"), "subtitle.start_ms", minimum=0)
    end_ms = _require_int(entry.get("end_ms"), "subtitle.end_ms", minimum=0)
    if end_ms <= start_ms:
        raise ProjectValidationError(
            f"subtitle end_ms must exceed start_ms: {entry!r}"
        )
    text = _require_str(entry.get("text"), "subtitle.text")
    voice = entry.get("voice", "")
    if voice is None:
        voice = ""
    voice = _require_str(voice, "subtitle.voice")
    return {"index": index, "start_ms": start_ms, "end_ms": end_ms,
            "text": text, "voice": voice}


def _validate_audio_mapping(value: Any) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ProjectValidationError("audio.subtitle_audio_paths must be an object.")
    mapping: dict = {}
    for key, path in value.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise ProjectValidationError(
                f"audio mapping key must be an integer index: {key!r}"
            ) from None
        if isinstance(index, bool) or index <= 0:
            raise ProjectValidationError(
                f"audio mapping key must be a positive index: {key!r}"
            )
        mapping[index] = _require_str(path, f"audio path for subtitle {index}",
                                      allow_empty=False)
    return mapping


def validate_project_data(data: Any) -> dict:
    """Validate a parsed project document; return the normalized document."""
    if not isinstance(data, Mapping):
        raise ProjectValidationError("Project root must be a JSON object.")
    if data.get("format") != FORMAT_ID:
        raise ProjectValidationError(
            f"Unknown project format: {data.get('format')!r}"
        )
    if data.get("version") != SUPPORTED_VERSION:
        raise ProjectValidationError(
            f"Unsupported project version: {data.get('version')!r} "
            f"(supported: {SUPPORTED_VERSION})"
        )
    subtitles = data.get("subtitles", [])
    if not isinstance(subtitles, list):
        raise ProjectValidationError("Project 'subtitles' must be a list.")
    normalized = dict(data)
    normalized["subtitles"] = [_validate_subtitle(entry) for entry in subtitles]
    audio = data.get("audio", {}) or {}
    if not isinstance(audio, Mapping):
        raise ProjectValidationError("Project 'audio' must be an object.")
    normalized_audio = dict(audio)
    normalized_audio["subtitle_audio_paths"] = _validate_audio_mapping(
        audio.get("subtitle_audio_paths")
    )
    normalized["audio"] = normalized_audio
    return normalized


def save_project(path: PathLike, data: Mapping) -> Path:
    """Atomically write a validated project document as readable UTF-8 JSON."""
    if not isinstance(data, Mapping):
        raise ProjectError("Project data must be a mapping.")
    if data.get("format") != FORMAT_ID or data.get("version") != SUPPORTED_VERSION:
        raise ProjectError("Project data has an invalid format envelope.")
    dest = Path(path)
    if dest.suffix.lower() != EXTENSION:
        dest = dest.with_suffix(EXTENSION)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectError(f"Cannot create project directory: {exc}") from exc
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise ProjectError(f"Cannot write project file: {exc}") from exc
    return dest


def load_project(path: PathLike) -> dict:
    """Read, parse, and validate a project file; never mutates app state."""
    src = Path(path)
    try:
        raw = src.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ProjectError(f"Cannot read project file: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectValidationError(f"Project file is not valid JSON: {exc}") from exc
    return validate_project_data(data)
