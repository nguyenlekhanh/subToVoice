"""Tests for safe temp cleanup (PLAN 15, no GUI)."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.cleanup_service import (
    cleanup_on_close,
    cleanup_orphaned_files,
    cleanup_preview_files,
    cleanup_stale_save_tmp_files,
    safe_unlink,
)


def touch(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class PreviewCleanupTest(unittest.TestCase):
    def test_old_previews_removed_newest_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview"
            old = touch(preview / "aaa.wav")
            new = touch(preview / "zzz.wav")
            summary = cleanup_preview_files(preview)
            self.assertIn(str(old), summary["deleted"])
            self.assertFalse(old.exists())
            self.assertIn(str(new), summary["kept"])
            self.assertTrue(new.exists())

    def test_actively_playing_file_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview"
            old = touch(preview / "aaa.wav")
            playing = touch(preview / "mmm.wav")
            newest = touch(preview / "zzz.wav")
            summary = cleanup_preview_files(preview, keep_paths=[str(playing)])
            self.assertFalse(old.exists())
            self.assertTrue(playing.exists())
            self.assertTrue(newest.exists())
            self.assertIn(str(old), summary["deleted"])

    def test_unknown_files_and_subdirs_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview"
            notes = touch(preview / "notes.txt")
            sub = preview / "sub"
            sub.mkdir()
            inner = touch(sub / "inner.wav")
            summary = cleanup_preview_files(preview)
            self.assertTrue(notes.exists())
            self.assertTrue(inner.exists())
            self.assertEqual(summary["deleted"], [])

    def test_missing_directory_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = cleanup_preview_files(Path(tmp) / "nope")
            self.assertEqual(summary, {"deleted": [], "kept": [], "errors": []})

    def test_close_sweep_deletes_previews(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview"
            one = touch(preview / "a.wav")
            summary = cleanup_on_close(preview)
            self.assertFalse(one.exists())
            self.assertIn(str(one), summary["deleted"])

    def test_outside_files_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview"
            preview.mkdir()
            outside = touch(Path(tmp) / "elsewhere.wav")
            cleanup_preview_files(preview)
            cleanup_on_close(preview)
            self.assertTrue(outside.exists())


class OrphanCleanupTest(unittest.TestCase):
    def test_old_batch_removed_referenced_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            voices = Path(tmp) / "voices"
            old = touch(voices / "subtitle_0001_oldbatch.wav")
            current = touch(voices / "subtitle_0001_newbatch.wav")
            summary = cleanup_orphaned_files(
                voices, "subtitle_", referenced_paths=[str(current)]
            )
            self.assertFalse(old.exists())
            self.assertTrue(current.exists())
            self.assertIn(str(old), summary["deleted"])

    def test_composed_orphan_removed_unknown_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            composed = Path(tmp) / "composed"
            orphan = touch(composed / "audio_old.wav")
            keep = touch(composed / "audio_new.wav")
            other = touch(composed / "readme.txt")
            summary = cleanup_orphaned_files(
                composed, "audio_", referenced_paths=[str(keep)]
            )
            self.assertFalse(orphan.exists())
            self.assertTrue(keep.exists())
            self.assertTrue(other.exists())
            self.assertIn(str(other), summary["kept"])


class SaveTmpCleanupTest(unittest.TestCase):
    def test_only_save_tmp_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            stale = touch(base / "project.vveproj.tmp")
            real = touch(base / "project.vveproj", b"{}")
            other = touch(base / "notes.tmp")
            summary = cleanup_stale_save_tmp_files(base)
            self.assertFalse(stale.exists())
            self.assertTrue(real.exists())
            self.assertTrue(other.exists())
            self.assertIn(str(stale), summary["deleted"])


class CleanupSafetyTest(unittest.TestCase):
    def test_safe_unlink_missing_is_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(safe_unlink(Path(tmp) / "gone.wav"))

    def test_delete_failure_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview"
            victim = touch(preview / "a.wav")
            with mock.patch.object(Path, "unlink",
                                   side_effect=PermissionError("locked")):
                summary = cleanup_preview_files(preview)
            self.assertEqual(summary["deleted"], [])
            self.assertEqual(summary["errors"], [str(victim)])


if __name__ == "__main__":
    unittest.main()
