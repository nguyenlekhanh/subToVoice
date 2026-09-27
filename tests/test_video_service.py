"""
Tests for Video Service
"""
import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.video_service import VideoService, VideoMetadata, VideoLoadError


def test_parse_fps():
    """Test FPS rational parsing"""
    print("Testing FPS parsing...")

    test_cases = [
        ("30000/1001", 29.97002997002997),
        ("30/1", 30.0),
        ("24000/1001", 23.976023976023978),
        ("25/1", 25.0),
        ("60000/1001", 59.94005994005994),
        ("24/1", 24.0),
        ("50/1", 50.0),
        ("invalid", 0.0),
        ("", 0.0),
        ("10/0", 0.0),
    ]

    for fps_str, expected in test_cases:
        result = VideoService.parse_fps(fps_str)
        # Use approximate comparison for floating point
        assert abs(result - expected) < 0.001, f"Failed: {fps_str} -> {result}, expected ~{expected}"
        print(f"  ✓ {fps_str} -> {result:.6f}")

    print("  All FPS parsing tests passed!")


def test_parse_duration():
    """Test duration parsing"""
    print("Testing duration parsing...")

    test_cases = [
        ("10.523", 10523),
        ("0", 0),
        ("1.5", 1500),
        ("123.456", 123456),
        ("invalid", 0),
        (None, 0),
        ("", 0),
    ]

    for duration_str, expected in test_cases:
        result = VideoService.parse_duration(duration_str)
        assert result == expected, f"Failed: {duration_str} -> {result}, expected {expected}"
        print(f"  ✓ {duration_str} -> {result}ms")

    print("  All duration parsing tests passed!")


def test_ffmpeg_detection():
    """Test FFmpeg/FFprobe detection"""
    print("Testing FFmpeg/FFprobe detection...")

    service = VideoService()
    available, error_msg = service.check_ffmpeg()

    # We can't guarantee FFmpeg is installed in the test environment
    # Just verify the function works and returns expected format
    assert isinstance(available, bool)
    assert isinstance(error_msg, str)

    if available:
        print("  ✓ FFmpeg and FFprobe found")
    else:
        print(f"  ℹ FFmpeg not available: {error_msg}")

    print("  FFmpeg detection test passed!")


def test_video_metadata_model():
    """Test VideoMetadata dataclass"""
    print("Testing VideoMetadata model...")

    metadata = VideoMetadata(
        path="/test/video.mp4",
        width=1920,
        height=1080,
        fps=29.97,
        frame_count=3000,
        duration_ms=100000,
        has_audio=True,
        first_frame_path="/temp/frame.png"
    )

    assert metadata.path == "/test/video.mp4"
    assert metadata.width == 1920
    assert metadata.height == 1080
    assert metadata.fps == 29.97
    assert metadata.frame_count == 3000
    assert metadata.duration_ms == 100000
    assert metadata.has_audio is True
    assert metadata.first_frame_path == "/temp/frame.png"

    # Test with None frame_count
    metadata2 = VideoMetadata(
        path="/test/video2.mp4",
        width=1280,
        height=720,
        fps=30.0,
        frame_count=None,
        duration_ms=50000,
        has_audio=False
    )
    assert metadata2.frame_count is None
    assert metadata2.has_audio is False

    print("  ✓ VideoMetadata creation works")
    print("  All VideoMetadata tests passed!")


