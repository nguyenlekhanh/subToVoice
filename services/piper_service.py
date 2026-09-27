"""Local Piper voice discovery and preview synthesis.

Discovery inspects locally installed Piper voice files. Synthesis runs the
locally installed Piper runtime once per preview request to generate a
temporary WAV. This module never touches Tkinter and never plays audio.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Union


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

def normalize_piper_input(text: str) -> str:
    """Collapse one subtitle into a single Piper stdin line (no trailing newline).

    Internal subtitle newlines become single spaces so one subtitle is one
    Piper input record instead of several utterances. Words, punctuation, and
    UTF-8 Vietnamese characters are preserved untouched; only line-boundary
    whitespace, carriage returns, and BOM marks are normalized away.
    """
    if not isinstance(text, str):
        raise PiperSynthesisError("Piper input must be a string.")
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    lines = [line.strip(" \t") for line in cleaned.split("\n")]
    return " ".join(line for line in lines if line)


def synthesize(
        self,
        text: str,
        voice: PiperVoice,
        output_wav: PathLike,
        piper_cmd: Sequence[str] | None = None,
        speaker: Optional[int] = None,
        timeout: int = 120,
        espeak_voice: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Path:
        """Generate a preview WAV with the given voice (GUI-independent)."""
        return synthesize(
            text, voice, output_wav,
            piper_cmd=piper_cmd, speaker=speaker, timeout=timeout,
            espeak_voice=espeak_voice, request_id=request_id,
        )


class PiperSynthesisError(Exception):
    """Raised when Piper preview synthesis cannot be completed."""


@dataclass(frozen=True)
class VoicePreviewResult:
    """One finished Preview Voice request (worker -> queue -> UI callback).

    The UI callback must play EXACTLY ``output_wav`` -- never reconstruct the
    path, never fall back to an older WAV. The fingerprint fields are captured
    in the worker immediately after Piper exits so the callback can prove the
    file was not changed before playback.
    """

    request_id: str
    subtitle_index: int
    subtitle_text: str
    voice_name: str
    output_wav: str
    success: bool
    error: str = ""
    wav_size: int = 0
    wav_sha256: str = ""
    wav_duration_s: float = 0.0


def find_piper_executable() -> Optional[str]:
    """Return the path of a `piper` executable on PATH, if any."""
    return shutil.which("piper")


def is_piper_module_available() -> bool:
    """Return True when `python -m piper` looks importable."""
    try:
        return importlib.util.find_spec("piper") is not None
    except (ImportError, ValueError):
        return False


def resolve_piper_base_command(piper_cmd: Sequence[str] | None = None) -> list[str]:
    """Resolve the base Piper command without model/output arguments."""
    if piper_cmd is not None:
        base = [str(part) for part in piper_cmd]
        if not base:
            raise PiperSynthesisError("Piper command override is empty.")
        return base
    executable = find_piper_executable()
    if executable:
        return [executable]
    if is_piper_module_available():
        return [sys.executable, "-m", "piper"]
    raise PiperSynthesisError(
        "Piper runtime not found. Install the Piper CLI "
        "(a `piper` executable on PATH or the `piper-tts` Python package) "
        "to enable voice preview."
    )


def default_config_root() -> Path:
    """Return the project's ``config`` directory."""
    return Path(__file__).resolve().parent.parent / "config"


def espeak_voice_from_config(config_path: PathLike) -> str:
    """Read the eSpeak voice id from a Piper ``<voice>.onnx.json`` file.

    Falls back to ``language.code`` when ``espeak.voice`` is absent.
    Returns "" when neither is present or the file is unreadable.
    Each voice therefore uses its OWN language -- Vietnamese models resolve
    to "vi", English models to "en-us"; nothing is forced globally.
    """
    data = _read_config_data(Path(config_path))
    if not data:
        return ""
    voice = _nested_text(data, "espeak", "voice")
    if voice:
        return voice
    return _nested_text(data, "language", "code")


def resolve_espeak_voice(voice: PiperVoice, override: Optional[str] = None) -> str:
    """Resolve the eSpeak voice id for the selected model.

    Priority: explicit override, the model's own ``.onnx.json``
    (``espeak.voice``, then ``language.code``), then the discovered
    ``PiperVoice.language`` metadata.
    """
    if override is not None:
        return override.strip()
    if voice.config_path:
        from_config = espeak_voice_from_config(voice.config_path)
        if from_config:
            return from_config
    return (voice.language or "").strip()


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


