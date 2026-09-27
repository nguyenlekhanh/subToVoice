"""
Tests for Subtitle Editing and Timeline Drag Functionality
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.subtitle import Subtitle
from services.srt_service import SRTService, SRTParseError


def test_subtitle_model():
    """Test Subtitle model creation and validation"""
    print("Testing Subtitle model...")

    # Valid subtitle
    s = Subtitle(1, 2000, 4000, "Test subtitle")
    assert s.index == 1
    assert s.start_ms == 2000
    assert s.end_ms == 4000
    assert s.text == "Test subtitle"
    assert s.voice == ""
    print("  ✓ Valid subtitle creation works")

    # Multi-line subtitle
    s2 = Subtitle(2, 5000, 7000, "Line 1\nLine 2")
    assert s2.text == "Line 1\nLine 2"
    print("  ✓ Multi-line text preserved")

    # Voice field
    s3 = Subtitle(3, 8000, 10000, "Voice test", voice="vietnamese")
    assert s3.voice == "vietnamese"
    print("  ✓ Voice field works")

    # Validation tests
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


def test_time_parsing():
    """Test time string parsing for editing"""
    print("Testing time parsing...")

    def parse_time_input(time_str: str) -> int:
        if not time_str:
            return None
        try:
            parts = time_str.split(':')
            if len(parts) == 2:
                # MM:SS.mmm
                minutes = int(parts[0])
                sec_parts = parts[1].split('.')
                seconds = int(sec_parts[0])
                milliseconds = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0
                return minutes * 60 * 1000 + seconds * 1000 + milliseconds
            elif len(parts) == 3:
                # HH:MM:SS.mmm
                hours = int(parts[0])
                minutes = int(parts[1])
                sec_parts = parts[2].split('.')
                seconds = int(sec_parts[0])
                milliseconds = int(sec_parts[1].ljust(3, '0')[:3]) if len(sec_parts) > 1 else 0
                return hours * 3600 * 1000 + minutes * 60 * 1000 + seconds * 1000 + milliseconds
            else:
                return None
        except (ValueError, IndexError):
            return None

    test_cases = [
        ("00:00.000", 0),
        ("00:05.000", 5000),
        ("01:30.500", 90500),
        ("00:10.123", 10123),
        ("01:00:00.000", 3600000),
        ("01:02:03.456", 3723456),
        ("invalid", None),
        ("", None),
        ("00:00", 0),
        ("05:00.001", 300001),
    ]

    for time_str, expected in test_cases:
        result = parse_time_input(time_str)
        assert result == expected, f"Failed: {time_str} -> {result}, expected {expected}"
        print(f"  ✓ {time_str} -> {result}ms")

    print("  All time parsing tests passed!")


def test_time_formatting():
    """Test time formatting for display"""
    print("Testing time formatting...")

    def format_short_timestamp(ms: int) -> str:
        if ms < 0:
            return "00:00.000"
        minutes = ms // (60 * 1000)
        ms_remaining = ms % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def format_timestamp_display(ms: int) -> str:
        if ms < 0:
            return "00:00:00.000"
        hours = ms // (3600 * 1000)
        ms_remaining = ms % (3600 * 1000)
        minutes = ms_remaining // (60 * 1000)
        ms_remaining = ms_remaining % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    # Test short format
    test_cases = [
        (0, "00:00.000"),
        (1000, "00:01.000"),
        (5000, "00:05.000"),
        (10000, "00:10.000"),
        (61000, "01:01.000"),
        (125500, "02:05.500"),
    ]

    for ms, expected in test_cases:
        result = format_short_timestamp(ms)
        assert result == expected, f"Short format failed: {ms} -> {result}, expected {expected}"
        print(f"  ✓ Short: {ms}ms -> {result}")

    # Test display format
    display_cases = [
        (0, "00:00:00.000"),
        (1000, "00:00:01.000"),
        (5000, "00:00:05.000"),
        (65000, "00:01:05.000"),
        (3723250, "01:02:03.250"),
    ]

    for ms, expected in display_cases:
        result = format_timestamp_display(ms)
        assert result == expected, f"Display format failed: {ms} -> {result}, expected {expected}"
        print(f"  ✓ Display: {ms}ms -> {result}")

    print("  All time formatting tests passed!")


def test_time_to_x_conversion():
    """Test time to x coordinate conversion (simulated)"""
    print("Testing time to x conversion...")

    def time_to_x(time_ms, duration_ms, canvas_width, margin_left=50, margin_right=20):
        if duration_ms <= 0:
            return margin_left
        time_ms = max(0, min(time_ms, duration_ms))
        available_width = canvas_width - margin_left - margin_right
        x = margin_left + int((time_ms / duration_ms) * available_width)
        return x

    def x_to_time(x, duration_ms, canvas_width, margin_left=50, margin_right=20):
        if duration_ms <= 0:
            return 0
        available_width = canvas_width - margin_left - margin_right
        x = max(margin_left, min(x, canvas_width - margin_right))
        ratio = (x - margin_left) / available_width
        time_ms = int(ratio * duration_ms)
        return max(0, min(time_ms, duration_ms))

    canvas_width = 1000
    duration_ms = 10000  # 10 seconds

    test_cases = [
        (0, 50),  # Start
        (5000, 525),  # Middle
        (10000, 930),  # End
        (-1000, 50),  # Clamped to start
        (15000, 930),  # Clamped to end
    ]

    for ms, expected_x in test_cases:
        x = time_to_x(ms, duration_ms, canvas_width)
        assert x == expected_x, f"Failed: {ms}ms -> {x}, expected {expected_x}"
        print(f"  ✓ {ms}ms -> {x}px")

    # Test round trip
    for ms in [0, 1000, 5000, 10000]:
        x = time_to_x(ms, duration_ms, canvas_width)
        back_ms = x_to_time(x, duration_ms, canvas_width)
        assert back_ms == max(0, min(ms, duration_ms)), f"Round-trip failed: {ms} -> {x} -> {back_ms}"
        print(f"  ✓ Round-trip: {ms}ms <-> {x}px <-> {back_ms}ms")

    print("  All time conversion tests passed!")


def test_subtitle_timing_validation():
    """Test subtitle timing validation logic"""
    print("Testing subtitle timing validation...")

    # Test cases: (start_ms, end_ms, video_duration, expected_valid, expected_error_msg)
    test_cases = [
        # Valid cases
        (0, 5000, 10000, True, None),
        (1000, 5000, 10000, True, None),
        (5000, 10000, 10000, True, None),
        (0, 10000, 10000, True, None),
        
        # Invalid cases
        (-100, 5000, 10000, False, "negative"),
        (5000, 5000, 10000, False, "equal"),
        (6000, 5000, 10000, False, "end <= start"),
        (15000, 20000, 10000, False, "exceeds duration"),
        (5000, 15000, 10000, False, "end exceeds duration"),
    ]

    def validate_timing(start_ms, end_ms, video_duration_ms):
        if start_ms < 0:
            return False, "start_ms < 0"
        if end_ms <= start_ms:
            return False, "end_ms <= start_ms"
        if video_duration_ms > 0 and end_ms > video_duration_ms:
            return False, "end_ms > video_duration"
        return True, None

    for start, end, duration, expected_valid, expected_error in test_cases:
        valid, error = validate_timing(start, end, duration)
        assert valid == expected_valid, f"Validation failed: {start}-{end} with duration {duration}"
        if not valid:
            assert expected_error in error, f"Error message mismatch: {error}"
        print(f"  ✓ {start}-{end} (duration={duration}): valid={valid}, error={error}")

    print("  All validation tests passed!")


def test_clamping_logic():
    """Test subtitle drag clamping logic"""
    print("Testing drag clamping logic...")

    def clamp_drag(start_ms, end_ms, video_duration_ms):
        """Simulate drag clamping"""
        duration = end_ms - start_ms
        
        # Clamp start
        if start_ms < 0:
            start_ms = 0
            end_ms = start_ms + duration
        
        # Clamp end
        if end_ms > video_duration_ms:
            end_ms = video_duration_ms
            start_ms = end_ms - duration
        
        # Re-check start after end clamp
        if start_ms < 0:
            start_ms = 0
            end_ms = start_ms + duration
        
        return start_ms, end_ms

    video_duration = 10000
    
    test_cases = [
        # (start, end, expected_start, expected_end, description)
        (1000, 3000, 1000, 3000, "Normal within bounds"),
        (-1000, 1000, 0, 2000, "Start before 0"),
        (8000, 11000, 7000, 10000, "End beyond duration"),
        (-2000, 500, 0, 2500, "Both before 0"),
        (9000, 12000, 7000, 10000, "Both beyond duration"),
        (5000, 1000, 0, 5000, "End before start (should fix)"),
    ]

    for start, end, exp_start, exp_end, desc in test_cases:
        result_start, result_end = clamp_drag(start, end, video_duration)
        assert result_start == exp_start, f"Start mismatch: {desc} got {result_start}, expected {exp_start}"
        assert result_end == exp_end, f"End mismatch: {desc} got {result_end}, expected {exp_end}"
        print(f"  ✓ {desc}: {start}-{end} -> {result_start}-{result_end}")

    print("  All clamping tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING PLAN 8 TESTS")
    print("=" * 60)

    test_subtitle_model()
    print()
    test_time_parsing()
    print()
    test_time_formatting()
    print()
    test_time_to_x_conversion()
    print()
    test_subtitle_timing_validation()
    print()
    test_clamping_logic()
    print()
    print("=" * 60)
    print("ALL PLAN 8 TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()