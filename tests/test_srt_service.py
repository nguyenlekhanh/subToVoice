"""
Tests for SRT Service
"""
import tempfile
import os
import sys

# Add project root to path
sys.path.insert(0, r'C:\khanh\python\30_2 subTheoVoice1')

from models.subtitle import Subtitle
from services.srt_service import SRTService, SRTParseError


TEST_SRT_CONTENT = """1
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

def test_timestamp_parsing():
    """Test SRT timestamp to milliseconds conversion"""
    print("Testing timestamp parsing...")

    test_cases = [
        ("00:00:02,000", 2000),
        ("00:01:05,500", 65500),
        ("01:02:03,250", 3723250),
        ("00:00:00,000", 0),
        ("12:34:56,789", 45296789),
    ]

    for timestamp_str, expected_ms in test_cases:
        result = SRTService.parse_timestamp(timestamp_str)
        assert result == expected_ms, f"Failed: {timestamp_str} -> {result}, expected {expected_ms}"
        print(f"  ✓ {timestamp_str} -> {result}ms")

    print("  All timestamp parsing tests passed!")


def test_timestamp_formatting():
    """Test milliseconds to SRT timestamp conversion"""
    print("Testing timestamp formatting...")

    test_cases = [
        (0, "00:00:00,000"),
        (1000, "00:00:01,000"),
        (2500, "00:00:02,500"),
        (60500, "00:01:00,500"),
        (3723250, "01:02:03,250"),
        (45296789, "12:34:56,789"),
    ]

    for ms, expected_str in test_cases:
        result = SRTService.format_timestamp(ms)
        assert result == expected_str, f"Failed: {ms}ms -> {result}, expected {expected_str}"
        print(f"  ✓ {ms}ms -> {result}")

    print("  All timestamp formatting tests passed!")


def test_round_trip_timestamp():
    """Test round-trip timestamp conversion"""
    print("Testing timestamp round-trip...")

    test_values = [0, 1000, 2500, 60500, 3723250, 45296789, 123456789]

    for ms in test_values:
        ts = SRTService.format_timestamp(ms)
        back_ms = SRTService.parse_timestamp(ts)
        assert back_ms == ms, f"Round-trip failed: {ms} -> {ts} -> {back_ms}"
        print(f"  ✓ {ms}ms <-> {ts}")

    print("  All round-trip tests passed!")


def test_load_srt():
    """Test loading SRT file"""
    print("Testing SRT loading...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(TEST_SRT_CONTENT)
        temp_path = f.name

    try:
        subtitles = SRTService.load_srt(temp_path)

        assert len(subtitles) == 4, f"Expected 4 subtitles, got {len(subtitles)}"
        print(f"  ✓ Loaded {len(subtitles)} subtitles")

        # Check subtitle 1
        s1 = subtitles[0]
        assert s1.index == 1
        assert s1.start_ms == 2000
        assert s1.end_ms == 4000
        assert s1.text == "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"
        assert s1.voice == ""
        print(f"  ✓ Subtitle 1: index={s1.index}, start={s1.start_ms}, end={s1.end_ms}")

        # Check subtitle 2
        s2 = subtitles[1]
        assert s2.index == 2
        assert s2.start_ms == 4500
        assert s2.end_ms == 6500
        assert s2.text == "Ừ, duyệt cho con luôn."
        print(f"  ✓ Subtitle 2: index={s2.index}, start={s2.start_ms}, end={s2.end_ms}")

        # Check subtitle 3
        s3 = subtitles[2]
        assert s3.index == 3
        assert s3.start_ms == 7000
        assert s3.end_ms == 9500
        assert s3.text == "Oh yeah quá xá đã!"
        print(f"  ✓ Subtitle 3: index={s3.index}, start={s3.start_ms}, end={s3.end_ms}")

        # Check subtitle 4 (multi-line)
        s4 = subtitles[3]
        assert s4.index == 4
        assert s4.start_ms == 10000
        assert s4.end_ms == 13000
        assert s4.text == "Đây là dòng đầu tiên.\nĐây là dòng thứ hai."
        print(f"  ✓ Subtitle 4 (multi-line): index={s4.index}, start={s4.start_ms}, end={s4.end_ms}")
        print(f"    Text: {repr(s4.text)}")

        print("  All SRT loading tests passed!")

    finally:
        os.unlink(temp_path)


def test_save_srt():
    """Test saving SRT file"""
    print("Testing SRT saving...")

    subtitles = [
        Subtitle(1, 2000, 4000, "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"),
        Subtitle(2, 4500, 6500, "Ừ, duyệt cho con luôn."),
        Subtitle(3, 7000, 9500, "Oh yeah quá xá đã!"),
        Subtitle(4, 10000, 13000, "Đây là dòng đầu tiên.\nĐây là dòng thứ hai."),
    ]

    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        temp_path = f.name

    try:
        SRTService.save_srt(temp_path, subtitles)

        # Read back and verify content
        with open(temp_path, 'r', encoding='utf-8') as f:
            content = f.read()

        print(f"  Saved content:\n{content}")

        # Verify key elements
        assert "1\n00:00:02,000 --> 00:00:04,000\nMẹ ơi, ba ơi, cho con đi chơi với các bạn nha?" in content
        assert "2\n00:00:04,500 --> 00:00:06,500\nỪ, duyệt cho con luôn." in content
        assert "3\n00:00:07,000 --> 00:00:09,500\nOh yeah quá xá đã!" in content
        assert "4\n00:00:10,000 --> 00:00:13,000\nĐây là dòng đầu tiên.\nĐây là dòng thứ hai." in content

        print("  SRT saving test passed!")

    finally:
        os.unlink(temp_path)


def test_round_trip_srt():
    """Test round-trip: SRT -> load -> save -> load"""
    print("Testing SRT round-trip...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(TEST_SRT_CONTENT)
        temp_path1 = f.name

    temp_path2 = temp_path1 + ".roundtrip.srt"

    try:
        # Load original
        original_subtitles = SRTService.load_srt(temp_path1)

        # Save to new file
        SRTService.save_srt(temp_path2, original_subtitles)

        # Load again
        roundtrip_subtitles = SRTService.load_srt(temp_path2)

        # Compare
        assert len(original_subtitles) == len(roundtrip_subtitles), "Subtitle count mismatch after round-trip"

        for i, (orig, rt) in enumerate(zip(original_subtitles, roundtrip_subtitles)):
            assert orig.index == rt.index, f"Subtitle {i}: index mismatch: {orig.index} != {rt.index}"
            assert orig.start_ms == rt.start_ms, f"Subtitle {i}: start_ms mismatch: {orig.start_ms} != {rt.start_ms}"
            assert orig.end_ms == rt.end_ms, f"Subtitle {i}: end_ms mismatch: {orig.end_ms} != {rt.end_ms}"
            assert orig.text == rt.text, f"Subtitle {i}: text mismatch"
            assert orig.voice == rt.voice, f"Subtitle {i}: voice mismatch"

        print(f"  ✓ Round-trip successful: {len(original_subtitles)} subtitles match perfectly")
        print("  All round-trip tests passed!")

    finally:
        os.unlink(temp_path1)
        if os.path.exists(temp_path2):
            os.unlink(temp_path2)


def test_error_handling():
    """Test error handling for invalid SRT data"""
    print("Testing error handling...")

    # Test invalid timestamp format
    try:
        SRTService.parse_timestamp("invalid")
        assert False, "Should have raised SRTParseError"
    except SRTParseError as e:
        print(f"  ✓ Invalid timestamp raises error: {e}")

    # Test end <= start
    try:
        SRTService.parse_timestamp("00:00:05,000")  # 5000ms
        SRTService.parse_timestamp("00:00:03,000")  # 3000ms
        # This would be caught at subtitle creation
        Subtitle(1, 5000, 3000, "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ end_ms <= start_ms raises error: {e}")

    # Test negative ms formatting
    try:
        SRTService.format_timestamp(-100)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ Negative ms raises error: {e}")

    # Test invalid SRT block (missing timestamp)
    invalid_srt = """1
