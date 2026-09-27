"""Tests for local Piper voice discovery and preview synthesis."""

import io
import json
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.piper_service import (
    PiperSynthesisError,
    PiperVoice,
    VoicePreviewResult,
    discover_voices,
    espeak_voice_from_config,
    resolve_espeak_voice,
    resolve_piper_base_command,
    synthesize,
    wav_info,
)


def write_pair(directory, stem, config):
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / f"{stem}.onnx"
    config_path = directory / f"{stem}.onnx.json"
    model_path.write_bytes(b"fake-piper-model")
    if config is not None:
        if isinstance(config, str):
            config_path.write_text(config, encoding="utf-8")
        else:
            config_path.write_text(json.dumps(config), encoding="utf-8")
    return model_path, config_path


class PiperServiceTest(unittest.TestCase):
    def test_valid_pair_is_discovered_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(
                root / "piper",
                "example",
                {
                    "audio": {"sample_rate": 22050},
                    "espeak": {"voice": "vi"},
                    "language": {"code": "vi_VN"},
                    "dataset": "example-data",
                    "phoneme_type": "espeak",
                    "num_speakers": 1,
                },
            )
            voices = discover_voices(root)
            self.assertEqual(len(voices), 1)
            voice = voices[0]
            self.assertIsInstance(voice, PiperVoice)
            self.assertEqual(voice.name, "example")
            self.assertTrue(voice.model_path.endswith("example.onnx"))
            self.assertTrue(voice.config_path.endswith("example.onnx.json"))
            self.assertEqual(voice.source, "piper")
            self.assertEqual(voice.language, "vi_VN")
            self.assertEqual(voice.dataset, "example-data")
            self.assertEqual(voice.sample_rate, 22050)
            self.assertEqual(voice.phoneme_type, "espeak")
            self.assertEqual(voice.num_speakers, 1)

    def test_missing_config_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voice_dir = root / "piper"
            voice_dir.mkdir(parents=True)
            (voice_dir / "orphan.onnx").write_bytes(b"fake-piper-model")
            self.assertEqual(discover_voices(root), [])

    def test_missing_model_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voice_dir = root / "piper"
            voice_dir.mkdir(parents=True)
            (voice_dir / "orphan.onnx.json").write_text("{}", encoding="utf-8")
            self.assertEqual(discover_voices(root), [])

    def test_malformed_json_does_not_prevent_valid_voices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(root / "piper", "broken", "{not valid json")
            write_pair(root / "piper", "good", {"audio": {"sample_rate": 16000}})
            voices = discover_voices(root)
            self.assertEqual([voice.name for voice in voices], ["good"])

    def test_multiple_voices_are_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(root / "piper", "beta", {})
            write_pair(root / "piper", "alpha", {})
            names = [voice.name for voice in discover_voices(root)]
            self.assertEqual(names, ["alpha", "beta"])

    def test_duplicate_directory_entries_are_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(root / "piper", "same", {})
            voices = discover_voices(root, voice_directories=("piper", "piper"))
            self.assertEqual(len(voices), 1)

    def test_missing_optional_metadata_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(root / "piper", "minimal", {"audio": {"sample_rate": 16000}})
            (voice,) = discover_voices(root)
            self.assertEqual(voice.language, "")
            self.assertEqual(voice.dataset, "")
            self.assertEqual(voice.sample_rate, 16000)
            self.assertIsNone(voice.num_speakers)

    def test_espeak_voice_is_used_when_language_code_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(root / "piper", "legacy", {"espeak": {"voice": "en-us"}})
            (voice,) = discover_voices(root)
            self.assertEqual(voice.language, "en-us")

    def test_both_config_directories_are_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_pair(root / "piper", "vietnamese", {})
            write_pair(root / "piper-en", "english", {})
            discovered = {(voice.source, voice.name) for voice in discover_voices(root)}
            self.assertEqual(
                discovered, {("piper", "vietnamese"), ("piper-en", "english")}
            )


TEXT_A = "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"
TEXT_B = "Xin chào, đây là một câu kiểm tra khác."
TEXT_C = "CCCCC completely different sentence three."


def make_voice(tmp, stem="demo", config=None):
    voice_dir = Path(tmp) / "piper"
    model_path, config_path = write_pair(
        voice_dir, stem, {"espeak": {"voice": "vi"}} if config is None else config
    )
    return PiperVoice(
        name=stem, model_path=str(model_path),
        config_path=str(config_path), source="piper", language="vi",
    )


