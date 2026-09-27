"""
Application state management
"""


class AppState:
    """Simple application state object"""

    def __init__(self):
        self.video_path = None
        self.video_width = 0
        self.video_height = 0
        self.video_fps = 0.0
        self.video_frame_count = None
        self.video_duration_ms = 0
        self.video_has_audio = False
        self.video_first_frame_path = None

        self.srt_path = None
        self.subtitles = []
        self.selected_subtitle = None
        self.selected_voice = None
        self.is_playing = False
        self.is_paused = False
        self.current_time_ms = 0

        # PLAN 11 batch voice generation (for PLAN 12 composition).
        self.subtitle_audio_paths = {}  # subtitle index -> generated WAV path
        self.subtitle_audio_errors = {}  # subtitle index -> error message
        self.audio_voice_name = None  # voice used for the stored WAVs
        self.audio_batch_id = None  # batch that produced the stored WAVs

    def clear_video_state(self):
        """Clear video-related state"""
        self.video_path = None
        self.video_width = 0
        self.video_height = 0
        self.video_fps = 0.0
        self.video_frame_count = None
        self.video_duration_ms = 0
        self.video_has_audio = False
        self.video_first_frame_path = None

    def clear_playback_state(self):
        """Clear playback-related state"""
        self.is_playing = False
        self.is_paused = False
        self.current_time_ms = 0

    def clear_audio_mappings(self):
        """Forget all batch-generated WAV mappings (e.g. new SRT loaded)."""
        self.subtitle_audio_paths = {}
        self.subtitle_audio_errors = {}
        self.audio_voice_name = None
        self.audio_batch_id = None

    def invalidate_subtitle_audio(self, subtitle_index):
        """Drop the generated WAV mapping for one edited subtitle.

        Generated audio must never silently count as valid after its
        subtitle's text or timing changed.
        """
        self.subtitle_audio_paths.pop(subtitle_index, None)
        self.subtitle_audio_errors.pop(subtitle_index, None)