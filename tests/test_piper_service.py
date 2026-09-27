"""Tests for local Piper voice discovery."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.piper_service import PiperVoice, discover_voices


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


if __name__ == "__main__":
    unittest.main()