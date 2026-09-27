"""Tests for per-subtitle Piper voice assignment (PLAN 16, no GUI/Tk).

UI capture paths (Treeview/Combobox/pollers) need a display and are covered
by the manual checklist in plan16result.txt; everything below exercises the
model, service, and state contracts those paths rely on.
"""

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.subtitle import Subtitle
from services.piper_service import (
    PiperSynthesisError,
    PiperVoice,
    generate_batch_voices,
    resolve_voice_by_name,
)


def make_voice(tmp, stem, espeak="vi"):
    voice_dir = Path(tmp) / "piper"
    voice_dir.mkdir(parents=True, exist_ok=True)
    model_path = voice_dir / f"{stem}.onnx"
    config_path = voice_dir / f"{stem}.onnx.json"
    model_path.write_bytes(b"fake-piper-model")
    config_path.write_text(json.dumps({"espeak": {"voice": espeak}}),
                           encoding="utf-8")
    return PiperVoice(name=stem, model_path=str(model_path),
                      config_path=str(config_path), source="piper")


def write_model_logging_fake_exe(path, model_log):
    """Fake Piper runtime: logs the --model per call, writes a valid WAV."""
    path.write_text(
        "import sys, wave\n"
        "from pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        "sys.stdin.buffer.read()\n"
        "model = argv[argv.index('--model') + 1]\n"
        f"with open({str(model_log)!r}, 'a', encoding='utf-8') as handle:\n"
        "    handle.write(model + '\\n')\n"
        "out = argv[argv.index('--output_file') + 1]\n"
        "with wave.open(out, 'wb') as wav:\n"
        "    wav.setnchannels(1)\n"
        "    wav.setsampwidth(2)\n"
        "    wav.setframerate(22050)\n"
        "    wav.writeframes(b'\\x00\\x00' * 2205)\n",
        encoding="utf-8",
    )
    return path


class SubtitleVoiceModelTest(unittest.TestCase):
    def test_subtitle_stores_individual_voice(self):
        sub = Subtitle(index=1, start_ms=0, end_ms=1000,
                       text="Hello", voice="banmai")
        self.assertEqual(sub.voice, "banmai")

    def test_two_subtitles_use_different_voices(self):
        subs = [Subtitle(index=1, start_ms=0, end_ms=1000, text="A", voice="banmai"),
                Subtitle(index=2, start_ms=2000, end_ms=3000, text="B",
                         voice="ngochuyen")]
        self.assertNotEqual(subs[0].voice, subs[1].voice)

    def test_three_subtitles_three_voices(self):
        voices = ["banmai", "ngochuyen", "cuc"]
        subs = [Subtitle(index=i + 1, start_ms=i * 2000, end_ms=i * 2000 + 1000,
                         text=f"T{i}", voice=name)
                for i, name in enumerate(voices)]
        self.assertEqual([s.voice for s in subs], voices)

    def test_voice_change_touches_only_that_subtitle(self):
        subs = [Subtitle(index=1, start_ms=0, end_ms=1000, text="A", voice="banmai"),
                Subtitle(index=2, start_ms=2000, end_ms=3000, text="B",
                         voice="banmai")]
        subs[1].voice = "ngochuyen"
        self.assertEqual(subs[0].voice, "banmai")
        self.assertEqual(subs[1].voice, "ngochuyen")

    def test_unicode_and_multiline_text_unchanged_by_voice(self):
        sub = Subtitle(index=1, start_ms=0, end_ms=1000,
                       text="Mẹ ơi\nBa ơi", voice="cuc")
        self.assertEqual(sub.text, "Mẹ ơi\nBa ơi")
        self.assertEqual(sub.voice, "cuc")


class ResolveVoiceTest(unittest.TestCase):
    def test_resolves_each_discovered_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            voices = [make_voice(tmp, "banmai"), make_voice(tmp, "ngochuyen")]
            self.assertEqual(resolve_voice_by_name(voices, "banmai").name, "banmai")
            self.assertEqual(
                resolve_voice_by_name(voices, "ngochuyen").name, "ngochuyen")

    def test_blank_and_unknown_return_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            voices = [make_voice(tmp, "banmai")]
            self.assertIsNone(resolve_voice_by_name(voices, ""))
            self.assertIsNone(resolve_voice_by_name(voices, "  "))
            self.assertIsNone(resolve_voice_by_name(voices, "ghost"))
            self.assertIsNone(resolve_voice_by_name([], "banmai"))

    def test_whitespace_is_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            voices = [make_voice(tmp, "cuc")]
            self.assertEqual(resolve_voice_by_name(voices, "  cuc ").name, "cuc")