not a timestamp
text here
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(invalid_srt)
        temp_path = f.name

    try:
        try:
            SRTService.load_srt(temp_path)
            assert False, "Should have raised SRTParseError"
        except SRTParseError as e:
            print(f"  ✓ Invalid timestamp line raises error: {e}")
    finally:
        os.unlink(temp_path)

    # Test missing text
    invalid_srt2 = """1
00:00:01,000 --> 00:00:02,000
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
        f.write(invalid_srt2)
        temp_path = f.name

    try:
        try:
            SRTService.load_srt(temp_path)
            assert False, "Should have raised SRTParseError"
        except SRTParseError as e:
            print(f"  ✓ Missing text raises error: {e}")
    finally:
        os.unlink(temp_path)

    print("  All error handling tests passed!")


def test_subtitle_model():
    """Test Subtitle model"""
    print("Testing Subtitle model...")

    # Valid subtitle
    s = Subtitle(1, 1000, 2000, "Hello world")
    assert s.index == 1
    assert s.start_ms == 1000
    assert s.end_ms == 2000
    assert s.text == "Hello world"
    assert s.voice == ""
    print("  ✓ Valid subtitle created")

    # Default voice
    s2 = Subtitle(2, 3000, 4000, "Test", voice="vietnamese")
    assert s2.voice == "vietnamese"
    print("  ✓ Custom voice works")

    # Test validation
    try:
        Subtitle(1, -100, 2000, "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ Negative start_ms raises error: {e}")

    try:
        Subtitle(1, 2000, 1000, "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ end_ms <= start_ms raises error: {e}")

    try:
        Subtitle(0, 1000, 2000, "test")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✓ Invalid index raises error: {e}")

    print("  All Subtitle model tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING SRT SERVICE TESTS")
    print("=" * 60)

    test_subtitle_model()
    print()
    test_timestamp_parsing()
    print()
    test_timestamp_formatting()
    print()
    test_round_trip_timestamp()
    print()
    test_load_srt()
    print()
    test_save_srt()
    print()
    test_round_trip_srt()
    print()
    test_error_handling()
    print()
    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()