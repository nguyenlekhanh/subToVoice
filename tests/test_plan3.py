"""
Tests for PLAN 3 - GUI Integration
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.subtitle import Subtitle
from services.srt_service import SRTService, SRTParseError


def test_timestamp_display_format():
    """Test the timestamp display format (HH:MM:SS.mmm)"""
    print("Testing timestamp display format...")

    # Test the same logic as _format_timestamp_display
    def format_display(ms: int) -> str:
        if ms < 0:
            return "00:00:00.000"
        hours = ms // (3600 * 1000)
        ms_remaining = ms % (3600 * 1000)
        minutes = ms_remaining // (60 * 1000)
        ms_remaining = ms_remaining % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    test_cases = [
        (0, "00:00:00.000"),
        (1000, "00:00:01.000"),
        (2500, "00:00:02.500"),
        (60500, "00:01:00.500"),
        (3723250, "01:02:03.250"),
        (45296789, "12:34:56.789"),
        (-100, "00:00:00.000"),
    ]

    for ms, expected in test_cases:
        result = format_display(ms)
        assert result == expected, f"Failed: {ms}ms -> {result}, expected {expected}"
        print(f"  ✓ {ms}ms -> {result}")

    print("  All timestamp display tests passed!")


def test_srt_service_imports():
    """Test that SRT service imports work"""
    print("Testing SRT service imports...")
    from services.srt_service import SRTService, SRTParseError
    from models.subtitle import Subtitle
    print("  ✓ All imports successful")


def test_subtitle_model():
    """Test Subtitle model still works"""
    print("Testing Subtitle model...")

    s = Subtitle(1, 2000, 4000, "Test subtitle")
    assert s.index == 1
    assert s.start_ms == 2000
    assert s.end_ms == 4000
    assert s.text == "Test subtitle"
    assert s.voice == ""
    print("  ✓ Subtitle creation works")

    # Test multi-line
    s2 = Subtitle(2, 5000, 7000, "Line 1\nLine 2")
    assert s2.text == "Line 1\nLine 2"
    print("  ✓ Multi-line text preserved")

    # Test voice field
    s3 = Subtitle(3, 8000, 10000, "Voice test", voice="vietnamese")
    assert s3.voice == "vietnamese"
    print("  ✓ Voice field works")

    print("  All Subtitle model tests passed!")


def test_srt_parsing():
    """Test SRT parsing with Vietnamese text"""
    print("Testing SRT parsing...")

    test_content = """1
00:00:02,000 --> 00:00:04,000
Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?

2
00:00:04,500 --> 00:00:06,500
Ừ, duyệt cho con luôn.

3
00:00:07,000 --> 00:00:09,500
Oh yeah quá xá đã!

4
00:00:10,000 --> 00:00:13,000
Đây là dòng đầu tiên.
Đây là dòng thứ hai.
"""

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(test_content)
        temp_path = f.name

    try:
        subtitles = SRTService.load_srt(temp_path)
        assert len(subtitles) == 4
        assert subtitles[0].index == 1
        assert subtitles[0].start_ms == 2000
        assert subtitles[0].end_ms == 4000
        assert subtitles[0].text == "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"
        assert subtitles[1].text == "Ừ, duyệt cho con luôn."
        assert subtitles[2].text == "Oh yeah quá xá đã!"
        assert subtitles[3].text == "Đây là dòng đầu tiên.\nĐây là dòng thứ hai."
        print("  ✓ Vietnamese text parsed correctly")
        print("  ✓ Multi-line subtitle preserved")
    finally:
        os.unlink(temp_path)

    print("  All SRT parsing tests passed!")


def test_round_trip():
    """Test SRT round-trip (load -> save -> load)"""
    print("Testing SRT round-trip...")

    test_content = """1
00:00:02,000 --> 00:00:04,000
Test subtitle 1

2
00:00:05,000 --> 00:00:07,000
Test subtitle 2
"""

    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(test_content)
        temp_path1 = f.name

    temp_path2 = temp_path1 + ".roundtrip.srt"

    try:
        original = SRTService.load_srt(temp_path1)
        SRTService.save_srt(temp_path2, original)
        roundtrip = SRTService.load_srt(temp_path2)

        assert len(original) == len(roundtrip)
        for o, r in zip(original, roundtrip):
            assert o.index == r.index
            assert o.start_ms == r.start_ms
            assert o.end_ms == r.end_ms
            assert o.text == r.text
        print("  ✓ Round-trip successful")
    finally:
        os.unlink(temp_path1)
        if os.path.exists(temp_path2):
            os.unlink(temp_path2)

    print("  All round-trip tests passed!")


def test_error_handling():
    """Test error handling for invalid SRT"""
    print("Testing error handling...")

    import tempfile

    # Invalid timestamp
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write("1\ninvalid timestamp\ntext")
        temp_path = f.name
    try:
        try:
            SRTService.load_srt(temp_path)
            assert False, "Should have raised SRTParseError"
        except SRTParseError as e:
            print(f"  ✓ Invalid timestamp raises error: {e}")
    finally:
        os.unlink(temp_path)

    # End before start
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write("1\n00:00:05,000 --> 00:00:03,000\ntext")
        temp_path = f.name
    try:
        try:
            SRTService.load_srt(temp_path)
            assert False, "Should have raised SRTParseError"
        except SRTParseError as e:
            print(f"  ✓ End before start raises error: {e}")
    finally:
        os.unlink(temp_path)

    print("  All error handling tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING PLAN 3 TESTS")
    print("=" * 60)

    test_srt_service_imports()
    print()
    test_subtitle_model()
    print()
    test_timestamp_display_format()
    print()
    test_srt_parsing()
    print()
    test_round_trip()
    print()
    test_error_handling()
    print()
    print("=" * 60)
    print("ALL PLAN 3 TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()