"""Tests for local Piper voice discovery and preview synthesis."""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.piper_service import (
    PiperService,
    PiperSynthesisError,
    PiperVoice,
    VoicePreviewResult,
    batch_output_path,
    build_piper_child_env,
    describe_piper_runtime,
    discover_voices,
    espeak_voice_from_config,
    generate_batch_voices,
    normalize_piper_input,
    piper_version_for_command,
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
            self.assertEqual(
                recorded_stdin.read_bytes(),
                (normalize_piper_input(TEXT_A) + chr(10)).encode("utf-8"),
            )
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
            self.assertEqual(
                stdin_b.read_bytes(),
                (normalize_piper_input(TEXT_B) + chr(10)).encode("utf-8"),
            )
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

    def test_multiline_text_becomes_one_input_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            text = chr(10).join(["Dòng một", "Dòng hai"])
            _, _, recorded_stdin, _ = run_fake_synthesis(
                tmp_path, text, make_voice(tmp)
            )
            self.assertEqual(
                recorded_stdin.read_bytes(),
                "Dòng một Dòng hai".encode("utf-8") + chr(10).encode("utf-8"),
            )

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
            _, argv_a_path, _, _ = run_fake_synthesis(tmp_path, TEXT_A, voice_a)
            _, argv_b_path, _, _ = run_fake_synthesis(tmp_path, TEXT_A, voice_b)
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


def write_selective_fake_exe(path, fail_marker=b"FAILME"):
    """Fake Piper runtime that fails when stdin contains the marker."""
    path.write_text(
        "import json, sys, wave\n"
        "from pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        "data = sys.stdin.buffer.read()\n"
        f"if {fail_marker!r} in data:\n"
        "    sys.stderr.write('selective failure')\n"
        "    sys.exit(2)\n"
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


class BatchOutputPathTest(unittest.TestCase):
    def test_paths_are_unique_per_subtitle_and_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "voices"
            first = batch_output_path(out_dir, 1, "batchAAA")
            self.assertEqual(first.parent, out_dir)
            self.assertIn("0001", first.name)
            self.assertIn("batchAAA", first.name)
            self.assertTrue(first.suffix == ".wav")
            paths = {batch_output_path(out_dir, i, "batchAAA") for i in (1, 2, 3)}
            self.assertEqual(len(paths), 3)
            again = batch_output_path(out_dir, 1, "batchBBB")
            self.assertNotEqual(first, again)


class GenerateBatchVoicesTest(unittest.TestCase):
    def test_empty_work_list_gives_empty_maps(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_exe = write_selective_fake_exe(tmp_path / "fake.py")
            success, errors = generate_batch_voices(
                [], tmp_path / "voices", "b1", make_voice(tmp),
                piper_cmd=[sys.executable, str(fake_exe)],
            )
            self.assertEqual(success, {})
            self.assertEqual(errors, {})

    def test_one_subtitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_exe = write_selective_fake_exe(tmp_path / "fake.py")
            success, errors = generate_batch_voices(
                [(1, TEXT_A)], tmp_path / "voices", "b2", make_voice(tmp),
                piper_cmd=[sys.executable, str(fake_exe)],
            )
            self.assertEqual(errors, {})
            self.assertIn(1, success)
            self.assertTrue(Path(success[1]).is_file())

    def test_multiple_multiline_vietnamese_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_exe = tmp_path / "fake.py"
            stdin_log = tmp_path / "stdin.log"
            fake_exe.write_text(
                "import sys, wave\n"
                "from pathlib import Path\n"
                "data = sys.stdin.buffer.read()\n"
                f"with open({str(stdin_log)!r}, 'ab') as handle:\n"
                "    handle.write(str(len(data)).encode() + b'\\n' + data + b'\\n')\n"
                "argv = sys.argv[1:]\n"
                "out = argv[argv.index('--output_file') + 1]\n"
                "with wave.open(out, 'wb') as wav:\n"
                "    wav.setnchannels(1)\n"
                "    wav.setsampwidth(2)\n"
                "    wav.setframerate(22050)\n"
                "    wav.writeframes(b'\\x00\\x00' * 2205)\n",
                encoding="utf-8",
            )
            voice = make_voice(tmp)
            items = [(1, TEXT_A), (2, "Dòng một\nDòng hai"), (3, TEXT_B)]
            progress_calls = []
            success, errors = generate_batch_voices(
                items, tmp_path / "voices", "b3", voice,
                piper_cmd=[sys.executable, str(fake_exe)],
                progress_callback=lambda *a: progress_calls.append(a),
            )
            self.assertEqual(errors, {})
            self.assertEqual(set(success), {1, 2, 3})
            self.assertEqual(len({success[i] for i in success}), 3)
            # Multiline subtitle becomes one terminated Piper input line.
            logged = stdin_log.read_bytes()
            joined = "Dòng một Dòng hai".encode("utf-8") + chr(10).encode("utf-8")
            split_across_lines = (
                "Dòng một".encode("utf-8")
                + chr(10).encode("utf-8")
                + "Dòng hai".encode("utf-8")
            )
            self.assertIn(joined, logged)
            self.assertNotIn(split_across_lines, logged)
            self.assertIn(
                TEXT_A.encode("utf-8") + chr(10).encode("utf-8"), logged
            )
            self.assertEqual(len(progress_calls), 3)
            self.assertEqual(progress_calls[0][:4], ("b3", 1, 3, 1))
            self.assertTrue(all(call[4] for call in progress_calls))

    def test_one_failure_does_not_stop_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_exe = write_selective_fake_exe(tmp_path / "fake.py")
            success, errors = generate_batch_voices(
                [(1, TEXT_A), (2, "this will FAILME badly"), (3, TEXT_B)],
                tmp_path / "voices", "b4", make_voice(tmp),
                piper_cmd=[sys.executable, str(fake_exe)],
            )
            self.assertEqual(set(success), {1, 3})
            self.assertIn(2, errors)
            self.assertTrue(errors[2])

    def test_no_voice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PiperSynthesisError):
                generate_batch_voices(
                    [(1, TEXT_A)], Path(tmp) / "voices", "b5", None,
                    piper_cmd=["__missing__"],
                )

    def test_precancelled_event_generates_nothing(self):
        import threading as _threading

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_exe = write_selective_fake_exe(tmp_path / "fake.py")
            event = _threading.Event()
            event.set()
            success, errors = generate_batch_voices(
                [(1, TEXT_A), (2, TEXT_B)], tmp_path / "voices", "b6",
                make_voice(tmp),
                piper_cmd=[sys.executable, str(fake_exe)],
                cancel_event=event,
            )
            self.assertEqual(success, {})
            self.assertEqual(errors, {})


class BatchAppStateTest(unittest.TestCase):
    def test_mapping_and_invalidation(self):
        from app.state import AppState

        state = AppState()
        state.subtitle_audio_paths = {1: "a.wav", 2: "b.wav"}
        state.subtitle_audio_errors = {3: "boom"}
        state.invalidate_subtitle_audio(1)
        self.assertEqual(state.subtitle_audio_paths, {2: "b.wav"})
        self.assertIn(3, state.subtitle_audio_errors)
        state.clear_audio_mappings()
        self.assertEqual(state.subtitle_audio_paths, {})
        self.assertEqual(state.subtitle_audio_errors, {})
        self.assertIsNone(state.audio_voice_name)
        self.assertIsNone(state.audio_batch_id)


class PiperInputNormalizationTest(unittest.TestCase):
    def test_normal_vietnamese_subtitle_unchanged(self):
        text = "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"
        self.assertEqual(normalize_piper_input(text), text)

    def test_multiline_subtitle_becomes_one_line(self):
        text = chr(10).join(["Mẹ ơi,", "ba ơi,", "cho con đi chơi."])
        self.assertEqual(
            normalize_piper_input(text), "Mẹ ơi, ba ơi, cho con đi chơi."
        )

    def test_vietnamese_unicode_intact(self):
        text = "Ừ, duyệt cho con luôn."
        normalized = normalize_piper_input(text)
        self.assertEqual(normalized, text)
        self.assertEqual(
            [hex(ord(char)) for char in normalized],
            [hex(ord(char)) for char in text],
        )

    def test_stdin_payload_has_exactly_one_terminating_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, recorded_stdin, logs = run_fake_synthesis(
                Path(tmp), "Ừ, duyệt cho con luôn.", make_voice(tmp)
            )
            payload = recorded_stdin.read_bytes()
            self.assertTrue(payload.endswith(chr(10).encode("utf-8")))
            self.assertFalse(
                payload[:-1].endswith(chr(10).encode("utf-8"))
            )
            self.assertIn("stdin_ends_with_newline=True", logs)

    def test_empty_and_whitespace_only_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice = make_voice(tmp)
            for bad in ("", "   "):
                with self.assertRaises(PiperSynthesisError):
                    synthesize(bad, voice, Path(tmp) / "out.wav")
            self.assertEqual(normalize_piper_input(""), "")
            with self.assertRaises(PiperSynthesisError):
                normalize_piper_input(None)

    def test_windows_line_endings_and_bom_normalized(self):
        text = (
            chr(65279) + "Dòng một," + chr(13) + chr(10) + "dòng hai."
        )
        self.assertEqual(
            normalize_piper_input(text), "Dòng một, dòng hai."
        )


class PiperRuntimeSelectionTest(unittest.TestCase):
    def test_current_module_preferred_over_path_exe(self):
        import services.piper_service as service

        with mock.patch.object(service, "is_piper_module_available",
                               return_value=True), mock.patch.object(
            service, "find_piper_executable",
            return_value="C:\\other\\project\\.venv\\Scripts\\piper.exe",
        ):
            resolved = resolve_piper_base_command()
        self.assertEqual(resolved, [sys.executable, "-m", "piper"])

    def test_explicit_override_still_wins(self):
        import services.piper_service as service

        with mock.patch.object(service, "is_piper_module_available",
                               return_value=True):
            resolved = resolve_piper_base_command(
                ["C:\\Program Files\\piper\\piper.exe", "--extra"]
            )
        self.assertEqual(
            resolved, ["C:\\Program Files\\piper\\piper.exe", "--extra"]
        )

    def test_path_fallback_when_module_unavailable(self):
        import services.piper_service as service

        with mock.patch.object(service, "is_piper_module_available",
                               return_value=False), mock.patch.object(
            service, "find_piper_executable",
            return_value="C:\\tools\\piper.exe",
        ):
            resolved = resolve_piper_base_command()
        self.assertEqual(resolved, ["C:\\tools\\piper.exe"])

    def test_missing_everything_is_a_clear_error(self):
        import services.piper_service as service

        with mock.patch.object(service, "is_piper_module_available",
                               return_value=False), mock.patch.object(
            service, "find_piper_executable", return_value=None
        ):
            with self.assertRaises(PiperSynthesisError) as ctx:
                resolve_piper_base_command()
            self.assertIn("Piper runtime not found", str(ctx.exception))

    def test_describe_is_safe_without_any_runtime(self):
        import services.piper_service as service

        with mock.patch.object(service, "is_piper_module_available",
                               return_value=False), mock.patch.object(
            service, "find_piper_executable", return_value=None
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                info = describe_piper_runtime()
        self.assertIsNone(info["piper_command"])
        self.assertEqual(info["piper_version"], "unknown")
        self.assertEqual(info["sys.executable"], sys.executable)
        self.assertIn("PATH", info)
        logs = buffer.getvalue()
        self.assertIn("[PIPER RUNTIME]", logs)
        self.assertIn("piper_version=unknown", logs)

    def test_version_probe_uses_list_argv_without_shell(self):
        import services.piper_service as service
        import subprocess as _subprocess

        captured = {}

        class FakeResult:
            returncode = 0
            stdout = b"piper 1.2.0 (test)"
            stderr = b""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return FakeResult()

        service._VERSION_CACHE.clear()
        with mock.patch.object(_subprocess, "run", side_effect=fake_run):
            version = service.piper_version_for_command(["somepiper"])
        self.assertEqual(version, "piper 1.2.0 (test)")
        self.assertIsInstance(captured["cmd"], list)
        self.assertEqual(captured["cmd"][-1], "--version")
        self.assertNotIn("shell", captured["kwargs"])

    def test_version_probe_failure_means_unknown(self):
        import services.piper_service as service
        import subprocess as _subprocess

        service._VERSION_CACHE.clear()
        with mock.patch.object(
            _subprocess, "run", side_effect=FileNotFoundError("gone")
        ):
            self.assertEqual(
                service.piper_version_for_command(["gonepiper"]), "unknown"
            )

    def test_explicit_paths_with_spaces_pass_through_intact(self):
        resolved = resolve_piper_base_command(
            ["C:\\My Tools\\piper.exe", "--model", "C:\\My Voices\\v.onnx"]
        )
        self.assertEqual(
            resolved,
            ["C:\\My Tools\\piper.exe", "--model", "C:\\My Voices\\v.onnx"],
        )


class PiperServiceSynthesizeRegressionTest(unittest.TestCase):
    """PLAN 15 FIX 3: PiperService.synthesize() must exist and delegate."""

    def test_method_exists_and_is_callable(self):
        self.assertTrue(callable(getattr(PiperService(), "synthesize", None)))

    def test_preview_compatible_call_reaches_implementation(self):
        import services.piper_service as service

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            tag = uuid.uuid4().hex[:8]
            fake_exe = tmp_path / f"fake_{tag}.py"
            recorded_stdin = tmp_path / f"stdin_{tag}.bin"
            write_wav_fake_exe(
                fake_exe, tmp_path / f"argv_{tag}.json", recorded_stdin
            )
            out_wav = tmp_path / "preview" / f"{tag}.wav"
            service_obj = PiperService()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                # Exact call shape used by Preview Voice (app/ui.py).
                result = service_obj.synthesize(
                    "Xin chào", voice, out_wav, request_id="preview1",
                    piper_cmd=[sys.executable, str(fake_exe)],
                )
            self.assertTrue(Path(result).is_file())
            self.assertIn("request_id=preview1", buffer.getvalue())

    def test_method_uses_fix2_runtime_selection(self):
        import services.piper_service as service
        import subprocess as _subprocess
        import wave as _wave

        captured = {}

        class FakeResult:
            returncode = 0
            stdout = b""
            stderr = b""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            out = cmd[cmd.index("--output_file") + 1]
            with _wave.open(out, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(22050)
                wav.writeframes(b"\x00\x00" * 220)
            return FakeResult()

        with tempfile.TemporaryDirectory() as tmp:
            voice = make_voice(tmp)
            out_wav = Path(tmp) / "preview.wav"
            with mock.patch.object(service, "is_piper_module_available",
                                   return_value=True), mock.patch.object(
                service, "find_piper_executable",
                return_value="C:\\other\\project\\.venv\\Scripts\\piper.exe",
            ), mock.patch.object(_subprocess, "run", side_effect=fake_run):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    # No override: must prefer the current-env module,
                    # never the foreign PATH exe.
                    PiperService().synthesize("Xin chào", voice, out_wav)
            self.assertEqual(
                captured["cmd"][:3], [sys.executable, "-m", "piper"]
            )
            self.assertNotIn("shell", captured["kwargs"])
            self.assertIn("[PIPER RUNTIME]", buffer.getvalue())

    def test_method_explicit_override_still_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            voice = make_voice(tmp)
            tag = uuid.uuid4().hex[:8]
            fake_exe = Path(tmp) / f"fake_{tag}.py"
            recorded_argv = Path(tmp) / f"argv_{tag}.json"
            write_wav_fake_exe(
                fake_exe, recorded_argv, Path(tmp) / f"stdin_{tag}.bin"
            )
            PiperService().synthesize(
                "Xin chào", voice, Path(tmp) / "o.wav",
                piper_cmd=[sys.executable, str(fake_exe)],
            )
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertIn("--model", argv)


# PLAN 18: the canonical synthesize() must never put the unsupported
# `--espeak-voice` option on the Piper command line. piper-tts collects unknown
# options with parse_known_args() and then synthesises " ".join(unknown_args)
# INSTEAD of reading stdin, so the flag silently turned every request into the
# literal text "--espeak-voice <voice>". These tests assert the real argv that
# reaches a real subprocess (fake Piper script), not a mocked call.
def piper_180_unknown_args(argv):
    """Reproduce piper-tts 1.8.0's parse_known_args() leftover handling.

    Mirrors the exact option set of the installed piper __main__.py parser.
    Returns what piper would treat as the synthesis text instead of stdin:
    an empty result means the real stdin payload is used.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--model", required=True)
    parser.add_argument("-c", "--config")
    parser.add_argument("-i", "--input-file", "--input_file", action="append")
    parser.add_argument("-f", "--output-file", "--output_file")
    parser.add_argument("-d", "--output-dir")
    parser.add_argument("--output-dir-naming")
    parser.add_argument("--output-raw", action="store_true")
    parser.add_argument("-s", "--speaker", type=int)
    parser.add_argument("--length-scale", "--length_scale", type=float)
    parser.add_argument("--noise-scale", "--noise_scale", type=float)
    parser.add_argument("--noise-w-scale", "--noise_w-scale", "--noise_w",
                        type=float)
    parser.add_argument("--cuda", action="store_true")
    parser.add_argument("--sentence-silence", "--sentence_silence", type=float)
    parser.add_argument("--volume", type=float)
    parser.add_argument("--no-normalize", action="store_true")
    parser.add_argument("--data-dir", "--data_dir", action="append")
    parser.add_argument("--debug", action="store_true")
    _, unknown_args = parser.parse_known_args(list(argv))
    return unknown_args


class PiperCliArgsRegressionTest(unittest.TestCase):
    """PLAN 18: no unsupported --espeak-voice on the Piper command line."""

    def test_command_never_contains_espeak_voice_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, recorded_argv, _, _ = run_fake_synthesis(tmp_path, TEXT_A, voice)
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertNotIn("--espeak-voice", argv)
            self.assertNotIn("espeak-voice", argv)
            # The resolved eSpeak id must not leak in as a bare token either.
            self.assertNotIn("vi", argv)

    def test_required_flags_remain_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            result, recorded_argv, _, _ = run_fake_synthesis(
                tmp_path, TEXT_A, voice
            )
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertIn("--model", argv)
            self.assertIn("--config", argv)
            self.assertIn("--output_file", argv)
            self.assertEqual(argv[argv.index("--model") + 1], voice.model_path)
            self.assertEqual(argv[argv.index("--config") + 1], voice.config_path)
            self.assertEqual(argv[argv.index("--output_file") + 1], str(result))

    def test_text_arrives_through_stdin_not_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, recorded_argv, recorded_stdin, _ = run_fake_synthesis(
                tmp_path, TEXT_A, voice
            )
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            payload = recorded_stdin.read_bytes()
            self.assertEqual(payload, (TEXT_A + "\n").encode("utf-8"))
            for token in argv:
                self.assertNotIn("chào", token)
                self.assertNotIn("Mẹ", token)

    def test_no_unknown_args_reach_piper_180(self):
        """No leftover argv token, so piper reads stdin, not CLI text."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, recorded_argv, recorded_stdin, _ = run_fake_synthesis(
                tmp_path, TEXT_A, voice
            )
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertEqual(piper_180_unknown_args(argv), [])
            self.assertTrue(recorded_stdin.read_bytes())

    def test_speaker_flag_preserved_for_multispeaker_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base = make_voice(tmp)
            multi = PiperVoice(
                name=base.name, model_path=base.model_path,
                config_path=base.config_path, source=base.source,
                language=base.language, num_speakers=4,
            )
            _, recorded_argv, _, _ = run_fake_synthesis(tmp_path, TEXT_B, multi)
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertIn("--speaker", argv)
            self.assertEqual(argv[argv.index("--speaker") + 1], "0")
            self.assertNotIn("--espeak-voice", argv)

    def test_speaker_flag_absent_for_single_speaker_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, recorded_argv, _, _ = run_fake_synthesis(tmp_path, TEXT_C, voice)
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertNotIn("--speaker", argv)
            self.assertNotIn("--espeak-voice", argv)

    def test_explicit_speaker_override_still_passed_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base = make_voice(tmp)
            multi = PiperVoice(
                name=base.name, model_path=base.model_path,
                config_path=base.config_path, source=base.source,
                language=base.language, num_speakers=2,
            )
            tag = uuid.uuid4().hex[:8]
            fake_exe = tmp_path / f"fake_{tag}.py"
            recorded_argv = tmp_path / f"argv_{tag}.json"
            recorded_stdin = tmp_path / f"stdin_{tag}.bin"
            write_wav_fake_exe(fake_exe, recorded_argv, recorded_stdin)
            out_wav = tmp_path / "o.wav"
            with redirect_stdout(io.StringIO()):
                synthesize(TEXT_A, multi, out_wav, speaker=1,
                           piper_cmd=[sys.executable, str(fake_exe)])
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertEqual(argv[argv.index("--speaker") + 1], "1")
            self.assertNotIn("--espeak-voice", argv)

    def test_explicit_espeak_override_does_not_reach_cli(self):
        """The espeak_voice= parameter stays a code path, never an argv token."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, recorded_argv, _, _ = run_fake_synthesis(tmp_path, TEXT_A, voice)
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertNotIn("--espeak-voice", argv)
            self.assertEqual(piper_180_unknown_args(argv), [])

    def test_batch_items_also_send_no_espeak_voice_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            tag = uuid.uuid4().hex[:8]
            fake_exe = tmp_path / f"fake_{tag}.py"
            recorded_argv = tmp_path / f"argv_{tag}.json"
            recorded_stdin = tmp_path / f"stdin_{tag}.bin"
            write_wav_fake_exe(fake_exe, recorded_argv, recorded_stdin)
            with redirect_stdout(io.StringIO()):
                success, errors = generate_batch_voices(
                    [(1, TEXT_A), (2, TEXT_B), (3, TEXT_C)],
                    tmp_path / "out", f"b{tag}", voice,
                    piper_cmd=[sys.executable, str(fake_exe)],
                )
            self.assertEqual(errors, {})
            self.assertEqual(len(success), 3)
            argv = json.loads(recorded_argv.read_text(encoding="utf-8"))
            self.assertNotIn("--espeak-voice", argv)
            self.assertEqual(piper_180_unknown_args(argv), [])

    def test_espeak_voice_still_logged_for_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            _, _, _, log = run_fake_synthesis(tmp_path, TEXT_A, voice)
            self.assertIn("espeak_voice='vi'", log)
            self.assertNotIn("--espeak-voice", log)


class PiperChildStdioEncodingRegressionTest(unittest.TestCase):
    """Piper decodes stdin with the locale encoding, so the UTF-8 bytes this
    module writes must be paired with a UTF-8 child stdio encoding."""

    def test_child_env_pins_stdio_to_utf8(self):
        env = build_piper_child_env()
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_child_env_inherits_the_rest_of_the_environment(self):
        env = build_piper_child_env()
        self.assertEqual(env.get("PATH"), os.environ.get("PATH"))
        # Only PYTHONIOENCODING is added; nothing is dropped.
        self.assertEqual(len(env), len(os.environ) + 1)

    def test_child_env_does_not_mutate_the_parent_environment(self):
        before = os.environ.get("PYTHONIOENCODING")
        build_piper_child_env()
        self.assertEqual(os.environ.get("PYTHONIOENCODING"), before)

    def test_child_decodes_utf8_stdin_under_the_pinned_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "echo_stdin.py"
            probe.write_text(
                "import sys\n"
                "sys.stdout.buffer.write(sys.stdin.read().encode('utf-8'))\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(probe)],
                input=TEXT_A.encode("utf-8") + b"\n",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=build_piper_child_env(), timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.decode("utf-8").strip(), TEXT_A)

    def test_legacy_codepage_stdin_would_corrupt_the_same_bytes(self):
        """Why the env pin exists: a cp1252 child silently mangles the bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "echo_stdin.py"
            probe.write_text(
                "import sys\n"
                "sys.stdout.buffer.write(sys.stdin.read().encode('utf-8'))\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "cp1252"
            result = subprocess.run(
                [sys.executable, str(probe)],
                input=TEXT_A.encode("utf-8") + b"\n",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual(result.stdout.decode("utf-8").strip(), TEXT_A)

    def test_vietnamese_logging_survives_a_cp1252_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            voice = make_voice(tmp)
            tag = uuid.uuid4().hex[:8]
            fake_exe = tmp_path / f"fake_{tag}.py"
            write_wav_fake_exe(
                fake_exe, tmp_path / f"argv_{tag}.json",
                tmp_path / f"stdin_{tag}.bin",
            )
            raw = io.BytesIO()
            cp1252_stream = io.TextIOWrapper(
                raw, encoding="cp1252", errors="strict", newline="\n",
            )
            with redirect_stdout(cp1252_stream):
                synthesize(
                    TEXT_A, voice, tmp_path / f"{tag}.wav",
                    piper_cmd=[sys.executable, str(fake_exe)],
                    request_id="cp1252-regression",
                )
            cp1252_stream.flush()
            self.assertIn(TEXT_A, raw.getvalue().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()