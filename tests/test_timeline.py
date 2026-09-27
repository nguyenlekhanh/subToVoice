"""
Tests for Timeline Logic
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_time_to_x_conversion():
    """Test time to x coordinate conversion"""
    print("Testing time_to_x conversion...")

    # Simulate the conversion logic
    def time_to_x(time_ms, duration_ms, canvas_width, margin_left=50, margin_right=20):
        if duration_ms <= 0:
            return margin_left
        time_ms = max(0, min(time_ms, duration_ms))
        available_width = canvas_width - margin_left - margin_right
        x = margin_left + int((time_ms / duration_ms) * available_width)
        return x

    # Test cases
    canvas_width = 1000
    duration_ms = 10000  # 10 seconds

    test_cases = [
        (0, 50),  # Start
        (5000, 525),  # Middle
        (10000, 930),  # End
        (-1000, 50),  # Clamped to start
        (15000, 930),  # Clamped to end
    ]

    for time_ms, expected_x in test_cases:
        result = time_to_x(time_ms, duration_ms, canvas_width)
        assert result == expected_x, f"Failed: {time_ms}ms -> {result}, expected {expected_x}"
        print(f"  ✓ {time_ms}ms -> {result}px")

    print("  All time_to_x tests passed!")


def test_x_to_time_conversion():
    """Test x coordinate to time conversion"""
    print("Testing x_to_time conversion...")

    def x_to_time(x, duration_ms, canvas_width, margin_left=50, margin_right=20):
        if duration_ms <= 0:
            return 0
        available_width = canvas_width - margin_left - margin_right
        x = max(margin_left, min(x, canvas_width - margin_right))
        ratio = (x - margin_left) / available_width
        time_ms = int(ratio * duration_ms)
        return max(0, min(time_ms, duration_ms))

    canvas_width = 1000
    duration_ms = 10000

    test_cases = [
        (50, 0),  # Start
        (525, 5000),  # Middle
        (930, 10000),  # End
        (0, 0),  # Clamped to start
        (1000, 10000),  # Clamped to end
    ]

    for x, expected_ms in test_cases:
        result = x_to_time(x, duration_ms, canvas_width)
        assert result == expected_ms, f"Failed: {x}px -> {result}ms, expected {expected_ms}ms"
        print(f"  ✓ {x}px -> {result}ms")

    print("  All x_to_time tests passed!")


def test_marker_interval_calculation():
    """Test marker interval calculation based on duration"""
    print("Testing marker interval calculation...")

    def calculate_marker_interval(duration_ms):
        duration_s = duration_ms / 1000.0
        if duration_s <= 60:
            return 5000
        elif duration_s <= 300:
            return 10000
        elif duration_s <= 600:
            return 30000
        elif duration_s <= 1800:
            return 60000
        elif duration_s <= 3600:
            return 120000
        else:
            return 300000

    test_cases = [
        (30000, 5000),  # 30s -> 5s
        (60000, 10000),  # 60s -> 10s
        (120000, 10000),  # 2min -> 10s
        (300000, 30000),  # 5min -> 30s
        (600000, 60000),  # 10min -> 1min
        (1800000, 60000),  # 30min -> 1min
        (3600000, 120000),  # 1hr -> 2min
        (7200000, 300000),  # 2hr -> 5min
    ]

    for duration_ms, expected_interval in test_cases:
        result = calculate_marker_interval(duration_ms)
        assert result == expected_interval, f"Failed: {duration_ms}ms -> {result}ms, expected {expected_interval}ms"
        print(f"  ✓ {duration_ms/1000}s -> {result/1000}s interval")

    print("  All marker interval tests passed!")


def test_timeline_time_formatting():
    """Test timeline time formatting"""
    print("Testing timeline time formatting...")

    def format_timeline_time(ms):
        if ms < 0:
            return "00:00"
        hours = ms // (3600 * 1000)
        ms_remaining = ms % (3600 * 1000)
        minutes = ms_remaining // (60 * 1000)
        seconds = (ms_remaining % (60 * 1000)) // 1000

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    test_cases = [
        (0, "00:00"),
        (5000, "00:05"),
        (60000, "01:00"),
        (65000, "01:05"),
        (3600000, "01:00:00"),
        (3665000, "01:01:05"),
    ]

    for ms, expected in test_cases:
        result = format_timeline_time(ms)
        assert result == expected, f"Failed: {ms}ms -> {result}, expected {expected}"
        print(f"  ✓ {ms}ms -> {result}")

    print("  All timeline time formatting tests passed!")


def test_round_trip_conversion():
    """Test round-trip time -> x -> time conversion"""
    print("Testing round-trip conversion...")

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
    duration_ms = 123456  # Arbitrary duration

    test_times = [0, 1000, 12345, 61728, 100000, 123456, -1000, 200000]

    for time_ms in test_times:
        x = time_to_x(time_ms, duration_ms, canvas_width)
        back_ms = x_to_time(x, duration_ms, canvas_width)
        # Allow small rounding difference
        assert abs(back_ms - max(0, min(time_ms, duration_ms))) <= 1, \
            f"Round-trip failed: {time_ms} -> {x}px -> {back_ms}ms"
        print(f"  ✓ {time_ms}ms -> {x}px -> {back_ms}ms")

    print("  All round-trip tests passed!")


def test_zero_duration():
    """Test handling of zero duration"""
    print("Testing zero duration handling...")

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
    duration_ms = 0

    # Should not crash
    x = time_to_x(1000, duration_ms, canvas_width)
    assert x == 50, f"Expected 50, got {x}"
    print(f"  ✓ time_to_x with zero duration returns margin_left: {x}")

    time_ms = x_to_time(500, duration_ms, canvas_width)
    assert time_ms == 0, f"Expected 0, got {time_ms}"
    print(f"  ✓ x_to_time with zero duration returns 0: {time_ms}")

    print("  All zero duration tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING TIMELINE TESTS")
    print("=" * 60)

    test_time_to_x_conversion()
    print()
    test_x_to_time_conversion()
    print()
    test_marker_interval_calculation()
    print()
    test_timeline_time_formatting()
    print()
    test_round_trip_conversion()
    print()
    test_zero_duration()
    print()
    print("=" * 60)
    print("ALL TIMELINE TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()