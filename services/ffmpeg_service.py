"""
FFmpeg Service - audio composition and (later) video rendering.
"""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

PathLike = Union[str, Path]


class FFmpegService:
    """Service for FFmpeg video rendering and audio composition."""

    def __init__(self, ffmpeg_path: PathLike | None = None):
        # TODO: Initialize FFmpeg in a later plan
        self.ffmpeg_path = str(ffmpeg_path) if ffmpeg_path is not None else "ffmpeg"

    def render_final_video(self, video_path: str, audio_path: str, output_path: str):
        """Render final video with combined audio"""
        # TODO: Implement FFmpeg rendering in a later plan
        raise NotImplementedError("FFmpeg rendering not implemented yet")

    def combine_audio_tracks(self, audio_paths: list, output_path: str):
        """Combine multiple audio tracks"""
        # TODO: Implement audio combining in a later plan
        raise NotImplementedError("Audio combining not implemented yet")

    def find_ffmpeg(self) -> Optional[str]:
        """Return a discovered FFmpeg executable path, if any."""
        found = shutil.which(self.ffmpeg_path)
        if found:
            return found
        if self.ffmpeg_path != "ffmpeg":
            return None
        return shutil.which("ffmpeg")

    def compose_subtitle_audio(
        self,
        *,
        video_duration_ms: int,
        segments: Sequence[Mapping],
        audio_mapping: Mapping[int, PathLike],
        output_wav: PathLike,
        sample_rate: int = 48000,
        channels: int = 2,
        timeout: int = 300,
        request_id: Optional[str] = None,
    ) -> Path:
        """Compose one timeline WAV from per-subtitle voice WAVs.

        Each segment is a mapping with ``index`` and ``start_ms``; the WAV is
        taken from ``audio_mapping[index]`` and delayed to ``start_ms``.
        Gaps stay silent, overlaps are mixed, the result is trimmed to
        ``video_duration_ms`` and encoded as PCM WAV. Never modifies inputs.
        """
        return compose_subtitle_audio(
            video_duration_ms=video_duration_ms,
            segments=segments,
            audio_mapping=audio_mapping,
            output_wav=output_wav,
            sample_rate=sample_rate,
            channels=channels,
            timeout=timeout,
            request_id=request_id,
            ffmpeg_path=self.find_ffmpeg(),
        )

    def export_final_mp4(
        self,
        *,
        video_path: PathLike,
        composed_audio_wav: PathLike,
        output_mp4: PathLike,
        audio_bitrate: str = "192k",
        timeout: int = 600,
        request_id: Optional[str] = None,
    ) -> Path:
        """Mux original video with composed voice audio into a final MP4.

        Video stream is copied untouched; the composed WAV becomes the single
        AAC audio track (replacing any original audio). Never modifies inputs.
        """
        return export_final_mp4(
            video_path=video_path,
            composed_audio_wav=composed_audio_wav,
            output_mp4=output_mp4,
            audio_bitrate=audio_bitrate,
            timeout=timeout,
            request_id=request_id,
            ffmpeg_path=self.find_ffmpeg(),
        )


class FFmpegComposeError(Exception):
    """Raised when audio composition cannot be completed."""


def _read_wav_header(wav_path: Path) -> None:
    """Validate that a file is a readable, non-empty WAV."""
    try:
        size = wav_path.stat().st_size
    except OSError as exc:
        raise FFmpegComposeError(f"Audio file is missing: {wav_path} ({exc})") from exc
    if size <= 0:
        raise FFmpegComposeError(f"Audio file is empty: {wav_path}")
    try:
        with wave.open(str(wav_path), "rb") as wav:
            if wav.getnframes() <= 0:
                raise FFmpegComposeError(f"Audio file has no frames: {wav_path}")
    except (wave.Error, EOFError, OSError) as exc:
        raise FFmpegComposeError(f"Not a readable WAV file: {wav_path} ({exc})") from exc


