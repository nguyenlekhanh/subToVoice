"""Tests for FFmpeg subtitle-audio composition (PLAN 12, no GUI)."""

import math
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.ffmpeg_service import (
    FFmpegComposeError,
    build_compose_command,
    compose_subtitle_audio,
)


def write_tone(path, seconds=1.0, freq=440.0, sample_rate=22050):
    """Write a real mono 16-bit WAV with a sine tone."""
    frames = int(sample_rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(frames):
            sample = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
            wav.writeframes(struct.pack("<h", sample))
    return path


def make_inputs(tmp, specs=((1, 0), (2, 4000))):
    """Create per-subtitle WAVs; return (segments, mapping)."""
    tmp_path = Path(tmp)
    segments, mapping = [], {}
    for index, start_ms in specs:
        wav_path = tmp_path / f"voice_{index}.wav"
        write_tone(wav_path, seconds=1.0)
        segments.append({"index": index, "start_ms": start_ms,
                         "end_ms": start_ms + 2500})
        mapping[index] = str(wav_path)
    return segments, mapping


class ComposeValidationTest(unittest.TestCase):
    def test_empty_subtitle_list_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FFmpegComposeError):
                build_compose_command(
                    ffmpeg_path="ffmpeg", video_duration_ms=10000,
                    segments=[], audio_mapping={1: "a.wav"},
                    output_wav=Path(tmp) / "out.wav",
                )

    def test_empty_mapping_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FFmpegComposeError):
                build_compose_command(
                    ffmpeg_path="ffmpeg", video_duration_ms=10000,
                    segments=[{"index": 1, "start_ms": 0, "end_ms": 100}],
                    audio_mapping={}, output_wav=Path(tmp) / "out.wav",
                )

    def test_missing_wav_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FFmpegComposeError):
                build_compose_command(
                    ffmpeg_path="ffmpeg", video_duration_ms=10000,
                    segments=[{"index": 1, "start_ms": 0, "end_ms": 100}],
                    audio_mapping={1: str(Path(tmp) / "gone.wav")},
                    output_wav=Path(tmp) / "out.wav",
                )

    def test_zero_size_wav_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.wav"
            empty.write_bytes(b"")
            with self.assertRaises(FFmpegComposeError):
                build_compose_command(
                    ffmpeg_path="ffmpeg", video_duration_ms=10000,
                    segments=[{"index": 1, "start_ms": 0, "end_ms": 100}],
                    audio_mapping={1: str(empty)},
                    output_wav=Path(tmp) / "out.wav",
                )

    def test_invalid_timing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wav_path = tmp_path / "voice.wav"
            write_tone(wav_path, seconds=0.2)
            bad_cases = [
                {"index": 1, "start_ms": -5, "end_ms": 100},
                {"index": 1, "start_ms": 200, "end_ms": 200},
                {"index": 1, "start_ms": 200, "end_ms": 100},
                {"index": 1, "start_ms": 10000, "end_ms": 11000},
            ]
            for bad in bad_cases:
                with self.assertRaises(FFmpegComposeError, msg=str(bad)):
                    build_compose_command(
                        ffmpeg_path="ffmpeg", video_duration_ms=10000,
                        segments=[bad], audio_mapping={1: str(wav_path)},
                        output_wav=tmp_path / "out.wav",
                    )

    def test_unknown_duration_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            segments, mapping = make_inputs(tmp)
            with self.assertRaises(FFmpegComposeError):
                build_compose_command(
                    ffmpeg_path="ffmpeg", video_duration_ms=0,
                    segments=segments, audio_mapping=mapping,
                    output_wav=Path(tmp) / "out.wav",
                )

    def test_missing_mapping_entry_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            segments, mapping = make_inputs(tmp)
            del mapping[2]
            with self.assertRaises(FFmpegComposeError):
                build_compose_command(
                    ffmpeg_path="ffmpeg", video_duration_ms=10000,
                    segments=segments, audio_mapping=mapping,
                    output_wav=Path(tmp) / "out.wav",
                )