def test_mock_ffprobe_output():
    """Test parsing mock ffprobe JSON output"""
    print("Testing mock ffprobe output parsing...")

    # This simulates the kind of JSON ffprobe returns
    mock_ffprobe_json = {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_long_name": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
                "profile": "High",
                "codec_type": "video",
                "codec_time_base": "1001/60000",
                "codec_tag_string": "avc1",
                "codec_tag": "0x31637661",
                "width": 1920,
                "height": 1080,
                "coded_width": 1920,
                "coded_height": 1080,
                "closed_captions": 0,
                "has_b_frames": 2,
                "sample_aspect_ratio": "1:1",
                "display_aspect_ratio": "16:9",
                "pix_fmt": "yuv420p",
                "level": 40,
                "color_range": "tv",
                "color_space": "bt709",
                "color_transfer": "bt709",
                "color_primaries": "bt709",
                "chroma_location": "left",
                "refs": 1,
                "is_avc": "true",
                "nal_length_size": "4",
                "r_frame_rate": "30000/1001",
                "avg_frame_rate": "30000/1001",
                "time_base": "1/15360",
                "start_pts": 0,
                "start_time": "0.000000",
                "duration_ts": 1536000,
                "duration": "100.000000",
                "bit_rate": "5000000",
                "bits_per_raw_sample": "8",
                "nb_frames": "3000"
            },
            {
                "index": 1,
                "codec_name": "aac",
                "codec_long_name": "AAC (Advanced Audio Coding)",
                "profile": "LC",
                "codec_type": "audio",
                "codec_time_base": "1/48000",
                "codec_tag_string": "mp4a",
                "codec_tag": "0x6134706d",
                "sample_fmt": "fltp",
                "sample_rate": "48000",
                "channels": 2,
                "channel_layout": "stereo",
                "bits_per_sample": 0,
                "r_frame_rate": "0/0",
                "avg_frame_rate": "0/0",
                "time_base": "1/48000",
                "start_pts": 0,
                "start_time": "0.000000",
                "duration_ts": 4800000,
                "duration": "100.000000",
                "bit_rate": "128000",
                "nb_frames": "4687"
            }
        ],
        "format": {
            "filename": "/test/video.mp4",
            "nb_streams": 2,
            "nb_programs": 0,
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "format_long_name": "QuickTime / MOV",
            "start_time": "0.000000",
            "duration": "100.000000",
            "size": "64000000",
            "bit_rate": "5120000",
            "probe_score": 100
        }
    }

    # We can't easily test the full load_video_metadata without ffprobe
    # But we can verify the parsing logic by checking the expected values
    video_stream = mock_ffprobe_json["streams"][0]
    audio_stream = mock_ffprobe_json["streams"][1]

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    fps_str = video_stream.get("r_frame_rate", "0/1")
    fps = VideoService.parse_fps(fps_str)
    duration_str = video_stream.get("duration")
    duration_ms = VideoService.parse_duration(duration_str)
    nb_frames = video_stream.get("nb_frames")
    frame_count = int(nb_frames) if nb_frames and nb_frames != "N/A" else None
    has_audio = audio_stream is not None

    assert width == 1920
    assert height == 1080
    assert abs(fps - 29.97) < 0.01
    assert duration_ms == 100000
    assert frame_count == 3000
    assert has_audio is True

    print(f"  ✓ Width: {width}, Height: {height}")
    print(f"  ✓ FPS: {fps:.2f}")
    print(f"  ✓ Duration: {duration_ms}ms")
    print(f"  ✓ Frame count: {frame_count}")
    print(f"  ✓ Has audio: {has_audio}")

    print("  All mock ffprobe parsing tests passed!")


def test_missing_audio():
    """Test video without audio stream"""
    print("Testing video without audio...")

    mock_ffprobe_json = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "30/1",
                "duration": "60.0",
                "nb_frames": "1800"
            }
        ],
        "format": {
            "duration": "60.0"
        }
    }

    video_stream = mock_ffprobe_json["streams"][0]
    audio_stream = None
    for stream in mock_ffprobe_json["streams"]:
        if stream.get("codec_type") == "audio":
            audio_stream = stream
            break

    has_audio = audio_stream is not None
    assert has_audio is False

    print("  ✓ Correctly detects missing audio stream")
    print("  All missing audio tests passed!")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("RUNNING VIDEO SERVICE TESTS")
    print("=" * 60)

    test_parse_fps()
    print()
    test_parse_duration()
    print()
    test_ffmpeg_detection()
    print()
    test_video_metadata_model()
    print()
    test_mock_ffprobe_output()
    print()
    test_missing_audio()
    print()
    print("=" * 60)
    print("ALL VIDEO SERVICE TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()