def build_compose_command(
    *,
    ffmpeg_path: str,
    video_duration_ms: int,
    segments: Sequence[Mapping],
    audio_mapping: Mapping[int, PathLike],
    output_wav: PathLike,
    sample_rate: int = 48000,
    channels: int = 2,
) -> tuple:
    """Validate inputs and build (cmd, filter_description, resolved_segments).

    Pure function: no subprocess, no file writes. Raises FFmpegComposeError
    on any invalid input.
    """
    if not isinstance(video_duration_ms, int) or video_duration_ms <= 0:
        raise FFmpegComposeError(
            f"Video duration is unknown or invalid: {video_duration_ms!r}"
        )
    items = list(segments or [])
    if not items:
        raise FFmpegComposeError("Subtitle list is empty.")
    if not audio_mapping:
        raise FFmpegComposeError("Generated audio mapping is empty.")

    resolved = []
    for seg in items:
        try:
            index = int(seg["index"])
            start_ms = int(seg["start_ms"])
            end_ms = int(seg.get("end_ms", start_ms + 1))
        except (KeyError, TypeError, ValueError) as exc:
            raise FFmpegComposeError(f"Invalid subtitle timing entry: {seg!r} ({exc})") from exc
        if start_ms < 0:
            raise FFmpegComposeError(f"Subtitle #{index} starts before 0.")
        if end_ms <= start_ms:
            raise FFmpegComposeError(f"Subtitle #{index} has end <= start.")
        if start_ms >= video_duration_ms:
            raise FFmpegComposeError(
                f"Subtitle #{index} starts beyond the video duration."
            )
        if index not in audio_mapping:
            raise FFmpegComposeError(
                f"Missing generated audio for subtitle #{index}."
            )
        wav_path = Path(audio_mapping[index])
        _read_wav_header(wav_path)
        resolved.append({"index": index, "start_ms": start_ms, "wav": wav_path})

    if channels not in (1, 2):
        raise FFmpegComposeError(f"Unsupported channel count: {channels!r}")
    layout = "stereo" if channels == 2 else "mono"
    duration_s = video_duration_ms / 1000.0

    inputs: list = []
    delayed = []
    for position, entry in enumerate(resolved):
        delay_value = "|".join([str(max(0, entry["start_ms"]))] * channels)
        inputs += ["-i", str(entry["wav"])]
        delayed.append(
            f"[{position}:a]"
            f"aformat=sample_fmts=s16:sample_rates={sample_rate}:channel_layouts={layout},"
            f"adelay={delay_value}:all=1,"
            f"apad=whole_dur={duration_s:.3f}"
            f"[d{position}]"
        )
    mix_inputs = "".join(f"[d{position}]" for position in range(len(resolved)))
    filter_graph = (
        ";".join(delayed)
        + f";{mix_inputs}amix=inputs={len(resolved)}:duration=longest:"
        f"dropout_transition=0:normalize=0,"
        f"atrim=0:{duration_s:.3f},asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=s16:sample_rates={sample_rate}:channel_layouts={layout}"
        f"[mixout]"
    )
    cmd = (
        [ffmpeg_path]
        + inputs
        + ["-filter_complex", filter_graph, "-map", "[mixout]",
           "-c:a", "pcm_s16le", "-ar", str(sample_rate), "-ac", str(channels),
           "-y", str(output_wav)]
    )
    return cmd, filter_graph, resolved