def write_wav_fake_exe(path, recorded_argv, recorded_stdin):
    """Fake Piper runtime: records argv/stdin, writes a valid 0.1s WAV."""
    path.write_text(
        "import json, sys, wave\n"
        "from pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        f"Path({str(recorded_argv)!r}).write_text(json.dumps(argv), encoding='utf-8')\n"
        "data = sys.stdin.buffer.read()\n"
        f"Path({str(recorded_stdin)!r}).write_bytes(data)\n"
        "out = None\n"
        "for i, a in enumerate(argv):\n"
        "    if a in ('--output_file', '--output-file') and i + 1 < len(argv):\n"
        "        out = argv[i + 1]\n"
        "with wave.open(out, 'wb') as wav:\n"
        "    wav.setnchannels(1)\n"
        "    wav.setsampwidth(2)\n"
        "    wav.setframerate(22050)\n"
        "    wav.writeframes(b'\\x00\\x00' * 2205)\n",
        encoding="utf-8",
    )
    return path


def run_fake_synthesis(tmp_path, text, voice, request_id="req001"):
    tag = uuid.uuid4().hex[:8]
    fake_exe = tmp_path / f"fake_piper_{tag}.py"
    recorded_argv = tmp_path / f"argv_{tag}.json"
    recorded_stdin = tmp_path / f"stdin_{tag}.bin"
    write_wav_fake_exe(fake_exe, recorded_argv, recorded_stdin)
    out_wav = tmp_path / "preview" / f"{tag}.wav"
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = synthesize(
            text, voice, out_wav,
            piper_cmd=[sys.executable, str(fake_exe)],
            request_id=request_id,
        )
    return result, recorded_argv, recorded_stdin, buffer.getvalue()


class PiperSynthesisValidationTest(unittest.TestCase):
    def test_empty_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PiperSynthesisError):
                synthesize("   ", make_voice(tmp), Path(tmp) / "out.wav")

    def test_missing_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice = make_voice(tmp)
            missing = PiperVoice(
                name=voice.name, model_path=str(Path(tmp) / "nope.onnx"),
                config_path=voice.config_path, source="piper",
            )
            with self.assertRaises(PiperSynthesisError):
                synthesize("hello", missing, Path(tmp) / "out.wav")

    def test_missing_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice = make_voice(tmp)
            missing = PiperVoice(
                name=voice.name, model_path=voice.model_path,
                config_path=str(Path(tmp) / "nope.onnx.json"), source="piper",
            )
            with self.assertRaises(PiperSynthesisError):
                synthesize("hello", missing, Path(tmp) / "out.wav")

    def test_invalid_voice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PiperSynthesisError):
                synthesize("hello", "not-a-voice", Path(tmp) / "out.wav")

    def test_missing_runtime_produces_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PiperSynthesisError) as ctx:
                synthesize(
                    "hello", make_voice(tmp), Path(tmp) / "nested" / "out.wav",
                    piper_cmd=["__definitely_missing_piper_exe__"],
                )
            self.assertIn("Piper", str(ctx.exception))

    def test_failed_process_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fail_exe = tmp_path / "fail.py"
            fail_exe.write_text("import sys; sys.exit(3)", encoding="utf-8")
            with self.assertRaises(PiperSynthesisError) as ctx:
                synthesize(
                    "hello", make_voice(tmp), tmp_path / "out.wav",
                    piper_cmd=[sys.executable, str(fail_exe)],
                )
            self.assertIn("exit 3", str(ctx.exception))


