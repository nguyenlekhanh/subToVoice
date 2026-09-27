"""
Video Service - Video metadata reading and first frame extraction
"""
import json
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class VideoMetadata:
    """Video metadata container"""
    path: str
    width: int
    height: int
    fps: float
    frame_count: Optional[int]
    duration_ms: int
    has_audio: bool
    first_frame_path: Optional[str] = None


class VideoLoadError(Exception):
    """Raised when video loading fails"""
    pass


class VideoService:
    """Service for video metadata reading and frame extraction"""

    def __init__(self):
        self._ffmpeg_path = shutil.which("ffmpeg")
        self._ffprobe_path = shutil.which("ffprobe")

    def check_ffmpeg(self) -> tuple[bool, str]:
        """
        Check if FFmpeg and FFprobe are available.

        Returns:
            Tuple of (available, error_message)
        """
        if not self._ffmpeg_path:
            return False, "FFmpeg was not found. Please make sure FFmpeg is installed and available in PATH."
        if not self._ffprobe_path:
            return False, "FFprobe was not found. Please make sure FFmpeg is installed and available in PATH."
        return True, ""

    def _run_ffprobe(self, file_path: str) -> dict:
        """Run ffprobe and return parsed JSON output"""
        if not self._ffprobe_path:
            raise VideoLoadError("FFprobe not available")

        cmd = [
            self._ffprobe_path,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            file_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8',
                errors='replace'
            )
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise VideoLoadError(f"FFprobe failed: {e.stderr.strip()}")
        except json.JSONDecodeError as e:
            raise VideoLoadError(f"Failed to parse FFprobe output: {e}")
        except FileNotFoundError:
            raise VideoLoadError("FFprobe executable not found")

    @staticmethod
    def parse_fps(fps_str: str) -> float:
        """
        Parse FPS string which may be a rational like "30000/1001" or integer like "30/1".

        Args:
            fps_str: FPS string from ffprobe

        Returns:
            FPS as float
        """
        if '/' in fps_str:
            num, den = fps_str.split('/')
            try:
                return float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                return 0.0
        try:
            return float(fps_str)
        except ValueError:
            return 0.0

    @staticmethod
    def parse_duration(duration_str: Optional[str]) -> int:
        """
        Parse duration string to milliseconds.

        Args:
            duration_str: Duration in seconds as string (e.g., "10.523")

        Returns:
            Duration in milliseconds, or 0 if invalid
        """
        if not duration_str:
            return 0
        try:
            seconds = float(duration_str)
            return int(seconds * 1000)
        except ValueError:
            return 0

    def load_video_metadata(self, file_path: str) -> VideoMetadata:
        """
        Load video metadata using ffprobe.

        Args:
            file_path: Path to video file

        Returns:
            VideoMetadata object

        Raises:
            VideoLoadError: If metadata cannot be read
        """
        probe_data = self._run_ffprobe(file_path)

        # Find video stream
        video_stream = None
        audio_stream = None

        for stream in probe_data.get("streams", []):
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = stream

        if not video_stream:
            raise VideoLoadError("No video stream found in file")

        # Extract video properties
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        if width <= 0 or height <= 0:
            raise VideoLoadError("Invalid video dimensions")

        # Parse FPS
        fps_str = video_stream.get("r_frame_rate", "0/1")
        fps = self.parse_fps(fps_str)

        # Parse frame count
        frame_count = None
        nb_frames = video_stream.get("nb_frames")
        if nb_frames and nb_frames != "N/A":
            try:
                frame_count = int(nb_frames)
            except ValueError:
                pass

        # Parse duration - prefer stream duration, fallback to format duration
        duration_ms = 0
        stream_duration = video_stream.get("duration")
        if stream_duration:
            duration_ms = self.parse_duration(stream_duration)

        if duration_ms == 0:
            format_duration = probe_data.get("format", {}).get("duration")
            if format_duration:
                duration_ms = self.parse_duration(format_duration)

        # Audio detection
        has_audio = audio_stream is not None

        return VideoMetadata(
            path=file_path,
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            duration_ms=duration_ms,
            has_audio=has_audio,
            first_frame_path=None
        )

    def extract_first_frame(self, file_path: str, output_path: str) -> bool:
        """
        Extract the first frame of the video using FFmpeg.

        Args:
            file_path: Path to input video
            output_path: Path to save the frame (PNG)

        Returns:
            True if successful, False otherwise
        """
        if not self._ffmpeg_path:
            raise VideoLoadError("FFmpeg not available")

        cmd = [
            self._ffmpeg_path,
            "-ss", "0",
            "-i", file_path,
            "-frames:v", "1",
            "-y",  # overwrite output
            output_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8',
                errors='replace'
            )
            return Path(output_path).exists() and Path(output_path).stat().st_size > 0
        except subprocess.CalledProcessError as e:
            raise VideoLoadError(f"FFmpeg frame extraction failed: {e.stderr.strip()}")
        except FileNotFoundError:
            raise VideoLoadError("FFmpeg executable not found")

    def load_video_with_frame(self, file_path: str) -> VideoMetadata:
        """
        Load video metadata and extract first frame in one operation.

        Args:
            file_path: Path to video file

        Returns:
            VideoMetadata with first_frame_path populated

        Raises:
            VideoLoadError: If any step fails
        """
        # Load metadata first
        metadata = self.load_video_metadata(file_path)

        # Extract first frame to temp directory
        temp_dir = Path(tempfile.gettempdir()) / "video_voice_editor"
        temp_dir.mkdir(parents=True, exist_ok=True)

        frame_filename = f"first_frame_{uuid.uuid4().hex[:8]}.png"
        frame_path = temp_dir / frame_filename

        try:
            success = self.extract_first_frame(file_path, str(frame_path))
            if success:
                metadata.first_frame_path = str(frame_path)
            else:
                raise VideoLoadError("First frame extraction produced empty file")
        except VideoLoadError:
            # Clean up on failure
            if frame_path.exists():
                frame_path.unlink(missing_ok=True)
            raise

        return metadata

    def extract_frame_at_timestamp(self, file_path: str, timestamp_ms: int, output_path: str) -> bool:
        """
        Extract a frame at a specific timestamp using FFmpeg.

        Args:
            file_path: Path to input video
            timestamp_ms: Timestamp in milliseconds
            output_path: Path to save the frame (PNG)

        Returns:
            True if successful, False otherwise
        """
        if not self._ffmpeg_path:
            raise VideoLoadError("FFmpeg not available")

        # Convert milliseconds to HH:MM:SS.mmm format for ffmpeg -ss
        seconds = timestamp_ms / 1000.0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        timestamp_str = f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

        # Use -ss before -i for faster seeking
        cmd = [
            self._ffmpeg_path,
            "-ss", timestamp_str,
            "-i", file_path,
            "-frames:v", "1",
            "-y",  # overwrite output
            output_path
        ]
        
        print(f"[DEBUG] FFMPEG CMD: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8',
                errors='replace'
            )
            success = Path(output_path).exists() and Path(output_path).stat().st_size > 0
            print(f"[DEBUG] FFMPEG SUCCESS - output={output_path}, size={Path(output_path).stat().st_size if success else 0}")
            return success
        except subprocess.CalledProcessError as e:
            print(f"[DEBUG] FFMPEG ERROR - returncode={e.returncode}, stderr={e.stderr}")
            raise VideoLoadError(f"FFmpeg frame extraction failed: {e.stderr.strip()}")
        except FileNotFoundError:
            print(f"[DEBUG] FFMPEG NOT FOUND")
            raise VideoLoadError("FFmpeg executable not found")