def compose_subtitle_audio(
    *,
    video_duration_ms: int,
    segments: Sequence[Mapping],
    audio_mapping: Mapping[int, PathLike],
    output_wav: PathLike,
    sample_rate: int = 48000,
    channels: int = 2,
    timeout: int = 300,
    request_id: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
) -> Path:
    """Validate, run FFmpeg, and verify the composed timeline WAV."""
    exe = ffmpeg_path or shutil.which("ffmpeg")
    if not exe:
        raise FFmpegComposeError(
            "FFmpeg was not found. Please make sure FFmpeg is installed "
            "and available in PATH."
        )
    output_path = Path(output_wav)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FFmpegComposeError(f"Cannot create output directory: {exc}") from exc

    cmd, _, resolved = build_compose_command(
        ffmpeg_path=exe,
        video_duration_ms=video_duration_ms,
        segments=segments,
        audio_mapping=audio_mapping,
        output_wav=output_path,
        sample_rate=sample_rate,
        channels=channels,
    )
    print("[AUDIO COMPOSE]")
    print(f"request_id={request_id}")
    print(f"subtitle_count={len(resolved)}")
    for entry in resolved:
        print(f"input=#{entry['index']} start_ms={entry['start_ms']} wav={entry['wav']}")
    print(f"output={output_path}")
    print(f"[AUDIO COMPOSE] CMD: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FFmpegComposeError(f"FFmpeg executable not found: {exe} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegComposeError("FFmpeg composition timed out.") from exc
    except OSError as exc:
        raise FFmpegComposeError(f"Cannot launch FFmpeg: {exc}") from exc

    stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    print(f"[AUDIO COMPOSE] ffmpeg_returncode={result.returncode}")
    if stderr:
        print(f"[AUDIO COMPOSE] stderr={stderr[-800:]!r}")
    if result.returncode != 0:
        raise FFmpegComposeError(
            f"FFmpeg composition failed (exit {result.returncode}): "
            f"{stderr[-800:] or 'no error output'}"
        )
    _read_wav_header(output_path)
    return output_path


class FFmpegExportError(Exception):
    """Raised when Final MP4 export cannot be completed."""


def _check_real_file(path: Path, label: str) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise FFmpegExportError(f"{label} is missing: {path} ({exc})") from exc
    if not path.is_file():
        raise FFmpegExportError(f"{label} is not a file: {path}")
    if size <= 0:
        raise FFmpegExportError(f"{label} is empty: {path}")


def build_export_command(
    *,
    ffmpeg_path: str,
    video_path: PathLike,
    composed_audio_wav: PathLike,
    output_mp4: PathLike,
    audio_bitrate: str = "192k",
) -> list:
    """Validate export inputs and build the FFmpeg mux argv (no execution)."""
    video = Path(video_path)
    audio = Path(composed_audio_wav)
    _check_real_file(video, "Input video")
    _check_real_file(audio, "Composed audio")
    try:
        _read_wav_header(audio)
    except FFmpegComposeError as exc:
        raise FFmpegExportError(str(exc)) from exc
    out = Path(output_mp4)
    if not out.suffix.lower() == ".mp4":
        raise FFmpegExportError(f"Output must be an .mp4 file: {out}")
    return [
        ffmpeg_path,
        "-y",
        "-i", str(video),
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",
        str(out),
    ]


def probe_mp4(mp4_path: PathLike) -> dict:
    """Inspect an MP4 with ffprobe; returns facts or {"error": ...}."""
    path = Path(mp4_path)
    probe = shutil.which("ffprobe")
    if not probe:
        return {"path": str(path), "error": "ffprobe unavailable"}
    try:
        import json as _json

        result = subprocess.run(
            [probe, "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"path": str(path), "error": f"ffprobe failed: {exc}"}
    if result.returncode != 0:
        return {"path": str(path), "error": "ffprobe returned nonzero"}
    try:
        data = _json.loads((result.stdout or b"").decode("utf-8", errors="replace"))
    except ValueError as exc:
        return {"path": str(path), "error": f"ffprobe output unparseable: {exc}"}
    streams = data.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    duration = data.get("format", {}).get("duration")
    try:
        duration_s = round(float(duration), 3) if duration else 0.0
    except (TypeError, ValueError):
        duration_s = 0.0
    return {
        "path": str(path),
        "has_video": bool(video),
        "has_audio": bool(audio),
        "audio_codec": audio[0].get("codec_name", "") if audio else "",
        "duration_s": duration_s,
    }


def export_final_mp4(
    *,
    video_path: PathLike,
    composed_audio_wav: PathLike,
    output_mp4: PathLike,
    audio_bitrate: str = "192k",
    timeout: int = 600,
    request_id: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
) -> Path:
    """Mux original video (stream copy) with composed voice audio (AAC)."""
    exe = ffmpeg_path or shutil.which("ffmpeg")
    if not exe:
        raise FFmpegExportError(
            "FFmpeg was not found. Please make sure FFmpeg is installed "
            "and available in PATH."
        )
    output_path = Path(output_mp4)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FFmpegExportError(f"Cannot create output directory: {exc}") from exc

    cmd = build_export_command(
        ffmpeg_path=exe, video_path=video_path,
        composed_audio_wav=composed_audio_wav, output_mp4=output_path,
        audio_bitrate=audio_bitrate,
    )
    print("[MP4 EXPORT]")
    print(f"request_id={request_id}")
    print(f"input_video={video_path}")
    print(f"input_audio={composed_audio_wav}")
    print(f"output={output_path}")
    print(f"[MP4 EXPORT] CMD: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise FFmpegExportError(f"FFmpeg executable not found: {exe} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise FFmpegExportError("FFmpeg export timed out.") from exc
    except OSError as exc:
        raise FFmpegExportError(f"Cannot launch FFmpeg: {exc}") from exc

    stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    print(f"[MP4 EXPORT] ffmpeg_returncode={result.returncode}")
    if stderr:
        print(f"[MP4 EXPORT] stderr={stderr[-800:]!r}")
    if result.returncode != 0:
        raise FFmpegExportError(
            f"FFmpeg export failed (exit {result.returncode}): "
            f"{stderr[-800:] or 'no error output'}"
        )
    _check_real_file(output_path, "Output MP4")
    print(f"[MP4 EXPORT] output_exists=True output_size={output_path.stat().st_size}")
    return output_path
