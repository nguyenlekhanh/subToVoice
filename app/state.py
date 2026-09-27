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