def synthesize(
    text: str,
    voice: PiperVoice,
    output_wav: PathLike,
    piper_cmd: Sequence[str] | None = None,
    speaker: Optional[int] = None,
    timeout: int = 120,
    espeak_voice: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Path:
    """Synthesize the exact given subtitle text to a WAV file with the given voice.

    The subtitle is normalized to ONE Piper input line (internal newlines
    become spaces) and delivered EXACTLY ONCE as UTF-8 bytes on stdin with a
    single terminating newline (stdin=PIPE + communicate + EOF via ``input=``);
    console/stdin is never inherited. Raises PiperSynthesisError on any
    validation, runtime, or generation failure.
    """
    if not isinstance(text, str):
        raise PiperSynthesisError("Cannot synthesize empty text.")
    normalized = normalize_piper_input(text)
    if not normalized.strip():
        raise PiperSynthesisError("Cannot synthesize empty text.")
    if not isinstance(voice, PiperVoice):
        raise PiperSynthesisError("Invalid voice: a discovered PiperVoice is required.")

    model_path = Path(voice.model_path) if voice.model_path else None
    if model_path is None or not model_path.is_file():
        raise PiperSynthesisError(f"Piper model file is missing: {voice.model_path}")
    config_path = Path(voice.config_path) if voice.config_path else None
    if config_path is None or not config_path.is_file():
        raise PiperSynthesisError(
            f"Piper model config is missing: {voice.config_path} "
            "(expected matching <voice>.onnx.json next to the model)"
        )

    output_path = Path(output_wav)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PiperSynthesisError(f"Cannot create output directory: {exc}") from exc

    base_cmd = resolve_piper_base_command(piper_cmd)
    resolved_espeak_voice = resolve_espeak_voice(voice, espeak_voice)
    resolved_speaker = speaker
    if resolved_speaker is None and (voice.num_speakers or 0) > 1:
        resolved_speaker = 0

    stdin_payload = (normalized + "\n").encode("utf-8")
    print("[PIPER]")
    print(f"request_id={request_id}")
    print(f"voice={voice.name} model={model_path}")
    print(f"config={config_path} espeak_voice={resolved_espeak_voice!r}")
    print(f"output_wav={output_path}")
    print(f"text={normalized!r}")
    print("[PIPER INPUT]")
    print(f"text_original={text!r}")
    print(f"text_normalized={normalized!r}")
    print(f"text_len={len(normalized)} stdin_bytes={len(stdin_payload)}")
    print(f"stdin_ends_with_newline={stdin_payload.endswith(chr(10).encode())}")

    cmd = list(base_cmd) + ["--model", str(model_path)]
    cmd += ["--config", str(config_path)]
    if resolved_espeak_voice:
        cmd += ["--espeak-voice", resolved_espeak_voice]
    cmd += ["--output_file", str(output_path)]
    if resolved_speaker is not None:
        cmd += ["--speaker", str(resolved_speaker)]
    print(f"[PIPER] CMD: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            input=stdin_payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PiperSynthesisError(
            f"Piper runtime not found: {base_cmd[0]}. "
            "Install the Piper CLI to enable voice preview."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PiperSynthesisError("Piper synthesis timed out.") from exc
    except OSError as exc:
        raise PiperSynthesisError(f"Cannot launch Piper runtime: {exc}") from exc

    stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    print("[PIPER OUTPUT]")
    print(f"request_id={request_id}")
    print(f"returncode={result.returncode}")
    print(f"output_wav={output_path}")
    if stderr:
        print(f"stderr={stderr[-500:]!r}")
    if result.returncode != 0:
        raise PiperSynthesisError(
            f"Piper synthesis failed (exit {result.returncode}): {stderr or 'no error output'}"
        )

    try:
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise PiperSynthesisError(
                f"Piper finished but no WAV was created: {output_path}"
            )
    except OSError as exc:
        raise PiperSynthesisError(f"Cannot verify Piper output WAV: {exc}") from exc

    return output_path


def wav_info(wav_path: PathLike) -> dict:
    """Inspect a WAV file header and content hash without modifying audio."""
    path = Path(wav_path)
    try:
        size = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PiperSynthesisError(f"Cannot read WAV file: {path} ({exc})") from exc
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
    except (wave.Error, EOFError, OSError) as exc:
        raise PiperSynthesisError(f"Not a readable WAV file: {path} ({exc})") from exc
    duration_s = frames / sample_rate if sample_rate else 0.0
    return {
        "path": str(path),
        "size": size,
        "sha256": digest,
        "channels": channels,
        "sample_width": sample_width,
        "sample_rate": sample_rate,
        "frames": frames,
        "duration_s": round(duration_s, 3),
    }


def resolve_voice_by_name(voices, name: Optional[str]) -> Optional[PiperVoice]:
    """Find a discovered voice by name; None when missing/blank/unknown."""
    wanted = (name or "").strip()
    if not wanted:
        return None
    for voice in voices or ():
        if voice.name == wanted:
            return voice
    return None


def batch_output_path(output_dir: PathLike, subtitle_index: int, batch_id: str) -> Path:
    """Unique WAV path for one subtitle in a batch (never a fixed filename)."""
    return Path(output_dir) / f"subtitle_{subtitle_index:04d}_{batch_id}.wav"


def generate_batch_voices(
    work_items,
    output_dir: PathLike,
    batch_id: str,
    voice: PiperVoice,
    *,
    piper_cmd: Sequence[str] | None = None,
    speaker: Optional[int] = None,
    timeout: int = 120,
    espeak_voice: Optional[str] = None,
    cancel_event=None,
    progress_callback=None,
    voices_by_name: Optional[Mapping[str, PiperVoice]] = None,
) -> tuple:
    """Generate one WAV per subtitle; GUI-independent batch worker core.

    Args:
        work_items: iterable of (subtitle_index, subtitle_text) or
            (subtitle_index, subtitle_text, voice_name). A per-item voice
            name selects that voice from ``voices_by_name``; an empty name
            (or no map) falls back to the global ``voice`` for compatibility.
        output_dir: directory receiving subtitle_IIII_<batch_id>.wav files.
        batch_id: unique id for this batch run.
        voice: fallback/global PiperVoice (also used when no per-item map).
        cancel_event: optional threading.Event; checked before each item.
        progress_callback: optional callable
            (batch_id, done, total, subtitle_index, ok, detail).
        voices_by_name: optional {voice_name: PiperVoice} for per-subtitle
            voices. Unknown names record an error and skip that subtitle.

    Returns:
        (success_map, errors): {index: wav_path}, {index: error message}.
        One failing subtitle never stops the remaining ones.
    """
    if voice is None or not isinstance(voice, PiperVoice):
        raise PiperSynthesisError("No Piper voice selected.")
    items = list(work_items)
    total = len(items)
    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PiperSynthesisError(f"Cannot create output directory: {exc}") from exc

    def _voice_for(index: int, item_voice_name: str) -> PiperVoice:
        wanted = (item_voice_name or "").strip()
        if voices_by_name is not None and wanted:
            if hasattr(voices_by_name, "get"):
                resolved = voices_by_name.get(wanted)
            else:
                resolved = resolve_voice_by_name(voices_by_name, wanted)
            if resolved is None:
                raise PiperSynthesisError(
                    f"Voice '{wanted}' is not available."
                )
            return resolved
        return voice

    success_map: dict = {}
    errors: dict = {}
    for position, item in enumerate(items, start=1):
        subtitle_index, subtitle_text = item[0], item[1]
        item_voice_name = item[2] if len(item) > 2 else ""
        if cancel_event is not None and cancel_event.is_set():
            print(f"[VOICE BATCH] batch_request_id={batch_id} cancelled "
                  f"after {position - 1}/{total}")
            break
        output_path = batch_output_path(out_dir, subtitle_index, batch_id)
        try:
            item_voice = _voice_for(subtitle_index, item_voice_name)
        except PiperSynthesisError as exc:
            errors[subtitle_index] = str(exc)
            print(f"[VOICE BATCH] subtitle_index={subtitle_index} "
                  f"voice={item_voice_name!r} return=failed-voice "
                  f"error={exc}")
            if progress_callback is not None:
                progress_callback(batch_id, position, total, subtitle_index,
                                  False, str(exc))
            continue
        print("[VOICE BATCH]")
        print(f"batch_request_id={batch_id}")
        print(f"subtitle_index={subtitle_index}")
        print(f"text={subtitle_text!r}")
        print(f"voice={item_voice.name}")
        print(f"output_wav={output_path}")
        if not isinstance(subtitle_text, str) or not subtitle_text.strip():
            errors[subtitle_index] = "Subtitle text is empty."
            print(f"[VOICE BATCH] subtitle_index={subtitle_index} "
                  f"return=skipped-empty wav_exists=False wav_size=0")
            if progress_callback is not None:
                progress_callback(batch_id, position, total, subtitle_index,
                                  False, "empty text")
            continue
        try:
            synthesize(
                subtitle_text, item_voice, output_path,
                piper_cmd=piper_cmd, speaker=speaker, timeout=timeout,
                espeak_voice=espeak_voice, request_id=f"{batch_id}#{subtitle_index}",
            )
            info = wav_info(output_path)
            if info["frames"] <= 0:
                raise PiperSynthesisError("Generated WAV has no audio frames.")
            success_map[subtitle_index] = str(output_path)
            print(f"[VOICE BATCH] subtitle_index={subtitle_index} return=ok "
                  f"wav_exists=True wav_size={info['size']} "
                  f"duration={info['duration_s']}s sha256={info['sha256'][:16]}")
            if progress_callback is not None:
                progress_callback(batch_id, position, total, subtitle_index,
                                  True, f"{info['duration_s']}s")
        except Exception as exc:
            errors[subtitle_index] = str(exc)
            print(f"[VOICE BATCH] subtitle_index={subtitle_index} "
                  f"return=failed wav_exists={output_path.is_file()} wav_size=0 "
                  f"error={exc}")
            if progress_callback is not None:
                progress_callback(batch_id, position, total, subtitle_index,
                                  False, str(exc))
    return success_map, errors