class BatchPerVoiceTest(unittest.TestCase):
    def test_batch_uses_different_voices_per_subtitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banmai = make_voice(tmp, "banmai")
            ngochuyen = make_voice(tmp, "ngochuyen")
            cuc = make_voice(tmp, "cuc")
            by_name = {v.name: v for v in (banmai, ngochuyen, cuc)}
            fake_exe = write_model_logging_fake_exe(
                tmp_path / "fake.py", tmp_path / "models.log")
            items = [(1, "Mẹ ơi", "banmai"),
                     (2, "Ba ơi", "ngochuyen"),
                     (3, "Con chào", "cuc")]
            success, errors = generate_batch_voices(
                items, tmp_path / "voices", "batch1", banmai,
                piper_cmd=[sys.executable, str(fake_exe)],
                voices_by_name=by_name,
            )
            self.assertEqual(errors, {})
            self.assertEqual(set(success), {1, 2, 3})
            logged = (tmp_path / "models.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(logged, [banmai.model_path,
                                      ngochuyen.model_path, cuc.model_path])

    def test_unknown_item_voice_fails_only_that_subtitle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banmai = make_voice(tmp, "banmai")
            fake_exe = write_model_logging_fake_exe(
                tmp_path / "fake.py", tmp_path / "models.log")
            success, errors = generate_batch_voices(
                [(1, "ok", "banmai"), (2, "bad voice here", "ghost")],
                tmp_path / "voices", "batch2", banmai,
                piper_cmd=[sys.executable, str(fake_exe)],
                voices_by_name={"banmai": banmai},
            )
            self.assertIn(1, success)
            self.assertIn(2, errors)
            self.assertIn("ghost", errors[2])

    def test_empty_item_voice_falls_back_to_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banmai = make_voice(tmp, "banmai")
            fake_exe = write_model_logging_fake_exe(
                tmp_path / "fake.py", tmp_path / "models.log")
            success, errors = generate_batch_voices(
                [(1, "fallback please", "")],
                tmp_path / "voices", "batch3", banmai,
                piper_cmd=[sys.executable, str(fake_exe)],
                voices_by_name={"banmai": banmai},
            )
            self.assertEqual(errors, {})
            self.assertIn(1, success)
            logged = (tmp_path / "models.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(logged, [banmai.model_path])

    def test_changing_map_after_capture_cannot_alter_items(self):
        # The worker receives plain (index, text, name) tuples: later UI
        # edits to subtitle objects cannot rewrite captured work items.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            banmai = make_voice(tmp, "banmai")
            ngochuyen = make_voice(tmp, "ngochuyen")
            by_name = {"banmai": banmai, "ngochuyen": ngochuyen}
            fake_exe = write_model_logging_fake_exe(
                tmp_path / "fake.py", tmp_path / "models.log")
            sub = Subtitle(index=1, start_ms=0, end_ms=1000,
                           text="Xin chào", voice="banmai")
            captured = [(sub.index, sub.text, sub.voice)]
            sub.voice = "ngochuyen"  # UI change AFTER capture
            success, errors = generate_batch_voices(
                captured, tmp_path / "voices", "batch4", banmai,
                piper_cmd=[sys.executable, str(fake_exe)],
                voices_by_name=by_name,
            )
            self.assertEqual(errors, {})
            logged = (tmp_path / "models.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(logged, [banmai.model_path])

    def test_missing_voice_still_rejected_without_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PiperSynthesisError):
                generate_batch_voices(
                    [(1, "hi")], Path(tmp) / "voices", "batch5", None,
                    piper_cmd=["__missing__"],
                )


class VoiceInvalidationTest(unittest.TestCase):
    def test_voice_change_invalidates_only_that_subtitle(self):
        from app.state import AppState

        state = AppState()
        state.subtitle_audio_paths = {1: "a.wav", 2: "b.wav"}
        state.subtitle_audio_errors = {}
        state.invalidate_subtitle_audio(2)
        self.assertEqual(state.subtitle_audio_paths, {1: "a.wav"})

    def test_voice_change_invalidates_composed_audio(self):
        from app.state import AppState

        state = AppState()
        state.subtitle_audio_paths = {1: "a.wav"}
        state.composed_audio_path = "temp/composed/audio.wav"
        state.invalidate_subtitle_audio(1)
        self.assertIsNone(state.composed_audio_path)

    def test_voice_change_invalidates_final_mp4(self):
        from app.state import AppState

        state = AppState()
        state.composed_audio_path = "temp/composed/audio.wav"
        state.final_mp4_path = "output/final.wav"
        state.invalidate_subtitle_audio(1)
        self.assertIsNone(state.composed_audio_path)
        self.assertIsNone(state.final_mp4_path)


class ProjectVoiceRoundTripTest(unittest.TestCase):
    def test_save_load_preserves_different_voices(self):
        from services.project_service import (
            FORMAT_ID,
            SUPPORTED_VERSION,
            load_project,
            save_project,
        )

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, {
                "format": FORMAT_ID, "version": SUPPORTED_VERSION,
                "video": {}, "subtitles": [
                    {"index": 1, "start_ms": 0, "end_ms": 1000,
                     "text": "Mẹ ơi", "voice": "banmai"},
                    {"index": 2, "start_ms": 2000, "end_ms": 3000,
                     "text": "Ba ơi\nLine 2", "voice": "ngochuyen"},
                ],
                "audio": {"subtitle_audio_paths": {}},
            })
            loaded = load_project(target)
            by_index = {s["index"]: s for s in loaded["subtitles"]}
            self.assertEqual(by_index[1]["voice"], "banmai")
            self.assertEqual(by_index[2]["voice"], "ngochuyen")
            self.assertEqual(by_index[2]["text"], "Ba ơi\nLine 2")

    def test_unavailable_saved_voice_is_preserved_verbatim(self):
        from services.project_service import (
            FORMAT_ID,
            SUPPORTED_VERSION,
            load_project,
            save_project,
        )

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, {
                "format": FORMAT_ID, "version": SUPPORTED_VERSION,
                "video": {}, "subtitles": [
                    {"index": 1, "start_ms": 0, "end_ms": 1000,
                     "text": "Hi", "voice": "ghost-voice"},
                ],
                "audio": {"subtitle_audio_paths": {}},
            })
            loaded = load_project(target)
            # Service preserves it; UI must warn, never substitute.
            self.assertEqual(loaded["subtitles"][0]["voice"], "ghost-voice")
            with tempfile.TemporaryDirectory() as tmp2:
                voices = [make_voice(tmp2, "banmai")]
                self.assertIsNone(resolve_voice_by_name(voices, "ghost-voice"))


if __name__ == "__main__":
    unittest.main()
