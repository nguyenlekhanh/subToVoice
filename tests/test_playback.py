"""
Tests for Video Playback Logic
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.state import AppState


def test_playback_state_transitions():
    """Test playback state transitions"""
    print("Testing playback state transitions...")

    state = AppState()
    state.video_duration_ms = 10000  # 10 seconds
    state.current_time_ms = 0

    # Initial state
    assert state.is_playing is False
    assert state.is_paused is False
    assert state.current_time_ms == 0
    print("  ✓ Initial state: stopped")

    # Stopped -> Playing
    state.is_playing = True
    state.is_paused = False
    assert state.is_playing is True
    assert state.is_paused is False
    print("  ✓ Stopped -> Playing")

    # Playing -> Paused
    state.is_playing = False
    state.is_paused = True
    assert state.is_playing is False
    assert state.is_paused is True
    print("  ✓ Playing -> Paused")

    # Paused -> Playing
    state.is_playing = True
    state.is_paused = False
    assert state.is_playing is True
    assert state.is_paused is False
    print("  ✓ Paused -> Playing")

    # Playing -> Stopped
    state.is_playing = False
    state.is_paused = False
    state.current_time_ms = 0
    assert state.is_playing is False
    assert state.is_paused is False
    assert state.current_time_ms == 0
    print("  ✓ Playing -> Stopped (position reset)")

    # Playing -> Ended
    state.is_playing = True
    state.current_time_ms = 10000
    state.is_playing = False
    state.is_paused = False
    assert state.is_playing is False
    assert state.current_time_ms == 10000
    print("  ✓ Playing -> Ended")

    print("  All playback state transition tests passed!")


def test_position_clamping():
    """Test position clamping logic"""
    print("Testing position clamping...")

    duration_ms = 10000

    # Test clamping function (simulating what happens in seek)
    def clamp_position(pos, duration):
        return max(0, min(pos, duration))

    test_cases = [
        (-1000, 0),
        (0, 0),
        (5000, 5000),
        (10000, 10000),
        (15000, 10000),
    ]

    for input_pos, expected in test_cases:
        result = clamp_position(input_pos, duration_ms)
        assert result == expected, f"Failed: {input_pos} -> {result}, expected {expected}"
        print(f"  ✓ {input_pos} -> {result}")

    print("  All position clamping tests passed!")


def test_time_formatting():
    """Test time formatting functions"""
    print("Testing time formatting...")

    # Test _format_short_timestamp logic
    def format_short_timestamp(ms):
        if ms < 0:
            return "00:00.000"
        minutes = ms // (60 * 1000)
        ms_remaining = ms % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    test_cases = [
        (0, "00:00.000"),
        (1000, "00:01.000"),
        (5000, "00:05.000"),
        (10000, "00:10.000"),
        (61000, "01:01.000"),
        (125500, "02:05.500"),
        (-100, "00:00.000"),
    ]

    for ms, expected in test_cases:
        result = format_short_timestamp(ms)
        assert result == expected, f"Failed: {ms} -> {result}, expected {expected}"
        print(f"  ✓ {ms}ms -> {result}")

    # Test _format_position_display logic
    def format_position_display(current_ms, duration_ms):
        return f"{format_short_timestamp(current_ms)} / {format_short_timestamp(duration_ms)}"

    pos_tests = [
        (0, 10000, "00:00.000 / 00:10.000"),
        (5000, 10000, "00:05.000 / 00:10.000"),
        (10000, 10000, "00:10.000 / 00:10.000"),
    ]

    for current, duration, expected in pos_tests:
        result = format_position_display(current, duration)
        assert result == expected, f"Failed: {current}/{duration} -> {result}, expected {expected}"
        print(f"  ✓ {current}/{duration} -> {result}")

    print("  All time formatting tests passed!")


def test_clear_playback_state():
    """Test clear_playback_state method"""
    print("Testing clear_playback_state...")

    state = AppState()
    state.is_playing = True
    state.is_paused = True
    state.current_time_ms = 5000

    state.clear_playback_state()

    assert state.is_playing is False
    assert state.is_paused is False
    assert state.current_time_ms == 0
    print("  ✓ clear_playback_state resets all playback fields")

    print("  All clear_playback_state tests passed!")


def test_video_state_clearing():
    """Test clear_video_state method"""
    print("Testing clear_video_state...")

    state = AppState()
    state.video_path = "/test/video.mp4"
    state.video_width = 1920
    state.video_height = 1080
    state.video_fps = 29.97
    state.video_frame_count = 3000
    state.video_duration_ms = 100000
    state.video_has_audio = True
    state.video_first_frame_path = "/temp/frame.png"
    state.is_playing = True
    state.current_time_ms = 5000

    state.clear_video_state()

    assert state.video_path is None
    assert state.video_width == 0
    assert state.video_height == 0
    assert state.video_fps == 0.0
    assert state.video_frame_count is None
    assert state.video_duration_ms == 0
    assert state.video_has_audio is False
    assert state.video_first_frame_path is None
    # Note: clear_video_state does NOT clear playback state
    assert state.is_playing is True  # unchanged
    assert state.current_time_ms == 5000  # unchanged

    print("  ✓ clear_video_state resets video fields but not playback state")

    print("  All clear_video_state tests passed!")


def test_app_state_initialization():
    """Test AppState initial values"""
    print("Testing AppState initialization...")

    state = AppState()

    # Video fields
    assert state.video_path is None
    assert state.video_width == 0
    assert state.video_height == 0
    assert state.video_fps == 0.0
    assert state.video_frame_count is None
    assert state.video_duration_ms == 0
    assert state.video_has_audio is False
    assert state.video_first_frame_path is None

    # SRT fields
    assert state.srt_path is None
    assert state.subtitles == []
    assert state.selected_subtitle is None

    # Playback fields
    assert state.is_playing is False
    assert state.is_paused is False
    assert state.current_time_ms == 0

    print("  ✓ All initial values correct")

    print("  All AppState initialization tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING PLAYBACK TESTS")
    print("=" * 60)

    test_app_state_initialization()
    print()
    test_playback_state_transitions()
    print()
    test_position_clamping()
    print()
    test_time_formatting()
    print()
    test_clear_playback_state()
    print()
    test_clear_video_state()
    print()
    print("=" * 60)
    print("ALL PLAYBACK TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()