"""Local Piper voice discovery.

This module only discovers locally installed Piper voice files. It does not
launch Piper, synthesize speech, generate audio, or modify subtitle timing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Union


VOICE_DIRECTORIES = ("piper", "piper-en")
PathLike = Union[str, Path]


@dataclass(frozen=True)
class PiperVoice:
    """A locally discovered Piper model/configuration pair."""

    name: str
    model_path: str
    config_path: str
    source: str = ""
    language: str = ""
    dataset: str = ""
    phoneme_type: str = ""
    sample_rate: Optional[int] = None
    num_speakers: Optional[int] = None


class PiperService:
    """Discover locally installed Piper voices without using Tkinter."""

    def __init__(
        self,
        config_root: PathLike | None = None,
        voice_directories: Iterable[str] = VOICE_DIRECTORIES,
    ) -> None:
        self._config_root = Path(config_root) if config_root is not None else None
        self._voice_directories = tuple(voice_directories)

    def discover_voices(self) -> list[PiperVoice]:
        """Discover valid local Piper model/config pairs."""
        config_root = (
            self._config_root if self._config_root is not None else default_config_root()
        )
        return discover_voices(config_root, self._voice_directories)


def default_config_root() -> Path:
    """Return the project's ``config`` directory."""
    return Path(__file__).resolve().parent.parent / "config"


def _is_model_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".onnx"


def _paired_config_path(model_path: Path) -> Path:
    return model_path.with_name(model_path.name + ".json")


def _safe_text(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _safe_int(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _nested_text(data: Mapping[str, object], *keys: str) -> str:
    current: object = data
    for key in keys:
        if not isinstance(current, Mapping):
            return ""
        current = current.get(key)
    return _safe_text(current)


def _read_config_data(config_path: Path) -> Optional[dict]:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return {}
    return data


def _metadata_from_config(data: Mapping[str, object]) -> dict:
    language_config = data.get("language")
    if isinstance(language_config, Mapping):
        language = _safe_text(language_config.get("code"))
    else:
        language = _safe_text(language_config)
    if not language:
        language = _nested_text(data, "espeak", "voice")

    audio = data.get("audio")
    if not isinstance(audio, Mapping):
        audio = {}

    return {
        "language": language,
        "dataset": _safe_text(data.get("dataset")),
        "phoneme_type": _safe_text(data.get("phoneme_type")),
        "sample_rate": _safe_int(audio.get("sample_rate")),
        "num_speakers": _safe_int(data.get("num_speakers")),
    }


def discover_voices(
    config_root: PathLike | None = None,
    voice_directories: Iterable[str] = VOICE_DIRECTORIES,
) -> list[PiperVoice]:
    """Discover valid local Piper model/config pairs.

    A voice is valid only when both ``<voice>.onnx`` and the matching
    ``<voice>.onnx.json`` exist as regular files and the JSON configuration
    can be parsed. Invalid, unreadable, or unpaired files are skipped.
    """
    root = Path(config_root) if config_root is not None else default_config_root()
    voices: list[PiperVoice] = []
    seen: set[tuple[str, str]] = set()

    for directory_name in voice_directories:
        voice_directory = root / directory_name
        try:
            model_files = sorted(
                (path for path in voice_directory.rglob("*") if _is_model_file(path)),
                key=lambda path: path.name.casefold(),
            )
        except OSError:
            continue

        for model_path in model_files:
            config_path = _paired_config_path(model_path)
            if not config_path.is_file():
                continue
            try:
                key = (str(model_path.resolve()), str(config_path.resolve()))
            except OSError:
                continue
            if key in seen:
                continue

            config_data = _read_config_data(config_path)
            if config_data is None:
                continue

            seen.add(key)
            voices.append(
                PiperVoice(
                    name=model_path.stem,
                    model_path=key[0],
                    config_path=key[1],
                    source=voice_directory.name,
                    **_metadata_from_config(config_data),
                )
            )

    return voices