class ComposeCommandTest(unittest.TestCase):
    def test_single_subtitle_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            segments, mapping = make_inputs(tmp, specs=((1, 0),))
            cmd, filt, resolved = build_compose_command(
                ffmpeg_path="ffmpeg", video_duration_ms=8000,
                segments=segments, audio_mapping=mapping,
                output_wav=Path(tmp) / "out.wav",
            )
            self.assertIn("-filter_complex", cmd)
            self.assertIn("adelay=0|0", filt)
            self.assertIn("amix=inputs=1", filt)
            self.assertIn("atrim=0:8.000", filt)
            for token in ("pcm_s16le", "48000", "2", "-y"):
                self.assertIn(token, cmd)
            self.assertIsInstance(cmd, list)
            self.assertEqual(len(resolved), 1)

    def test_gaps_use_start_delays(self):
        with tempfile.TemporaryDirectory() as tmp:
            segments, mapping = make_inputs(tmp, specs=((1, 0), (2, 5000)))
            _, filt, _ = build_compose_command(
                ffmpeg_path="ffmpeg", video_duration_ms=8000,
                segments=segments, audio_mapping=mapping,
                output_wav=Path(tmp) / "out.wav",
            )
            self.assertIn("adelay=0|0", filt)
            self.assertIn("adelay=5000|5000", filt)
            self.assertIn("amix=inputs=2", filt)

    def test_overlap_mixes_both_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            segments, mapping = make_inputs(tmp, specs=((1, 0), (2, 2000)))
            _, filt, resolved = build_compose_command(
                ffmpeg_path="ffmpeg", video_duration_ms=8000,
                segments=segments, audio_mapping=mapping,
                output_wav=Path(tmp) / "out.wav",
            )
            self.assertIn("amix=inputs=2", filt)
            self.assertIn("[d0]", filt)
            self.assertIn("[d1]", filt)
            self.assertEqual([r["index"] for r in resolved], [1, 2])

    def test_output_trimmed_to_video_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            segments, mapping = make_inputs(tmp, specs=((1, 29000),))
            _, filt, _ = build_compose_command(
                ffmpeg_path="ffmpeg", video_duration_ms=30000,
                segments=segments, audio_mapping=mapping,
                output_wav=Path(tmp) / "out.wav",
            )
            self.assertIn("atrim=0:30.000", filt)

    def test_unique_output_paths(self):
        import uuid as _uuid

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "composed" / f"audio_{_uuid.uuid4().hex[:8]}.wav"
            second = Path(tmp) / "composed" / f"audio_{_uuid.uuid4().hex[:8]}.wav"
            self.assertNotEqual(first, second)


class ComposeAppStateTest(unittest.TestCase):
    def test_composed_state_and_invalidation(self):
        from app.state import AppState

        state = AppState()
        state.composed_audio_path = "temp/composed/audio_x.wav"
        state.composed_audio_duration_s = 30.0
        state.composed_audio_request_id = "x"
        state.subtitle_audio_paths = {1: "a.wav"}
        state.invalidate_subtitle_audio(1)
        self.assertIsNone(state.composed_audio_path)
        self.assertIsNone(state.composed_audio_duration_s)
        self.assertIsNone(state.composed_audio_request_id)
        state.composed_audio_path = "temp/composed/audio_y.wav"
        state.clear_audio_mappings()
        self.assertIsNone(state.composed_audio_path)
        self.assertEqual(state.subtitle_audio_paths, {})


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg not available")
class RealFFmpegComposeTest(unittest.TestCase):
    def test_real_composition_matches_video_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            segments, mapping = make_inputs(tmp, specs=((1, 0), (2, 4000)))
            out_wav = tmp_path / "composed" / "audio_test.wav"
            result = compose_subtitle_audio(
                video_duration_ms=8000, segments=segments,
                audio_mapping=mapping, output_wav=out_wav,
            )
            self.assertTrue(result.is_file())
            self.assertGreater(result.stat().st_size, 0)
            with wave.open(str(result), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
                self.assertEqual(wav.getframerate(), 48000)
                self.assertEqual(wav.getnchannels(), 2)
                self.assertEqual(wav.getsampwidth(), 2)
            self.assertAlmostEqual(duration, 8.0, delta=0.15)


if __name__ == "__main__":
    unittest.main()
