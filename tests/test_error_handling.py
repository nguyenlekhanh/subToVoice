"""Tests for standardized error handling / no-false-success (PLAN 15).

Service-level only (no GUI, no real Piper/FFmpeg): every failure below must
raise a clear, short exception -- never a silent success, never a traceback
dump to the user path (callers show concise messages; technical detail stays
in logs).
"""

import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import piper_service
from services.ffmpeg_service import (
    FFmpegComposeError,
    FFmpegExportError,
    compose_subtitle_audio,
    export_final_mp4,
)
from services.piper_service import (
    PiperSynthesisError,
    PiperVoice,
    resolve_piper_base_command,
    synthesize,
    wav_info,
)
from services.project_service import (
    ProjectValidationError,
    load_project,
)


def write_wav(path, seconds=0.2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * int(22050 * seconds))
    return path


def write_pair(tmp, stem="v"):
    model = Path(tmp) / f"{stem}.onnx"
    config = Path(tmp) / f"{stem}.onnx.json"
    model.write_bytes(b"fake")
    config.write_text('{"espeak": {"voice": "vi"}}', encoding="utf-8")
    return PiperVoice(name=stem, model_path=str(model),
                      config_path=str(config), source="piper")


def write_failing_exe(path, code=1):
    path.write_text(f"import sys; sys.exit({code})", encoding="utf-8")
    return path


class MissingDependencyTest(unittest.TestCase):
    def test_missing_video_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = write_wav(Path(tmp) / "a.wav")
            with self.assertRaises(FFmpegExportError):
                export_final_mp4(
                    video_path=str(Path(tmp) / "gone.mp4"),
                    composed_audio_wav=str(audio),
                    output_mp4=str(Path(tmp) / "out.mp4"),
                    ffmpeg_path=sys.executable,
                )

    def test_missing_piper_runtime_rejected(self):
        with mock.patch.object(
            piper_service, "find_piper_executable", return_value=None
        ), mock.patch.object(
            piper_service, "is_piper_module_available", return_value=False
        ):
            with self.assertRaises(PiperSynthesisError) as ctx:
                resolve_piper_base_command()
            self.assertIn("Piper runtime not found", str(ctx.exception))

    def test_missing_piper_model_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice = write_pair(tmp)
            bad = PiperVoice(name=voice.name, model_path=str(Path(tmp) / "x.onnx"),
                             config_path=voice.config_path, source="piper")
            with self.assertRaises(PiperSynthesisError):
                synthesize("hi", bad, Path(tmp) / "o.wav",
                           piper_cmd=[sys.executable])

    def test_synthesis_failure_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fail = write_failing_exe(tmp_path / "fail.py", code=2)
            with self.assertRaises(PiperSynthesisError) as ctx:
                synthesize("hi", write_pair(tmp), tmp_path / "o.wav",
                           piper_cmd=[sys.executable, str(fail)])
            self.assertIn("exit 2", str(ctx.exception))

    def test_invalid_wav_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.wav"
            bad.write_bytes(b"not audio")
            with self.assertRaises(PiperSynthesisError):
                wav_info(bad)

    def test_ffmpeg_failure_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice_wav = write_wav(tmp_path / "v1.wav")
            fail = write_failing_exe(tmp_path / "fail.py", code=1)
            with self.assertRaises(FFmpegComposeError) as ctx:
                compose_subtitle_audio(
                    video_duration_ms=5000,
                    segments=[{"index": 1, "start_ms": 0, "end_ms": 1000}],
                    audio_mapping={1: str(voice_wav)},
                    output_wav=str(tmp_path / "out.wav"),
                    ffmpeg_path=str(fail),
                )
            self.assertIn("exit 1", str(ctx.exception))

    def test_missing_composed_audio_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "v.mp4"
            video.write_bytes(b"\x00" * 64)
            with self.assertRaises(FFmpegExportError):
                export_final_mp4(
                    video_path=str(video),
                    composed_audio_wav=str(Path(tmp) / "gone.wav"),
                    output_mp4=str(Path(tmp) / "out.mp4"),
                    ffmpeg_path=sys.executable,
                )

    def test_export_failure_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video = tmp_path / "v.mp4"
            video.write_bytes(b"\x00" * 64)
            audio = write_wav(tmp_path / "a.wav")
            fail = write_failing_exe(tmp_path / "fail.py", code=1)
            with self.assertRaises(FFmpegExportError):
                export_final_mp4(
                    video_path=str(video), composed_audio_wav=str(audio),
                    output_mp4=str(tmp_path / "out.mp4"),
                    ffmpeg_path=str(fail),
                )

    def test_malformed_project_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            target.write_text("{oops", encoding="utf-8")
            with self.assertRaises(ProjectValidationError):
                load_project(target)

    def test_missing_project_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception):
                load_project(Path(tmp) / "gone.vveproj")

    def test_unsupported_project_version_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            target.write_text(
                '{"format": "video_voice_editor_project", "version": 99,'
                ' "subtitles": []}',
                encoding="utf-8",
            )
            with self.assertRaises(ProjectValidationError):
                load_project(target)

    def test_no_false_success_without_ffmpeg(self):
        # Without an FFmpeg binary, composition must fail loudly, not succeed.
        with tempfile.TemporaryDirectory() as tmp:
            voice_wav = write_wav(Path(tmp) / "v1.wav")
            with self.assertRaises(FFmpegComposeError):
                compose_subtitle_audio(
                    video_duration_ms=5000,
                    segments=[{"index": 1, "start_ms": 0, "end_ms": 1000}],
                    audio_mapping={1: str(voice_wav)},
                    output_wav=str(Path(tmp) / "out.wav"),
                    ffmpeg_path="__definitely_missing_ffmpeg__",
                )


class CancelSafetyTest(unittest.TestCase):
    def test_cancel_event_double_set_is_safe(self):
        import threading

        event = threading.Event()
        event.set()
        event.set()  # second click must not crash
        self.assertTrue(event.is_set())


if __name__ == "__main__":
    unittest.main()
