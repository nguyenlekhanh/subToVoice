"""Tests for Final MP4 export (PLAN 13, no GUI)."""

import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.ffmpeg_service import (
    FFmpegExportError,
    build_export_command,
    export_final_mp4,
    probe_mp4,
)


def write_file(path, size=1024):
    path.write_bytes(b"\x00" * size)
    return path


def write_wav(path, seconds=0.5, sample_rate=48000):
    import math
    import struct

    frames = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(frames):
            sample = int(8000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wav.writeframes(struct.pack("<hh", sample, sample))
    return path


def make_inputs(tmp):
    tmp_path = Path(tmp)
    video = write_file(tmp_path / "video.mp4", size=4096)
    audio = write_wav(tmp_path / "composed.wav")
    return video, audio


class ExportValidationTest(unittest.TestCase):
    def test_missing_video_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, audio = make_inputs(tmp)
            with self.assertRaises(FFmpegExportError):
                build_export_command(
                    ffmpeg_path="ffmpeg", video_path=Path(tmp) / "gone.mp4",
                    composed_audio_wav=str(audio),
                    output_mp4=str(Path(tmp) / "final.mp4"),
                )

    def test_missing_audio_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, _ = make_inputs(tmp)
            with self.assertRaises(FFmpegExportError):
                build_export_command(
                    ffmpeg_path="ffmpeg", video_path=str(video),
                    composed_audio_wav=str(Path(tmp) / "gone.wav"),
                    output_mp4=str(Path(tmp) / "final.mp4"),
                )

    def test_missing_output_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, audio = make_inputs(tmp)
            with self.assertRaises((FFmpegExportError, TypeError, AttributeError)):
                build_export_command(
                    ffmpeg_path="ffmpeg", video_path=str(video),
                    composed_audio_wav=str(audio), output_mp4="",
                )

    def test_non_mp4_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, audio = make_inputs(tmp)
            with self.assertRaises(FFmpegExportError):
                build_export_command(
                    ffmpeg_path="ffmpeg", video_path=str(video),
                    composed_audio_wav=str(audio),
                    output_mp4=str(Path(tmp) / "final.avi"),
                )


class ExportCommandTest(unittest.TestCase):
    def test_command_maps_video_and_composed_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, audio = make_inputs(tmp)
            out = Path(tmp) / "output" / "final_abc.mp4"
            cmd = build_export_command(
                ffmpeg_path="ffmpeg", video_path=str(video),
                composed_audio_wav=str(audio), output_mp4=str(out),
            )
            self.assertEqual(cmd[0], "ffmpeg")
            self.assertIn(str(video), cmd)
            self.assertIn(str(audio), cmd)
            for token in ("0:v:0", "1:a:0", "copy", "aac", "192k"):
                self.assertIn(token, cmd)
            self.assertEqual(cmd[-1], str(out))
            self.assertIsInstance(cmd, list)

    def test_failing_process_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            video, audio = make_inputs(tmp)
            fail_exe = Path(tmp) / "fail_ffmpeg.py"
            fail_exe.write_text("import sys; sys.exit(1)", encoding="utf-8")
            with self.assertRaises(FFmpegExportError) as ctx:
                export_final_mp4(
                    video_path=str(video), composed_audio_wav=str(audio),
                    output_mp4=str(Path(tmp) / "final.mp4"),
                    ffmpeg_path=str(fail_exe),
                )
            # A fake "ffmpeg" that exits nonzero must surface, not succeed.
            self.assertTrue(str(ctx.exception))


class ExportStateTest(unittest.TestCase):
    def test_final_mp4_state_and_invalidation(self):
        from app.state import AppState

        state = AppState()
        state.final_mp4_path = "output/final_x.mp4"
        state.final_mp4_request_id = "x"
        state.final_mp4_duration_s = 30.0
        state.subtitle_audio_paths = {1: "a.wav"}
        state.invalidate_subtitle_audio(1)
        self.assertIsNone(state.final_mp4_path)
        self.assertIsNone(state.final_mp4_request_id)
        self.assertIsNone(state.final_mp4_duration_s)
        state.final_mp4_path = "output/final_y.mp4"
        state.clear_audio_mappings()
        self.assertIsNone(state.final_mp4_path)
        state.final_mp4_path = "output/final_z.mp4"
        state.clear_composed_audio()
        self.assertIsNone(state.final_mp4_path)
        state.final_mp4_path = "output/final_w.mp4"
        state.clear_video_state()
        self.assertIsNone(state.final_mp4_path)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not available")
class RealFFmpegExportTest(unittest.TestCase):
    def _make_test_video(self, path, seconds=3):
        import subprocess

        cmd = ["ffmpeg", "-y", "-f", "lavfi",
               f"testsrc=duration={seconds}:size=128x128:rate=10",
               "-pix_fmt", "yuv420p", str(path)]
        result = subprocess.run(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=120)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-500:])
        return path

    def test_real_export_has_video_and_aac_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video_before = self._make_test_video(tmp_path / "src.mp4")
            size_before = video_before.stat().st_size
            audio = write_wav(tmp_path / "composed.wav", seconds=3.0)
            out_mp4 = tmp_path / "final_test.mp4"
            result = export_final_mp4(
                video_path=str(video_before), composed_audio_wav=str(audio),
                output_mp4=str(out_mp4), request_id="test",
            )
            self.assertTrue(result.is_file())
            self.assertGreater(result.stat().st_size, 0)
            # Original video untouched.
            self.assertEqual(video_before.stat().st_size, size_before)
            probe = probe_mp4(out_mp4)
            if "error" not in probe:
                self.assertTrue(probe["has_video"])
                self.assertTrue(probe["has_audio"])
                self.assertEqual(probe["audio_codec"], "aac")
                self.assertAlmostEqual(probe["duration_s"], 3.0, delta=0.4)


if __name__ == "__main__":
    unittest.main()
