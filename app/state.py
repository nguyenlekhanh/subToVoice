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

        # PLAN 12 composed timeline audio.
        self.composed_audio_path = None  # composed timeline WAV path
        self.composed_audio_duration_s = None  # composed duration in seconds
        self.composed_audio_request_id = None  # request that produced it

        # PLAN 13 final MP4 export.
        self.final_mp4_path = None  # exported MP4 path
        self.final_mp4_request_id = None  # export request that produced it
        self.final_mp4_duration_s = None  # exported duration in seconds

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
        self.clear_final_mp4()

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
        self.clear_composed_audio()
        self.clear_final_mp4()

    def invalidate_subtitle_audio(self, subtitle_index):
        """Drop the generated WAV mapping for one edited subtitle.

        Generated audio must never silently count as valid after its
        subtitle's text or timing changed.
        """
        self.subtitle_audio_paths.pop(subtitle_index, None)
        self.subtitle_audio_errors.pop(subtitle_index, None)
        self.clear_composed_audio()

    def clear_composed_audio(self):
        """Forget the composed timeline WAV (inputs changed or stale)."""
        self.composed_audio_path = None
        self.composed_audio_duration_s = None
        self.composed_audio_request_id = None
        self.clear_final_mp4()

    def clear_final_mp4(self):
        """Forget the exported MP4 (any upstream input changed)."""
        self.final_mp4_path = None
        self.final_mp4_request_id = None
        self.final_mp4_duration_s = None