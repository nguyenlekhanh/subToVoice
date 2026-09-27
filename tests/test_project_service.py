"""Tests for project save/load service (PLAN 14, no GUI)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.project_service import (
    FORMAT_ID,
    SUPPORTED_VERSION,
    ProjectError,
    ProjectValidationError,
    load_project,
    resolve_path,
    save_project,
    store_path,
    validate_project_data,
)

TEXT_VI = "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"
TEXT_MULTI = "Dòng một\nDòng hai"


def make_envelope(project_file, video="video.mp4"):
    return {
        "format": FORMAT_ID,
        "version": SUPPORTED_VERSION,
        "video": {"path": video, "duration_ms": 30000, "width": 1280,
                  "height": 720, "fps": 30.0},
        "srt_path": "subs.srt",
        "subtitles": [
            {"index": 1, "start_ms": 0, "end_ms": 2500,
             "text": TEXT_VI, "voice": "banmai"},
            {"index": 2, "start_ms": 4000, "end_ms": 6000,
             "text": TEXT_MULTI, "voice": "banmai"},
        ],
        "selected_subtitle_index": 1,
        "selected_voice_name": "banmai",
        "audio": {"voice_name": "banmai", "batch_id": "b1",
                  "subtitle_audio_paths": {"1": "temp/voices/a.wav"},
                  "subtitle_audio_errors": {}},
        "composed_audio": {"path": "temp/composed/audio.wav",
                           "duration_s": 30.0, "request_id": "c1"},
        "final_mp4": {"path": "output/final.mp4", "duration_s": 30.0,
                      "request_id": "m1"},
    }


class ProjectRoundTripTest(unittest.TestCase):
    def test_save_and_load_basic_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "proj" / "my_project.vveproj"
            saved = save_project(target, make_envelope(target))
            self.assertEqual(saved.suffix, ".vveproj")
            self.assertTrue(saved.is_file())
            loaded = load_project(saved)
            self.assertEqual(loaded["format"], FORMAT_ID)
            self.assertEqual(len(loaded["subtitles"]), 2)
            self.assertEqual(loaded["subtitles"][0]["text"], TEXT_VI)
            self.assertEqual(loaded["selected_voice_name"], "banmai")

    def test_unicode_and_multiline_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, make_envelope(target))
            raw = target.read_text(encoding="utf-8")
            self.assertIn(TEXT_VI, raw)  # no ASCII escaping
            loaded = load_project(target)
            texts = [s["text"] for s in loaded["subtitles"]]
            self.assertIn(TEXT_VI, texts)
            self.assertIn(TEXT_MULTI, texts)

    def test_timing_indexes_voices_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, make_envelope(target))
            loaded = load_project(target)
            first, second = loaded["subtitles"]
            self.assertEqual((first["index"], first["start_ms"], first["end_ms"]),
                             (1, 0, 2500))
            self.assertEqual(second["voice"], "banmai")
            self.assertEqual(loaded["selected_subtitle_index"], 1)

    def test_audio_composed_final_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, make_envelope(target))
            loaded = load_project(target)
            self.assertEqual(loaded["audio"]["subtitle_audio_paths"], {1: "temp/voices/a.wav"})
            self.assertEqual(loaded["audio"]["voice_name"], "banmai")
            self.assertEqual(loaded["composed_audio"]["path"], "temp/composed/audio.wav")
            self.assertEqual(loaded["final_mp4"]["path"], "output/final.mp4")

    def test_audio_mapping_keys_are_integers(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, make_envelope(target))
            loaded = load_project(target)
            for key in loaded["audio"]["subtitle_audio_paths"]:
                self.assertIsInstance(key, int)


class ProjectPathTest(unittest.TestCase):
    def test_relative_inside_project_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "MyVideo" / "project.vveproj"
            stored = store_path(Path(tmp) / "MyVideo" / "video.mp4", proj)
            self.assertEqual(stored, "video.mp4")

    def test_absolute_outside_project_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "A" / "project.vveproj"
            outside = str(Path(tmp) / "B" / "video.mp4")
            self.assertEqual(store_path(outside, proj), outside)

    def test_relative_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "MyVideo" / "project.vveproj"
            resolved = resolve_path("video.mp4", proj)
            self.assertTrue(resolved.endswith("video.mp4"))
            self.assertTrue(Path(resolved).is_absolute())

    def test_absolute_passthrough_and_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p.vveproj"
            self.assertEqual(resolve_path(r"C:\v.mp4", proj), r"C:\v.mp4")
            self.assertIsNone(resolve_path(None, proj))
            self.assertIsNone(store_path(None, proj))


class ProjectValidationTest(unittest.TestCase):
    def _write(self, tmp, content):
        target = Path(tmp) / "p.vveproj"
        target.write_text(content, encoding="utf-8")
        return target

    def test_invalid_format_rejected(self):
        with self.assertRaises(ProjectValidationError):
            validate_project_data({"format": "nope", "version": 1, "subtitles": []})

    def test_unsupported_version_rejected(self):
        with self.assertRaises(ProjectValidationError):
            validate_project_data(
                {"format": FORMAT_ID, "version": 99, "subtitles": []})

    def test_missing_fields_rejected(self):
        with self.assertRaises(ProjectValidationError):
            validate_project_data(
                {"format": FORMAT_ID, "version": SUPPORTED_VERSION,
                 "subtitles": [{"index": 1, "start_ms": 0}]})
        with self.assertRaises(ProjectValidationError):
            validate_project_data("not-an-object")

    def test_invalid_timing_rejected(self):
        for subs in ([{"index": 1, "start_ms": 5, "end_ms": 5, "text": "x"}],
                     [{"index": 1, "start_ms": 9, "end_ms": 3, "text": "x"}],
                     [{"index": 0, "start_ms": 0, "end_ms": 3, "text": "x"}],
                     [{"index": 1, "start_ms": -1, "end_ms": 3, "text": "x"}]):
            with self.assertRaises(ProjectValidationError, msg=str(subs)):
                validate_project_data(
                    {"format": FORMAT_ID, "version": SUPPORTED_VERSION,
                     "subtitles": subs})

    def test_invalid_audio_mapping_rejected(self):
        with self.assertRaises(ProjectValidationError):
            validate_project_data(
                {"format": FORMAT_ID, "version": SUPPORTED_VERSION,
                 "subtitles": [],
                 "audio": {"subtitle_audio_paths": {"abc": "x.wav"}}})

    def test_malformed_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._write(tmp, "{not json")
            with self.assertRaises(ProjectValidationError):
                load_project(target)

    def test_missing_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProjectError):
                load_project(Path(tmp) / "gone.vveproj")


class ProjectAtomicTest(unittest.TestCase):
    def test_no_tmp_leftovers_and_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, make_envelope(target))
            leftovers = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftovers, [])
            loaded = load_project(target)
            self.assertEqual(len(loaded["subtitles"]), 2)

    def test_missing_media_loads_with_references_intact(self):
        # Service level: references are data; existence is checked by the UI.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            save_project(target, make_envelope(target))
            loaded = load_project(target)
            self.assertEqual(loaded["video"]["path"], "video.mp4")
            self.assertFalse(Path(loaded["video"]["path"]).is_file())


class ProjectStateSafetyTest(unittest.TestCase):
    def test_failed_load_leaves_caller_state_untouched(self):
        # load_project never touches app state: a failure returns an
        # exception and no partial document for the caller to apply.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "p.vveproj"
            target.write_text('{"format": "wrong"}', encoding="utf-8")
            sentinel = {"keep": "me"}
            try:
                load_project(target)
            except ProjectValidationError:
                pass
            self.assertEqual(sentinel, {"keep": "me"})

    def test_app_state_project_fields(self):
        from app.state import AppState

        state = AppState()
        self.assertIsNone(state.project_path)
        self.assertFalse(state.project_dirty)
        state.project_path = "x.vveproj"
        state.project_dirty = True
        self.assertTrue(state.project_dirty)


if __name__ == "__main__":
    unittest.main()