class PiperEspeakVoiceTest(unittest.TestCase):
    def test_vietnamese_voice_from_model_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config_path = write_pair(
                Path(tmp) / "piper", "v", {"espeak": {"voice": "vi"}}
            )
            self.assertEqual(espeak_voice_from_config(config_path), "vi")

    def test_english_voice_is_not_forced_to_vietnamese(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, config_path = write_pair(
                Path(tmp) / "piper-en", "e", {"espeak": {"voice": "en-us"}}
            )
            self.assertEqual(espeak_voice_from_config(config_path), "en-us")

    def test_resolve_prefers_model_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice_dir = Path(tmp) / "piper"
            model_path, config_path = write_pair(
                voice_dir, "w", {"espeak": {"voice": "vi"}}
            )
            voice = PiperVoice(
                name="w", model_path=str(model_path),
                config_path=str(config_path), source="piper", language="en-us",
            )
            self.assertEqual(resolve_espeak_voice(voice), "vi")

    def test_empty_base_command_is_rejected(self):
        with self.assertRaises(PiperSynthesisError):
            resolve_piper_base_command([])


class PiperExactTextTest(unittest.TestCase):
    def test_text_a_sent_byte_exact_with_full_repr_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result, _, recorded_stdin, logs = run_fake_synthesis(
                tmp_path, TEXT_A, make_voice(tmp), request_id="reqA"
            )
            self.assertTrue(result.is_file())
            self.assertEqual(recorded_stdin.read_bytes(), TEXT_A.encode("utf-8"))
            self.assertIn(f"text={TEXT_A!r}", logs)
            self.assertIn("request_id=reqA", logs)

    def test_text_b_differs_and_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, _, stdin_a, _ = run_fake_synthesis(tmp_path, TEXT_A, voice)
            _, _, stdin_b, logs_b = run_fake_synthesis(
                tmp_path, TEXT_B, voice, request_id="reqB"
            )
            self.assertEqual(stdin_b.read_bytes(), TEXT_B.encode("utf-8"))
            self.assertNotEqual(stdin_a.read_bytes(), stdin_b.read_bytes())
            self.assertIn(f"text={TEXT_B!r}", logs_b)

    def test_abc_inputs_all_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            payloads = set()
            for num, text in enumerate(
                ("AAAAAAA đây là câu kiểm tra số một.",
                 "BBBBBBB đây là câu kiểm tra số hai.",
                 "CCCCCCC đây là câu kiểm tra số ba."), start=1):
                _, _, recorded_stdin, logs = run_fake_synthesis(
                    tmp_path, text, voice, request_id=f"abc{num}"
                )
                payloads.add(recorded_stdin.read_bytes())
                self.assertIn(f"text={text!r}", logs)
            self.assertEqual(len(payloads), 3)

    def test_multiline_text_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            text = "Dòng một\nDòng hai"
            _, _, recorded_stdin, _ = run_fake_synthesis(
                tmp_path, text, make_voice(tmp)
            )
            self.assertEqual(recorded_stdin.read_bytes(), text.encode("utf-8"))

    def test_different_voices_resolve_different_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice_dir = tmp_path / "piper"
            model_a, config_a = write_pair(
                voice_dir, "voicea", {"espeak": {"voice": "vi"}}
            )
            model_b, config_b = write_pair(
                voice_dir, "voiceb", {"espeak": {"voice": "vi"}}
            )
            voice_a = PiperVoice(
                name="voicea", model_path=str(model_a),
                config_path=str(config_a), source="piper",
            )
            voice_b = PiperVoice(
                name="voiceb", model_path=str(model_b),
                config_path=str(config_b), source="piper",
            )
            _, argv_a_path, _ = run_fake_synthesis(tmp_path, TEXT_A, voice_a)
            _, argv_b_path, _ = run_fake_synthesis(tmp_path, TEXT_A, voice_b)
            argv_a = json.loads(argv_a_path.read_text(encoding="utf-8"))
            argv_b = json.loads(argv_b_path.read_text(encoding="utf-8"))
            self.assertIn(str(model_a), argv_a)
            self.assertNotIn(str(model_b), argv_a)
            self.assertIn(str(model_b), argv_b)
            self.assertNotIn(str(model_a), argv_b)
            self.assertIn(str(config_a), argv_a)
            self.assertIn(str(config_b), argv_b)


class PiperWavInfoTest(unittest.TestCase):
    def _write_wav(self, path):
        import wave as _wave

        with _wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(b"\x00\x00" * 2205)

    def test_valid_wav_header_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "a.wav"
            self._write_wav(wav_path)
            info = wav_info(wav_path)
            self.assertEqual(info["channels"], 1)
            self.assertEqual(info["sample_rate"], 22050)
            self.assertAlmostEqual(info["duration_s"], 0.1, places=2)
            self.assertEqual(len(info["sha256"]), 64)

    def test_tampered_file_changes_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "a.wav"
            self._write_wav(wav_path)
            hash_before = wav_info(wav_path)["sha256"]
            with wav_path.open("r+b") as handle:
                handle.seek(60)
                handle.write(b"\x01\x02")
            self.assertNotEqual(hash_before, wav_info(wav_path)["sha256"])

    def test_non_wav_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.wav"
            bad.write_bytes(b"not-a-wav")
            with self.assertRaises(PiperSynthesisError):
                wav_info(bad)


class VoicePreviewResultTest(unittest.TestCase):
    def test_success_carries_exact_playable_path(self):
        result = VoicePreviewResult(
            request_id="abc123", subtitle_index=2, subtitle_text=TEXT_A,
            voice_name="ngochuyen", output_wav="temp/preview/abc123.wav",
            success=True, wav_size=100, wav_sha256="deadbeef", wav_duration_s=1.0,
        )
        self.assertEqual(result.output_wav, "temp/preview/abc123.wav")
        self.assertEqual(result.subtitle_text, TEXT_A)

    def test_failure_never_points_at_a_wav(self):
        result = VoicePreviewResult(
            request_id="bad001", subtitle_index=1, subtitle_text=TEXT_B,
            voice_name="banmai", output_wav="", success=False, error="boom",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.output_wav, "")
        self.assertEqual(result.error, "boom")


if __name__ == "__main__":
    unittest.main()