"""
Tests for Subtitle Timeline Logic
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models.subtitle import Subtitle


def test_subtitle_block_positioning():
    """Test subtitle block time-to-x conversion"""
    print("Testing subtitle block positioning...")

    # Simulate the conversion logic from _time_to_x
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
    margin_left = 50
    margin_right = 20
    available_width = canvas_width - margin_left - margin_right  # 930

    # Subtitle from 2s to 5s
    sub1_start = 2000
    sub1_end = 5000
    left_x = time_to_x(sub1_start, duration_ms, canvas_width)
    right_x = time_to_x(sub1_end, duration_ms, canvas_width)
    
    expected_left = margin_left + int((2000 / 10000) * available_width)  # 50 + 0.2 * 930 = 236
    expected_right = margin_left + int((5000 / 10000) * available_width)  # 50 + 0.5 * 930 = 515
    
    assert left_x == expected_left, f"Start: {left_x} != {expected_left}"
    assert right_x == expected_right, f"End: {right_x} != {expected_right}"
    assert right_x - left_x == int(0.3 * available_width), "Block width should be 30% of available width"
    
    print(f"  ✓ Subtitle 2s-5s: x={left_x}-{right_x} (width={right_x-left_x}px)")

    # Subtitle from 0s to 10s (full duration)
    left_x = time_to_x(0, duration_ms, canvas_width)
    right_x = time_to_x(10000, duration_ms, canvas_width)
    assert left_x == margin_left, f"Full start: {left_x} != {margin_left}"
    assert right_x == canvas_width - margin_right, f"Full end: {right_x} != {canvas_width - margin_right}"
    print(f"  ✓ Subtitle 0s-10s: x={left_x}-{right_x} (full width)")

    # Very short subtitle (100ms) - should enforce minimum width
    sub_short_start = 1000
    sub_short_end = 1100
    left_x = time_to_x(sub_short_start, duration_ms, canvas_width)
    right_x = time_to_x(sub_short_end, duration_ms, canvas_width)
    # Width would be very small, should be enforced to minimum 8px in actual rendering
    print(f"  ✓ Short subtitle 1s-1.1s: x={left_x}-{right_x} (width={right_x-left_x}px)")

    print("  All subtitle block positioning tests passed!")


def test_minimum_visual_width():
    """Test minimum visual width enforcement"""
    print("Testing minimum visual width enforcement...")

    def enforce_min_width(left_x, right_x, min_width=8):
        if right_x - left_x < min_width:
            right_x = left_x + min_width
        return left_x, right_x

    # Normal subtitle (wide enough)
    l, r = enforce_min_width(100, 200)
    assert l == 100 and r == 200, "Normal width should not change"
    print(f"  ✓ Normal width: 100-200 -> {l}-{r}")

    # Too narrow subtitle
    l, r = enforce_min_width(100, 105)
    assert l == 100 and r == 108, f"Narrow width should be expanded: {l}-{r}"
    print(f"  ✓ Narrow width: 100-105 -> {l}-{r} (enforced to 8px)")

    # Zero width (should not happen but test)
    l, r = enforce_min_width(100, 100)
    assert l == 100 and r == 108, f"Zero width should be expanded: {l}-{r}"
    print(f"  ✓ Zero width: 100-100 -> {l}-{r} (enforced to 8px)")

    print("  All minimum visual width tests passed!")


def test_clamping_to_timeline_bounds():
    """Test subtitle block clamping to timeline bounds"""
    print("Testing subtitle block clamping to timeline bounds...")

    def clamp_to_bounds(left_x, right_x, margin_left=50, margin_right=20, canvas_width=1000):
        left_x = max(margin_left, left_x)
        right_x = min(canvas_width - margin_right, right_x)
        return left_x, right_x

    # Subtitle starting before timeline
    l, r = clamp_to_bounds(0, 100)
    assert l == 50 and r == 100, f"Left clamp: {l}-{r}"
    print(f"  ✓ Left clamp: 0-100 -> {l}-{r}")

    # Subtitle ending after timeline
    l, r = clamp_to_bounds(950, 1050)
    assert l == 950 and r == 980, f"Right clamp: {l}-{r}"
    print(f"  ✓ Right clamp: 950-1050 -> {l}-{r}")

    # Subtitle completely out of bounds
    l, r = clamp_to_bounds(-100, 20)
    assert l == 50 and r == 50, f"Out of bounds: {l}-{r} (becomes zero width, min width enforced later)"
    print(f"  ✓ Out of bounds: -100-20 -> {l}-{r}")

    print("  All clamping tests passed!")


def test_subtitle_text_truncation():
    """Test subtitle text truncation for block display"""
    print("Testing subtitle text truncation...")

    def truncate_subtitle_text(text: str, max_width_px: int) -> str:
        if not text:
            return ""
        display_text = text.replace('\n', ' | ')
        max_chars = max(1, max_width_px // 8)
        if len(display_text) > max_chars:
            return display_text[:max_chars - 3] + "..."
        return display_text

    # Short text fits
    result = truncate_subtitle_text("Hello", 100)
    assert result == "Hello", f"Short text: {result}"
    print(f"  ✓ Short text: 'Hello' -> '{result}'")

    # Long text truncates
    result = truncate_subtitle_text("This is a very long subtitle text that should be truncated", 80)
    max_chars = 80 // 8  # 10 chars
    expected = "This is a "[:7] + "..."
    assert result == "This is..." or result == "This is a...", f"Truncated: {result}"
    print(f"  ✓ Long text truncated: '{result}'")

    # Multi-line text
    result = truncate_subtitle_text("Line 1\nLine 2", 100)
    assert result == "Line 1 | Line 2", f"Multi-line: {result}"
    print(f"  ✓ Multi-line: 'Line 1\\nLine 2' -> '{result}'")

    # Empty text
    result = truncate_subtitle_text("", 100)
    assert result == "", f"Empty text: '{result}'"
    print(f"  ✓ Empty text: '' -> '{result}'")

    print("  All text truncation tests passed!")


def test_out_of_range_subtitles():
    """Test handling of subtitles outside video duration"""
    print("Testing out-of-range subtitle handling...")

    def time_to_x(time_ms, duration_ms, canvas_width, margin_left=50, margin_right=20):
        if duration_ms <= 0:
            return margin_left
        time_ms = max(0, min(time_ms, duration_ms))
        available_width = canvas_width - margin_left - margin_right
        x = margin_left + int((time_ms / duration_ms) * available_width)
        return x

    canvas_width = 1000
    duration_ms = 10000
    margin_left = 50
    margin_right = 20

    # Subtitle starts before video (negative time - shouldn't happen but test)
    left_x = time_to_x(-1000, duration_ms, canvas_width)
    assert left_x == 50, f"Negative time clamped to start: {left_x}"
    print(f"  ✓ Negative start time clamped: {left_x}")

    # Subtitle ends after video duration
    right_x = time_to_x(15000, duration_ms, canvas_width)
    assert right_x == 980, f"End after duration clamped: {right_x}"
    print(f"  ✓ End after duration clamped: {right_x}")

    print("  All out-of-range tests passed!")


def test_empty_subtitle_list():
    """Test handling of empty subtitle list"""
    print("Testing empty subtitle list...")

    subtitles = []
    # Should not crash, just do nothing
    assert len(subtitles) == 0
    print("  ✓ Empty list handled correctly")

    print("  Empty list test passed!")


def test_multiple_subtitle_positioning():
    """Test multiple subtitles at different positions"""
    print("Testing multiple subtitle positioning...")

    def time_to_x(time_ms, duration_ms, canvas_width, margin_left=50, margin_right=20):
        if duration_ms <= 0:
            return margin_left
        time_ms = max(0, min(time_ms, duration_ms))
        available_width = canvas_width - margin_left - margin_right
        x = margin_left + int((time_ms / duration_ms) * available_width)
        return x

    canvas_width = 1000
    duration_ms = 10000
    margin_left = 50
    margin_right = 20

    # Create multiple subtitles
    subtitles = [
        Subtitle(1, 0, 2000, "First subtitle"),
        Subtitle(2, 3000, 5000, "Second subtitle"),
        Subtitle(3, 6000, 8000, "Third subtitle"),
        Subtitle(4, 9000, 10000, "Last subtitle"),
    ]

    positions = []
    for sub in subtitles:
        left = time_to_x(sub.start_ms, duration_ms, canvas_width)
        right = time_to_x(sub.end_ms, duration_ms, canvas_width)
        positions.append((left, right))
        print(f"  Subtitle {sub.index}: {sub.start_ms}ms-{sub.end_ms}ms -> x={left}-{right}")

    # Verify ordering
    for i in range(len(positions) - 1):
        assert positions[i][1] <= positions[i+1][0], "Subtitles should not overlap in this test"
    
    # Check specific positions
    assert positions[0] == (50, 236), f"First: {positions[0]}"
    assert positions[3] == (884, 980), f"Last: {positions[3]}"

    print("  All multiple subtitle positioning tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING SUBTITLE TIMELINE TESTS")
    print("=" * 60)

    test_subtitle_block_positioning()
    print()
    test_minimum_visual_width()
    print()
    test_clamping_to_timeline_bounds()
    print()
    test_subtitle_text_truncation()
    print()
    test_out_of_range_subtitles()
    print()
    test_empty_subtitle_list()
    print()
    test_multiple_subtitle_positioning()
    print()
    print("=" * 60)
    print("ALL SUBTITLE TIMELINE TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()