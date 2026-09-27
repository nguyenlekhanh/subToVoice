"""
Video Voice Editor - Main GUI Application
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import hashlib
import threading
import queue
import time
import tempfile
import uuid
import wave
from pathlib import Path

from app.state import AppState
from services.piper_service import (
    PiperService,
    VoicePreviewResult,
    batch_output_path,
    generate_batch_voices,
    wav_info,
)
from services.srt_service import SRTService, SRTParseError
from services.video_service import VideoService, VideoLoadError


class VideoVoiceEditorApp:
    """Main application window"""

    def __init__(self):
        self.root = tk.Tk()
        self.state = AppState()
        self.video_service = VideoService()
        self.piper_service = PiperService()
        self._piper_load_thread = None
        self._piper_result_queue = queue.Queue()
        self._piper_voices = []
        # PLAN 10 voice preview state (worker/queue/root.after pattern)
        self._preview_thread = None
        self._preview_result_queue = queue.Queue()
        self._preview_generating = False
        self._preview_request_id = None
        self.btn_preview_voice = None
        # PLAN 11 batch voice generation state
        self._batch_thread = None
        self._batch_result_queue = queue.Queue()
        self._batch_generating = False
        self._batch_request_id = None
        self._batch_cancel_event = None
        self.btn_generate_all = None
        self.btn_cancel_batch = None
        self.batch_progress = None
        self._srt_load_thread = None
        self._srt_result_queue = queue.Queue()
        self._batch_insert_index = 0
        self._batch_insert_subtitles = []
        self._video_load_thread = None
        self._video_result_queue = queue.Queue()
        self._preview_image = None  # Keep reference to prevent garbage collection
        
        # Playback state
        self._playback_thread = None
        self._playback_stop_event = threading.Event()
        self._playback_result_queue = queue.Queue()
        self._playback_start_time = 0.0
        self._playback_paused_time = 0.0
        self._seek_scale_updating = False
        
        # Subtitle timeline state
        self._subtitle_block_ids = {}  # subtitle index -> (rect_id, text_id)
        self._selected_subtitle_index = None
        self._drag_subtitle_index = None
        self._drag_start_x = None
        self._drag_start_left_x = None
        self._drag_duration = None
        self._drag_subtitle = None
        self._drag_moved = False

        # Treeview in-place editing state
        self._edit_entry = None
        self._edit_var = None
        self._edit_item = None
        self._edit_col_name = None
        self._edit_col_idx = None
        
        self._setup_window()
        self._create_ui()
        self._check_srt_result()
        self._check_video_result()
        self._check_playback_result()
        self._check_piper_result()

    def _setup_window(self):
        """Configure main window"""
        self.root.title("Video Voice Editor")
        self.root.geometry("1200x800")
        self.root.minsize(800, 600)

    def _create_ui(self):
        """Create the main UI layout"""
        # Main container
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 1. Top toolbar
        self._create_toolbar(main_frame)

        # Content area (split into left and right)
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Left panel: Video preview + Timeline
        left_panel = ttk.Frame(content_frame)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 2. Video preview area
        self._create_video_preview(left_panel)

        # 3. Video metadata display
        self._create_video_metadata(left_panel)

        # 4. Playback controls
        self._create_playback_controls(left_panel)

        # 5. Timeline area
        self._create_timeline(left_panel)

        # Right panel: Subtitle area
        right_panel = ttk.Frame(content_frame, width=400)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))
        right_panel.pack_propagate(False)

        # 6. Subtitle area (Treeview)
        self._create_subtitle_area(right_panel)

        # 8. Status bar (must exist before voice area starts Piper discovery)
        self._create_status_bar(main_frame)

        # 7. Piper voice selection
        self._create_voice_area(right_panel)

    def _create_toolbar(self, parent):
        """Create top toolbar with buttons"""
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        self.btn_load_video = ttk.Button(toolbar, text="Load Video", command=self._on_load_video)
        self.btn_load_video.pack(side=tk.LEFT, padx=2)

        self.btn_load_srt = ttk.Button(toolbar, text="Load SRT", command=self._on_load_srt)
        self.btn_load_srt.pack(side=tk.LEFT, padx=2)

        # Playback buttons in toolbar
        self.btn_play = ttk.Button(toolbar, text="Play", command=self._on_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, padx=2)

        self.btn_pause = ttk.Button(toolbar, text="Pause", command=self._on_pause, state=tk.DISABLED)
        self.btn_pause.pack(side=tk.LEFT, padx=2)

        self.btn_stop = ttk.Button(toolbar, text="Stop", command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=2)

        self.btn_save_srt = ttk.Button(toolbar, text="Save SRT", command=self._on_save_srt)
        self.btn_save_srt.pack(side=tk.LEFT, padx=2)

        self.btn_generate_mp4 = ttk.Button(toolbar, text="Generate Final MP4", command=self._on_generate_mp4)
        self.btn_generate_mp4.pack(side=tk.LEFT, padx=2)

    def _create_video_preview(self, parent):
        """Create video preview area with constrained size"""
        # Outer container with fixed maximum height to prevent layout explosion
        self.video_preview_container = ttk.LabelFrame(parent, text="Video Preview")
        self.video_preview_container.pack(fill=tk.BOTH, expand=False, pady=(0, 5))
        # Prevent child widgets from resizing the container
        self.video_preview_container.pack_propagate(False)
        # Set a reasonable maximum height for the preview area (~70% of previous 550)
        self.video_preview_container.configure(height=385)

        # Inner frame for the image label (allows centering)
        preview_inner = ttk.Frame(self.video_preview_container)
        preview_inner.pack(fill=tk.BOTH, expand=True)

        self.video_preview_label = ttk.Label(
            preview_inner,
            text="Video Preview",
            font=("TkDefaultFont", 14),
            anchor=tk.CENTER
        )
        self.video_preview_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Bind configure event to handle resize
        self.video_preview_label.bind("<Configure>", self._on_preview_resize)

    def _create_video_metadata(self, parent):
        """Create video metadata display area"""
        frame = ttk.LabelFrame(parent, text="Video Info")
        frame.pack(fill=tk.X, pady=(0, 5))

        # Grid layout for metadata
        info_frame = ttk.Frame(frame)
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        # Row 1: Resolution and FPS
        ttk.Label(info_frame, text="Resolution:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.lbl_resolution = ttk.Label(info_frame, text="—")
        self.lbl_resolution.grid(row=0, column=1, sticky=tk.W, padx=(0, 20))

        ttk.Label(info_frame, text="FPS:").grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
        self.lbl_fps = ttk.Label(info_frame, text="—")
        self.lbl_fps.grid(row=0, column=3, sticky=tk.W, padx=(0, 20))

        # Row 2: Duration and Frames
        ttk.Label(info_frame, text="Duration:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        self.lbl_duration = ttk.Label(info_frame, text="—")
        self.lbl_duration.grid(row=1, column=1, sticky=tk.W, padx=(0, 20))

        ttk.Label(info_frame, text="Frames:").grid(row=1, column=2, sticky=tk.W, padx=(0, 5))
        self.lbl_frames = ttk.Label(info_frame, text="—")
        self.lbl_frames.grid(row=1, column=3, sticky=tk.W, padx=(0, 20))

        # Row 3: Audio
        ttk.Label(info_frame, text="Audio:").grid(row=2, column=0, sticky=tk.W, padx=(0, 5))
        self.lbl_audio = ttk.Label(info_frame, text="—")
        self.lbl_audio.grid(row=2, column=1, sticky=tk.W)

        # Configure column weights
        info_frame.columnconfigure(1, weight=1)
        info_frame.columnconfigure(3, weight=1)

    def _create_playback_controls(self, parent):
        """Create playback controls: position display and seek bar"""
        frame = ttk.LabelFrame(parent, text="Playback")
        frame.pack(fill=tk.X, pady=(0, 5))

        # Position display
        pos_frame = ttk.Frame(frame)
        pos_frame.pack(fill=tk.X, padx=10, pady=5)

        self.lbl_position = ttk.Label(pos_frame, text="00:00.000 / 00:00.000", font=("TkDefaultFont", 10))
        self.lbl_position.pack(side=tk.LEFT)

        # Seek scale
        scale_frame = ttk.Frame(frame)
        scale_frame.pack(fill=tk.X, padx=10, pady=5)

        self.seek_var = tk.IntVar(value=0)
        self.seek_scale = ttk.Scale(
            scale_frame,
            from_=0,
            to=1000,
            orient=tk.HORIZONTAL,
            variable=self.seek_var,
            command=self._on_seek_drag
        )
        self.seek_scale.pack(fill=tk.X, expand=True)

        # Bind mouse release for seek
        self.seek_scale.bind("<ButtonRelease-1>", self._on_seek_release)

    def _create_timeline(self, parent):
        """Create timeline with Canvas, time markers, and playhead"""
        frame = ttk.LabelFrame(parent, text="Timeline")
        frame.pack(fill=tk.X, pady=(0, 5))

        # Timeline height
        self._timeline_height = 100
        self._timeline_margin_left = 50
        self._timeline_margin_right = 20
        self._timeline_margin_top = 10
        self._timeline_margin_bottom = 30

        # Canvas for timeline
        self.timeline_canvas = tk.Canvas(
            frame,
            height=self._timeline_height,
            bg="#f0f0f0",
            highlightthickness=1,
            highlightbackground="#ccc"
        )
        self.timeline_canvas.pack(fill=tk.X, padx=5, pady=5)

        # Timeline state
        self._timeline_playhead_id = None
        self._timeline_marker_ids = []
        self._timeline_label_ids = []

        # Bind events. There is exactly one widget-level press handler.
        self.timeline_canvas.bind("<ButtonPress-1>", self._on_timeline_mouse_press)
        self.timeline_canvas.bind("<Configure>", self._on_timeline_resize)

        # Draw initial empty timeline
        self._draw_timeline()

    def _draw_timeline(self):
        """Draw static timeline elements: background, markers, labels, subtitle blocks"""
        self.timeline_canvas.delete("all")
        self._timeline_marker_ids = []
        self._timeline_label_ids = []
        self._subtitle_block_ids = {}

        canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 1000

        duration_ms = self.state.video_duration_ms

        if duration_ms <= 0:
            # No video loaded
            self.timeline_canvas.create_text(
                canvas_width // 2, self._timeline_height // 2,
                text="No video loaded",
                fill="#888",
                font=("TkDefaultFont", 11)
            )
            return

        # Calculate available width for timeline
        available_width = canvas_width - self._timeline_margin_left - self._timeline_margin_right

        # Determine marker interval based on duration
        interval_ms = self._calculate_marker_interval(duration_ms)

        # Draw time markers and labels
        time_ms = 0
        while time_ms <= duration_ms:
            x = self._time_to_x(time_ms, canvas_width)

            # Vertical marker line
            marker_id = self.timeline_canvas.create_line(
                x, self._timeline_margin_top,
                x, self._timeline_height - self._timeline_margin_bottom,
                fill="#999",
                width=1
            )
            self._timeline_marker_ids.append(marker_id)

            # Time label
            label_text = self._format_timeline_time(time_ms)
            label_id = self.timeline_canvas.create_text(
                x, self._timeline_height - self._timeline_margin_bottom + 5,
                text=label_text,
                fill="#666",
                font=("TkDefaultFont", 8),
                anchor=tk.N
            )
            self._timeline_label_ids.append(label_id)

            time_ms += interval_ms

        # Ensure last marker at exact duration if not already drawn
        last_x = self._time_to_x(duration_ms, canvas_width)
        if abs(last_x - self._time_to_x(time_ms - interval_ms, canvas_width)) > 2:
            marker_id = self.timeline_canvas.create_line(
                last_x, self._timeline_margin_top,
                last_x, self._timeline_height - self._timeline_margin_bottom,
                fill="#999",
                width=1
            )
            self._timeline_marker_ids.append(marker_id)

            label_id = self.timeline_canvas.create_text(
                last_x, self._timeline_height - self._timeline_margin_bottom + 5,
                text=self._format_timeline_time(duration_ms),
                fill="#666",
                font=("TkDefaultFont", 8),
                anchor=tk.N
            )
            self._timeline_label_ids.append(label_id)

        # Draw subtitle blocks
        self._draw_subtitle_blocks(canvas_width, duration_ms)

        # Create playhead (initially at 0)
        self._create_playhead(canvas_width)

    def _draw_subtitle_blocks(self, canvas_width: int, duration_ms: int):
        """Draw subtitle blocks on the timeline"""
        if not self.state.subtitles:
            return

        # Calculate vertical positions for subtitle blocks
        # Use two rows if there are overlapping subtitles
        block_height = 28
        top_margin = self._timeline_margin_top
        bottom_margin = self._timeline_margin_bottom
        available_height = self._timeline_height - top_margin - bottom_margin
        
        # Use single row centered in available space
        block_y = top_margin + (available_height - 28) // 2
        
        for sub in self.state.subtitles:
            # Calculate block position
            left_x = self._time_to_x(sub.start_ms, canvas_width)
            right_x = self._time_to_x(sub.end_ms, canvas_width)
            
            # Ensure minimum visual width
            min_width = 8
            if right_x - left_x < min_width:
                right_x = left_x + min_width
            
            # Clamp to timeline bounds
            left_x = max(self._timeline_margin_left, left_x)
            right_x = min(canvas_width - self._timeline_margin_right, right_x)
            
            if left_x >= right_x:
                continue
            
            # Determine block color based on selection
            is_selected = (self._selected_subtitle_index == sub.index)
            if is_selected:
                fill_color = "#3a7bd5"
                outline_color = "#2980b9"
            else:
                fill_color = "#5dade2"
                outline_color = "#3498db"
            
            # Draw rectangle
            rect_id = self.timeline_canvas.create_rectangle(
                left_x, block_y,
                right_x, block_y + 28,
                fill=fill_color,
                outline=outline_color,
                width=1,
                tags=("subtitle_block", f"subtitle_{sub.index}")
            )
            
            # Draw text inside block
            display_text = self._truncate_subtitle_text(sub.text, right_x - left_x)
            text_id = self.timeline_canvas.create_text(
                (left_x + right_x) // 2, block_y + 14,
                text=display_text,
                fill="white",
                font=("TkDefaultFont", 8),
                anchor=tk.CENTER,
                tags=("subtitle_block", f"subtitle_{sub.index}")
            )
            
            # Store block references
            self._subtitle_block_ids[sub.index] = (rect_id, text_id)

    def _truncate_subtitle_text(self, text: str, max_width_px: int) -> str:
        """Truncate subtitle text to fit within block width"""
        if not text:
            return ""
        # Replace newlines with separator
        display_text = text.replace('\n', ' | ')
        # Rough character width estimation (8px per char at font size 8)
        max_chars = max(1, max_width_px // 8)
        if len(display_text) > max_chars:
            return display_text[:max_chars - 3] + "..."
        return display_text

    def _on_subtitle_block_click(self, event, subtitle_index: int):
        """Handle click on subtitle block"""
        # Select the subtitle
        self._select_subtitle_by_index(subtitle_index)
        
        # Don't seek when clicking subtitle block
        # Just select it
        return "break"  # Prevent event propagation to timeline click handler

    def _get_subtitle_index_from_tags(self, tags):
        """Return the numeric subtitle index encoded in Canvas tags, or None."""
        if not tags:
            return None
        for tag in tags:
            if tag == "subtitle_block":
                continue
            if tag.startswith("subtitle_"):
                suffix = tag[len("subtitle_"):]
                if suffix.isdigit():
                    index = int(suffix)
                    if index > 0:
                        return index
        return None

    def _select_subtitle_by_index(self, subtitle_index: int):
        """Select subtitle by index and update both Treeview and timeline"""
        self._selected_subtitle_index = subtitle_index
        
        # Update state
        for sub in self.state.subtitles:
            if sub.index == subtitle_index:
                self.state.selected_subtitle = sub
                break
        
        # Update Treeview selection only when it actually changes.
        current_selection = self.subtitle_tree.selection()
        for item in self.subtitle_tree.get_children():
            item_index = int(self.subtitle_tree.item(item, "values")[0])
            if item_index == subtitle_index:
                if not current_selection or current_selection[0] != item:
                    self.subtitle_tree.selection_set(item)
                    self.subtitle_tree.see(item)
                break
        
        # Update timeline block visual
        self._update_subtitle_block_selection()

    def _update_subtitle_block_selection(self):
        """Update visual selection state of subtitle blocks"""
        for idx, (rect_id, text_id) in self._subtitle_block_ids.items():
            is_selected = (idx == self._selected_subtitle_index)
            if is_selected:
                self.timeline_canvas.itemconfig(rect_id, fill="#3a7bd5", outline="#2980b9")
            else:
                self.timeline_canvas.itemconfig(rect_id, fill="#5dade2", outline="#3498db")
        
        # Ensure playhead is on top
        if self._timeline_playhead_id is not None:
            self.timeline_canvas.tag_raise(self._timeline_playhead_id)
        if hasattr(self, '_timeline_playhead_triangle_id') and self._timeline_playhead_triangle_id is not None:
            self.timeline_canvas.tag_raise(self._timeline_playhead_triangle_id)

    def _calculate_marker_interval(self, duration_ms: int) -> int:
        """Calculate appropriate time marker interval based on duration"""
        duration_s = duration_ms / 1000.0

        if duration_s <= 60:
            return 5000  # 5 seconds
        elif duration_s <= 300:
            return 10000  # 10 seconds
        elif duration_s <= 600:
            return 30000  # 30 seconds
        elif duration_s <= 1800:
            return 60000  # 1 minute
        elif duration_s <= 3600:
            return 120000  # 2 minutes
        else:
            return 300000  # 5 minutes

    def _format_timeline_time(self, ms: int) -> str:
        """Format time for timeline labels (MM:SS or HH:MM:SS)"""
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

    def _time_to_x(self, time_ms: int, canvas_width: int = None) -> int:
        """Convert time in milliseconds to Canvas x coordinate"""
        if canvas_width is None:
            canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 1000

        if self.state.video_duration_ms <= 0:
            return self._timeline_margin_left

        # Clamp time
        time_ms = max(0, min(time_ms, self.state.video_duration_ms))

        available_width = canvas_width - self._timeline_margin_left - self._timeline_margin_right
        x = self._timeline_margin_left + int((time_ms / self.state.video_duration_ms) * available_width)
        return x

    def _x_to_time(self, x: int, canvas_width: int = None) -> int:
        """Convert Canvas x coordinate to time in milliseconds"""
        if canvas_width is None:
            canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 1000

        if self.state.video_duration_ms <= 0:
            return 0

        available_width = canvas_width - self._timeline_margin_left - self._timeline_margin_right

        # Clamp x to valid range
        x = max(self._timeline_margin_left, min(x, canvas_width - self._timeline_margin_right))

        ratio = (x - self._timeline_margin_left) / available_width
        time_ms = int(ratio * self.state.video_duration_ms)
        return max(0, min(time_ms, self.state.video_duration_ms))

    def _create_playhead(self, canvas_width: int = None):
        """Create the playhead Canvas items (vertical line + triangle)"""
        if self._timeline_playhead_id is not None:
            self.timeline_canvas.delete(self._timeline_playhead_id)
        if hasattr(self, '_timeline_playhead_triangle_id') and self._timeline_playhead_triangle_id is not None:
            self.timeline_canvas.delete(self._timeline_playhead_triangle_id)

        x = self._time_to_x(self.state.current_time_ms, canvas_width)

        # Vertical line
        self._timeline_playhead_id = self.timeline_canvas.create_line(
            x, self._timeline_margin_top,
            x, self._timeline_height - self._timeline_margin_bottom,
            fill="#e74c3c",
            width=2
        )

        # Triangle at top
        triangle_size = 8
        self._timeline_playhead_triangle_id = self.timeline_canvas.create_polygon(
            x, self._timeline_margin_top - 5,
            x - triangle_size // 2, self._timeline_margin_top + triangle_size - 5,
            x + triangle_size // 2, self._timeline_margin_top + triangle_size - 5,
            fill="#e74c3c",
            outline="#c0392b"
        )

        # Bring to front
        self.timeline_canvas.tag_raise(self._timeline_playhead_id)
        self.timeline_canvas.tag_raise(self._timeline_playhead_triangle_id)

    def _update_playhead_position(self):
        """Update playhead position based on current_time_ms"""
        if self._timeline_playhead_id is None:
            return

        canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            return

        x = self._time_to_x(self.state.current_time_ms, canvas_width)

        # Update playhead line
        self.timeline_canvas.coords(
            self._timeline_playhead_id,
            x, self._timeline_margin_top,
            x, self._timeline_height - self._timeline_margin_bottom
        )

        # Update playhead triangle
        triangle_size = 8
        self.timeline_canvas.coords(
            self._timeline_playhead_triangle_id,
            x, self._timeline_margin_top - 5,
            x - triangle_size // 2, self._timeline_margin_top + triangle_size - 5,
            x + triangle_size // 2, self._timeline_margin_top + triangle_size - 5
        )

    def _on_timeline_click(self, event):
        """Handle click on timeline - seek to clicked position"""
        if self.state.video_duration_ms <= 0:
            return

        # Check if click is on a subtitle block
        item = self.timeline_canvas.find_closest(event.x, event.y)
        if item:
            if self._get_subtitle_index_from_tags(self.timeline_canvas.gettags(item[0])) is not None:
                # Click was on a subtitle block, don't seek
                return

        # Convert click x to time
        clicked_time_ms = self._x_to_time(event.x)

        # Update position
        self.state.current_time_ms = clicked_time_ms
        self._update_position_display()
        self._update_playhead_position()

        # Use existing seek mechanism
        self._seek_to_position(clicked_time_ms)

    def _on_timeline_mouse_press(self, event):
        """Handle all Timeline mouse presses: subtitle selection/drag or empty-area seek."""
        if self.state.video_duration_ms <= 0:
            return

        # Reset drag state for each new press.
        self._drag_subtitle_index = None
        self._drag_subtitle = None
        self._drag_start_x = None
        self._drag_start_left_x = None
        self._drag_duration = None
        self._drag_moved = False

        # Check if press is on a subtitle block or its text.
        item = self.timeline_canvas.find_closest(event.x, event.y)
        subtitle_index = None
        if item:
            subtitle_index = self._get_subtitle_index_from_tags(
                self.timeline_canvas.gettags(item[0])
            )
        
        if subtitle_index is None:
            # Empty Timeline press: use the existing seek behavior.
            self._on_timeline_click(event)
            return
        
        # Subtitle press: select first, then arm a possible drag.
        self._select_subtitle_by_index(subtitle_index)
        block_ids = self._subtitle_block_ids.get(subtitle_index)
        if block_ids is None:
            return
        block_coords = self.timeline_canvas.coords(block_ids[0])
        if not block_coords or len(block_coords) < 4:
            return
        
        self._drag_subtitle_index = subtitle_index
        self._drag_start_x = event.x
        self._drag_start_left_x = block_coords[0]
        self._drag_duration = self._get_subtitle_duration(subtitle_index)
        
        # Find subtitle in state
        self._drag_subtitle = None
        for sub in self.state.subtitles:
            if sub.index == subtitle_index:
                self._drag_subtitle = sub
                break

    def _on_timeline_mouse_drag(self, event):
        """Handle mouse drag on timeline - move subtitle block"""
        if self._drag_subtitle_index is None:
            return
        
        if not self._drag_subtitle:
            return
        
        # A stationary press is a click, not a drag.
        if self._drag_start_x is None:
            return
        if not self._drag_moved and abs(event.x - self._drag_start_x) < 4:
            return
        self._drag_moved = True
        
        # Calculate block width in pixels
        canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 1000
        
        # Calculate block width in pixels based on duration
        block_width = self._time_to_x(self._drag_subtitle.end_ms, canvas_width) - self._time_to_x(self._drag_subtitle.start_ms, canvas_width)
        if block_width < 8:
            block_width = 8
        
        # Calculate new position
        delta_x = event.x - self._drag_start_x
        new_left_x = self._drag_start_left_x + delta_x
        
        # Clamp to timeline bounds
        min_left = self._timeline_margin_left
        max_left = canvas_width - self._timeline_margin_right - block_width
        
        if max_left < min_left:
            max_left = min_left
        
        new_left_x = max(min_left, min(new_left_x, max_left))
        new_right_x = new_left_x + block_width
        
        # Update block position visually
        block_ids = self._subtitle_block_ids.get(self._drag_subtitle_index)
        if block_ids is None:
            return
        rect_id, text_id = block_ids
        block_height = 28
        top_margin = self._timeline_margin_top
        bottom_margin = self._timeline_margin_bottom
        available_height = self._timeline_height - top_margin - self._timeline_margin_bottom
        block_y = top_margin + (available_height - 28) // 2
        
        self.timeline_canvas.coords(
            rect_id,
            new_left_x, block_y,
            new_right_x, block_y + 28
        )
        # Update text position
        self.timeline_canvas.coords(
            text_id,
            (new_left_x + new_right_x) // 2,
            block_y + 14
        )

    def _on_timeline_mouse_release(self, event):
        """Handle mouse release on timeline - finalize drag"""
        if self._drag_subtitle_index is None:
            self._drag_moved = False
            return
        
        if not self._drag_subtitle:
            self._drag_subtitle_index = None
            self._drag_subtitle = None
            self._drag_start_x = None
            self._drag_start_left_x = None
            self._drag_duration = None
            self._drag_moved = False
            return
        
        if not self._drag_moved:
            # A stationary press was only a selection click.
            self._drag_subtitle_index = None
            self._drag_subtitle = None
            self._drag_start_x = None
            self._drag_start_left_x = None
            self._drag_duration = None
            self._drag_moved = False
            return
        
        # Calculate new position in milliseconds
        canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 1000
        
        block_ids = self._subtitle_block_ids.get(self._drag_subtitle_index)
        if block_ids is None:
            self._drag_subtitle_index = None
            self._drag_subtitle = None
            self._drag_start_x = None
            self._drag_start_left_x = None
            self._drag_duration = None
            self._drag_moved = False
            return
        rect_id, text_id = block_ids
        coords = self.timeline_canvas.coords(rect_id)
        if not coords or len(coords) < 4:
            self._drag_subtitle_index = None
            self._drag_subtitle = None
            self._drag_start_x = None
            self._drag_start_left_x = None
            self._drag_duration = None
            self._drag_moved = False
            return
        
        new_left_x = coords[0]
        new_right_x = coords[2]
        
        # Convert to milliseconds
        new_start_ms = self._x_to_time(new_left_x)
        new_end_ms = self._x_to_time(new_right_x)
        
        # Update subtitle timing
        old_start = self._drag_subtitle.start_ms
        old_end = self._drag_subtitle.end_ms
        
        try:
            if new_start_ms < 0:
                new_start_ms = 0
                new_end_ms = new_start_ms + (old_end - old_start)
            if new_end_ms > self.state.video_duration_ms and self.state.video_duration_ms > 0:
                new_end_ms = self.state.video_duration_ms
                new_start_ms = new_end_ms - (old_end - old_start)
            
            if new_start_ms < 0:
                new_start_ms = 0
                new_end_ms = new_start_ms + (old_end - old_start)
            if new_end_ms > self.state.video_duration_ms and self.state.video_duration_ms > 0:
                new_end_ms = self.state.video_duration_ms
                new_start_ms = new_end_ms - (old_end - old_start)
            
            # Ensure valid
            if new_start_ms >= 0 and new_end_ms > new_start_ms:
                self._drag_subtitle.start_ms = new_start_ms
                self._drag_subtitle.end_ms = new_end_ms
                self.state.invalidate_subtitle_audio(self._drag_subtitle.index)
                self._rebuild_timeline()
                # Update Treeview
                for item in self.subtitle_tree.get_children():
                    values = self.subtitle_tree.item(item, "values")
                    if int(values[0]) == self._drag_subtitle.index:
                        self.subtitle_tree.set(item, "start", self._format_timestamp_display(new_start_ms))
                        self.subtitle_tree.set(item, "end", self._format_timestamp_display(new_end_ms))
                        break
                self._update_status(f"Moved subtitle {self._drag_subtitle.index}")
        except Exception as e:
            self._update_status(f"Error moving subtitle: {e}")
        
        # Clean up drag state
        self._drag_subtitle_index = None
        self._drag_subtitle = None
        self._drag_start_x = None
        self._drag_start_left_x = None
        self._drag_duration = None
        self._drag_moved = False

    def _on_timeline_resize(self, event):
        """Handle timeline canvas resize"""
        # Redraw timeline markers
        self._draw_timeline()
        # Update playhead position
        self._update_playhead_position()

    def _rebuild_timeline(self):
        """Rebuild the entire timeline - redraw markers and update playhead"""
        self._draw_timeline()
        self._update_playhead_position()

    def _create_subtitle_area(self, parent):
        """Create subtitle Treeview"""
        frame = ttk.LabelFrame(parent, text="Subtitles")
        frame.pack(fill=tk.BOTH, expand=True)

        # Treeview with scrollbars
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("index", "start", "end", "text", "voice")
        self.subtitle_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse"
        )

        # Configure columns
        self.subtitle_tree.heading("index", text="#")
        self.subtitle_tree.heading("start", text="Start")
        self.subtitle_tree.heading("end", text="End")
        self.subtitle_tree.heading("text", text="Subtitle")
        self.subtitle_tree.heading("voice", text="Voice")

        self.subtitle_tree.column("index", width=50, minwidth=40, anchor=tk.CENTER)
        self.subtitle_tree.column("start", width=110, minwidth=90, anchor=tk.CENTER)
        self.subtitle_tree.column("end", width=110, minwidth=90, anchor=tk.CENTER)
        self.subtitle_tree.column("text", width=500, minwidth=200, anchor=tk.W)
        self.subtitle_tree.column("voice", width=120, minwidth=80, anchor=tk.CENTER)

        # Scrollbars
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.subtitle_tree.yview)
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.subtitle_tree.xview)
        self.subtitle_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        # Grid layout
        self.subtitle_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")

        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Bind selection
        self.subtitle_tree.bind("<<TreeviewSelect>>", self._on_subtitle_select)

        # Bind double-click for editing
        self.subtitle_tree.bind("<Double-1>", self._on_treeview_double_click)

        # Bind keyboard shortcuts for editing
        self.subtitle_tree.bind("<Return>", self._on_treeview_enter)
        self.subtitle_tree.bind("<Escape>", self._on_treeview_escape)
        self.subtitle_tree.bind("<FocusOut>", self._on_treeview_focus_out)

        # Bind timeline motion and release handlers. Press handling is already
        # bound once in _create_timeline.
        self.timeline_canvas.bind("<B1-Motion>", self._on_timeline_mouse_drag)
        self.timeline_canvas.bind("<ButtonRelease-1>", self._on_timeline_mouse_release)

    def _create_voice_area(self, parent):
        """Create the Piper voice-selection area."""
        frame = ttk.LabelFrame(parent, text="Piper Voice")
        frame.pack(fill=tk.X, pady=(5, 0))

        self.voice_var = tk.StringVar(value="Discovering Piper voices...")
        self.voice_combo = ttk.Combobox(
            frame,
            textvariable=self.voice_var,
            state=tk.DISABLED,
            values=(),
        )
        self.voice_combo.pack(fill=tk.X, padx=10, pady=5)
        self.voice_combo.bind("<<ComboboxSelected>>", self._on_voice_selected)
        self.btn_preview_voice = ttk.Button(
            frame,
            text="Preview Voice",
            command=self._on_preview_voice,
        )
        self.btn_preview_voice.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.btn_generate_all = ttk.Button(
            frame,
            text="Generate All Voices",
            command=self._on_generate_all_voices,
            state=tk.DISABLED,
        )
        self.btn_generate_all.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.btn_cancel_batch = ttk.Button(
            frame,
            text="Cancel",
            command=self._on_cancel_batch,
            state=tk.DISABLED,
        )
        self.btn_cancel_batch.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.batch_progress = ttk.Progressbar(
            frame, orient=tk.HORIZONTAL, mode="determinate"
        )
        self.batch_progress.pack(fill=tk.X, padx=10, pady=(0, 5))
        self._start_piper_discovery()

    def _start_piper_discovery(self):
        """Discover installed Piper voices without blocking the GUI."""
        if self._piper_load_thread is not None and self._piper_load_thread.is_alive():
            return
        self.voice_var.set("Discovering Piper voices...")
        self.voice_combo.config(state=tk.DISABLED, values=())
        self._update_status("Discovering Piper voices...")
        self._piper_load_thread = threading.Thread(
            target=self._piper_discovery_worker,
            daemon=True,
        )
        self._piper_load_thread.start()

    def _piper_discovery_worker(self):
        """Scan local voice directories and return the result to the GUI."""
        try:
            voices = self.piper_service.discover_voices()
            self._piper_result_queue.put(("success", voices))
        except Exception as exc:
            self._piper_result_queue.put(("error", str(exc)))

    def _check_piper_result(self):
        """Consume one Piper discovery result on the Tkinter main thread."""
        try:
            status, payload = self._piper_result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._check_piper_result)
            return

        if status != "success":
            self._piper_voices = []
            self.state.selected_voice = None
            self.voice_combo.config(state=tk.DISABLED, values=())
            self.voice_var.set("No Piper voices found")
            self._update_status(f"Piper voice discovery failed: {payload}")
            self._update_preview_button_state()
            self._update_batch_button_state()
            return

        self._piper_voices = list(payload)
        if not self._piper_voices:
            self.state.selected_voice = None
            self.voice_combo.config(state=tk.DISABLED, values=())
            self.voice_var.set("No Piper voices found")
            self._update_status("No Piper voices found")
            self._update_preview_button_state()
            self._update_batch_button_state()
            return

        names = [voice.name for voice in self._piper_voices]
        labels = [
            f"{voice.name} ({voice.source})" if names.count(voice.name) > 1 else voice.name
            for voice in self._piper_voices
        ]
        self.voice_combo.config(state="readonly", values=tuple(labels))
        self.voice_combo.current(0)
        self.state.selected_voice = self._piper_voices[0]
        self._update_status(f"Discovered {len(self._piper_voices)} Piper voices")
        self._update_preview_button_state()
        self._update_batch_button_state()

    def _on_voice_selected(self, event=None):
        """Store the user-selected Piper voice object."""
        index = self.voice_combo.current()
        if 0 <= index < len(self._piper_voices):
            self.state.selected_voice = self._piper_voices[index]
        self._update_preview_button_state()
        self._update_batch_button_state()

    @staticmethod
    def _clean_preview_text(raw_text: str) -> str:
        """Remove hidden control characters that TTS must never receive.

        Drops U+FEFF, normalizes \\r\\n/\\r to \\n, strips boundary blank
        lines/whitespace. Interior accents, punctuation, multiline breaks and
        meaningful spaces stay byte-identical.
        """
        text = raw_text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
        return text.strip(" \t\n")

    def _get_selected_subtitle_for_preview(self):
        """Single source of truth: CURRENT Treeview item -> live model subtitle.

        Returns (subtitle_index, raw_subtitle_text, voice, error_message).
        No cached/stale/fallback subtitle, voice, or text -- ever.
        """
        selection = self.subtitle_tree.selection()
        if not selection:
            return None, "", None, "Please select a subtitle first."
        values = self.subtitle_tree.item(selection[0], "values")
        if not values:
            return None, "", None, "Invalid subtitle selection."
        try:
            subtitle_index = int(values[0])
        except (TypeError, ValueError):
            return None, "", None, "Invalid subtitle selection."
        subtitle = None
        for sub in self.state.subtitles:
            if sub.index == subtitle_index:
                subtitle = sub
                break
        if subtitle is None:
            return None, "", None, f"Selected subtitle #{subtitle_index} no longer exists."
        raw_text = subtitle.text if isinstance(subtitle.text, str) else ""
        voice = self.state.selected_voice
        if voice is None:
            return None, "", None, "Please select a Piper voice first."
        return subtitle_index, raw_text, voice, ""

    def _update_preview_button_state(self):
        """Enable Preview Voice only when a subtitle+voice are ready."""
        if self.btn_preview_voice is None:
            return
        if self._preview_generating:
            self.btn_preview_voice.config(state=tk.DISABLED, text="Generating...")
            return
        ready = bool(self.subtitle_tree.selection()) and self.state.selected_voice is not None
        self.btn_preview_voice.config(
            state=tk.NORMAL if ready else tk.DISABLED, text="Preview Voice"
        )

    @staticmethod
    def _wav_fingerprint(wav_path):
        """Short size/hash/duration fingerprint of a WAV file (read-only)."""
        try:
            data = Path(wav_path).read_bytes()
        except OSError:
            return "unreadable"
        digest = hashlib.sha256(data).hexdigest()[:16]
        try:
            with wave.open(str(wav_path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                duration = f"{frames / rate:.2f}s" if rate else "unknown"
        except Exception:
            duration = "unknown"
        return f"size={len(data)} sha256={digest} duration={duration}"

    def _on_preview_voice(self):
        """Capture selection -> request -> worker. Treeview never queried again."""
        if self._preview_generating:
            return

        subtitle_index, raw_text, voice, error = self._get_selected_subtitle_for_preview()
        if error:
            self._update_status(error)
            messagebox.showinfo("Preview Voice", error)
            self._update_preview_button_state()
            return

        subtitle_text = self._clean_preview_text(raw_text)
        if not subtitle_text:
            self._update_status("Subtitle text is empty.")
            messagebox.showinfo("Preview Voice", "Subtitle text is empty.")
            return

        request_id = uuid.uuid4().hex[:8]
        self._preview_request_id = request_id
        print("[VOICE PREVIEW]")
        print(f"request_id={request_id}")
        print(f"subtitle_index={subtitle_index}")
        print(f"voice={voice.name}")
        print(f"text={subtitle_text!r}")

        self._preview_generating = True
        self._update_preview_button_state()
        self._update_status("Generating voice preview...")

        self._preview_thread = threading.Thread(
            target=self._preview_worker,
            args=(request_id, subtitle_index, subtitle_text, voice),
            daemon=True,
        )
        self._preview_thread.start()
        self.root.after(100, lambda _rid=request_id: self._check_preview_result(_rid))

    def _preview_output_path(self, request_id: str):
        """Fresh unique WAV under temp/preview/; never reuse an existing file."""
        project_root = Path(__file__).resolve().parent.parent
        preview_dir = project_root / "temp" / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        output_path = preview_dir / f"{request_id}.wav"
        while output_path.exists():
            output_path = preview_dir / f"{uuid.uuid4().hex[:8]}.wav"
        return output_path

    def _preview_worker(self, request_id: str, subtitle_index: int, subtitle_text: str, voice):
        """Synthesize ONLY the captured text; never touches Tkinter/Treeview."""
        try:
            output_path = self._preview_output_path(request_id)
            result_path = self.piper_service.synthesize(
                subtitle_text, voice, output_path, request_id=request_id
            )
            info = wav_info(str(result_path))
            print("[VOICE PREVIEW]")
            print(f"generated_wav={result_path}")
            print(f"exists={Path(result_path).is_file()}")
            print(f"size={info['size']} duration={info['duration_s']}s sha256={info['sha256']}")
            self._preview_result_queue.put(VoicePreviewResult(
                request_id=request_id,
                subtitle_index=subtitle_index,
                subtitle_text=subtitle_text,
                voice_name=voice.name,
                output_wav=str(result_path),
                success=True,
                wav_size=info["size"],
                wav_sha256=info["sha256"],
                wav_duration_s=info["duration_s"],
            ))
        except Exception as exc:
            self._preview_result_queue.put(VoicePreviewResult(
                request_id=request_id,
                subtitle_index=subtitle_index,
                subtitle_text=subtitle_text,
                voice_name=getattr(voice, "name", ""),
                output_wav="",
                success=False,
                error=str(exc),
            ))

    def _check_preview_result(self, request_id=None):
        """Consume one preview result on the Tkinter main thread."""
        try:
            result = self._preview_result_queue.get_nowait()
        except queue.Empty:
            if self._preview_generating:
                self.root.after(100, lambda _rid=request_id: self._check_preview_result(_rid))
            return

        if request_id is not None and result.request_id != request_id:
            self._preview_result_queue.put(result)
            if self._preview_generating:
                self.root.after(100, lambda _rid=request_id: self._check_preview_result(_rid))
            return

        self._preview_generating = False
        self._update_preview_button_state()

        if not result.success:
            self._update_status(f"Voice preview failed: {result.error}")
            messagebox.showerror("Preview Voice", f"Voice preview failed:\n{result.error}")
            return

        print("[VOICE PREVIEW]")
        print(f"playing_wav={result.output_wav}")
        print(f"playing_request_id={result.request_id}")
        print(f"playing_voice={result.voice_name}")
        try:
            before_play = wav_info(result.output_wav)
            match = (before_play["size"] == result.wav_size
                     and before_play["sha256"] == result.wav_sha256)
        except Exception as exc:
            before_play = {"size": 0, "sha256": "", "duration_s": 0.0}
            match = False
            print(f"[VOICE PREVIEW] before_play_unreadable={exc}")
        print(f"before_play_size={before_play['size']} "
              f"before_play_duration={before_play['duration_s']}s "
              f"before_play_sha256={before_play['sha256']}")
        print(f"wav_match={match}")
        if not match:
            self._update_status("Warning: preview WAV changed after synthesis.")
            messagebox.showwarning(
                "Preview Voice",
                "The preview WAV changed between synthesis and playback.",
            )
        self._update_status("Playing voice preview.")
        self._play_preview_wav(result.output_wav)
        self._update_preview_button_state()

    def _play_preview_wav(self, wav_path: str):
        """Play exactly the returned WAV file (non-blocking winsound)."""
        abs_path = str(Path(wav_path).resolve())
        if not Path(abs_path).is_file():
            self._update_status(f"Preview WAV not found: {abs_path}")
            messagebox.showerror("Preview Voice", f"Preview WAV not found:\n{abs_path}")
            return
        try:
            import winsound
        except ImportError:
            self._update_status(f"Preview saved: {abs_path} (audio playback not supported)")
            return

        def _play():
            try:
                try:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                except Exception:
                    pass
                winsound.PlaySound(abs_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as exc:
                self.root.after(
                    0, lambda: self._update_status(f"Voice preview failed: {exc}")
                )

        threading.Thread(target=_play, daemon=True).start()

    def _update_batch_button_state(self):
        """Enable Generate All Voices only when subtitles + voice are ready."""
        if self.btn_generate_all is None:
            return
        if self._batch_generating:
            self.btn_generate_all.config(state=tk.DISABLED)
            if self.btn_cancel_batch is not None:
                self.btn_cancel_batch.config(state=tk.NORMAL)
            return
        ready = bool(self.state.subtitles) and self.state.selected_voice is not None
        self.btn_generate_all.config(state=tk.NORMAL if ready else tk.DISABLED)
        if self.btn_cancel_batch is not None:
            self.btn_cancel_batch.config(state=tk.DISABLED)

    def _on_generate_all_voices(self):
        """Capture the full subtitle work list and start the batch worker."""
        if self._batch_generating:
            return
        voice = self.state.selected_voice
        if voice is None:
            self._update_status("Please select a Piper voice first.")
            messagebox.showinfo("Generate All Voices", "Please select a Piper voice first.")
            return
        if not self.state.subtitles:
            self._update_status("No subtitles loaded.")
            messagebox.showinfo("Generate All Voices", "Please load an SRT file first.")
            return

        # Immutable work list from the MODEL (never Treeview display strings,
        # never " | " joined text); the worker only sees these captured values.
        work_items = []
        for sub in self.state.subtitles:
            raw = sub.text if isinstance(sub.text, str) else ""
            work_items.append((
                sub.index,
                self._clean_preview_text(raw),
                sub.start_ms,
                sub.end_ms,
            ))

        batch_id = uuid.uuid4().hex[:8]
        self._batch_request_id = batch_id
        self._batch_cancel_event = threading.Event()
        self._batch_generating = True
        self._update_batch_button_state()
        if self.batch_progress is not None:
            self.batch_progress.config(maximum=len(work_items), value=0)
        self._update_status(f"Generating voices 1/{len(work_items)}...")

        self._batch_thread = threading.Thread(
            target=self._batch_worker,
            args=(batch_id, work_items, voice),
            daemon=True,
        )
        self._batch_thread.start()
        self.root.after(100, lambda _bid=batch_id: self._check_batch_result(_bid))

    def _on_cancel_batch(self):
        """Stop starting new synthesis jobs; keep what already succeeded."""
        if self._batch_cancel_event is not None:
            self._batch_cancel_event.set()
        self._update_status("Cancelling voice generation...")

    def _batch_worker(self, batch_id: str, work_items, voice):
        """Run the batch off the Tkinter main thread (no widget access)."""
        texts = [(index, text) for index, text, _, _ in work_items]
        project_root = Path(__file__).resolve().parent.parent
        output_dir = project_root / "temp" / "voices"

        def _progress(bid, done, total, index, ok, detail):
            self._batch_result_queue.put(
                ("progress", bid, done, total, index, ok, detail)
            )

        try:
            success_map, errors = generate_batch_voices(
                texts, output_dir, batch_id, voice,
                cancel_event=self._batch_cancel_event,
                progress_callback=_progress,
            )
            cancelled = (self._batch_cancel_event is not None
                         and self._batch_cancel_event.is_set())
            self._batch_result_queue.put(
                ("done", batch_id, success_map, errors, cancelled)
            )
        except Exception as exc:
            self._batch_result_queue.put(
                ("failed", batch_id, {}, {0: str(exc)}, False)
            )

    def _check_batch_result(self, batch_id=None):
        """Consume batch progress/results on the Tkinter main thread."""
        try:
            while True:
                item = self._batch_result_queue.get_nowait()
                kind = item[0]
                if batch_id is not None and item[1] != batch_id:
                    print(f"[VOICE BATCH] ignoring stale result batch_request_id={item[1]}")
                    continue
                if kind == "progress":
                    _, _, done, total, index, ok, _ = item
                    self._update_status(
                        f"Generating voices {done}/{total}... (subtitle #{index})"
                    )
                    if self.batch_progress is not None:
                        self.batch_progress.config(value=done)
                elif kind in ("done", "failed"):
                    _, _, success_map, errors, cancelled = item
                    self.state.subtitle_audio_paths = dict(success_map)
                    self.state.subtitle_audio_errors = dict(errors)
                    self.state.audio_batch_id = batch_id
                    self.state.audio_voice_name = getattr(
                        self.state.selected_voice, "name", None
                    )
                    total = len(success_map) + len(errors)
                    note = " (cancelled)" if cancelled else ""
                    self._update_status(
                        f"Voice generation complete: {len(success_map)}/{total} "
                        f"succeeded, {len(errors)} failed.{note}"
                    )
                    print("[VOICE BATCH]")
                    print(f"success={len(success_map)}")
                    print(f"failed={len(errors)}")
                    print(f"total={total}")
                    if errors:
                        print(f"failed_indexes={sorted(errors)}")
                    self._batch_generating = False
                    if self.batch_progress is not None:
                        self.batch_progress.config(value=len(success_map))
                    self._update_batch_button_state()
        except queue.Empty:
            pass
        if self._batch_generating:
            self.root.after(100, lambda _bid=batch_id: self._check_batch_result(_bid))

    def _create_status_bar(self, parent):
        """Create status bar at bottom"""
        self.status_bar = ttk.Label(
            parent,
            text="Ready",
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(5, 2)
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 0))

    def _update_status(self, message: str):
        """Update status bar message"""
        self.status_bar.config(text=message)
        self.root.update_idletasks()

    @staticmethod
    def _format_timestamp_display(ms: int) -> str:
        """Convert milliseconds to HH:MM:SS.mmm format for display"""
        if ms < 0:
            return "00:00:00.000"
        hours = ms // (3600 * 1000)
        ms_remaining = ms % (3600 * 1000)
        minutes = ms_remaining // (60 * 1000)
        ms_remaining = ms_remaining % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    @staticmethod
    def _format_short_timestamp(ms: int) -> str:
        """Convert milliseconds to MM:SS.mmm format for position display"""
        if ms < 0:
            return "00:00.000"
        minutes = ms // (60 * 1000)
        ms_remaining = ms % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _format_position_display(self, current_ms: int, duration_ms: int) -> str:
        """Format position as 'current / duration'"""
        return f"{self._format_short_timestamp(current_ms)} / {self._format_short_timestamp(duration_ms)}"

    # Button handlers
    def _on_load_video(self):
        """Handle Load Video button click"""
        file_path = filedialog.askopenfilename(
            title="Load Video File",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm"),
                ("All files", "*.*")
            ]
        )
        if not file_path:
            return

        # Stop any existing playback
        self._stop_playback()

        # Check FFmpeg availability first
        available, error_msg = self.video_service.check_ffmpeg()
        if not available:
            self._update_status("Failed to load video")
            messagebox.showerror("FFmpeg Not Found", error_msg)
            return

        # Clear existing video preview
        self._clear_video_preview()

        # Disable Load Video button during loading
        self.btn_load_video.config(state=tk.DISABLED)
        self._update_status("Loading video...")

        # Start background worker
        self._video_load_thread = threading.Thread(
            target=self._video_load_worker,
            args=(file_path,),
            daemon=True
        )
        self._video_load_thread.start()

    def _video_load_worker(self, file_path: str):
        """Background worker to load video metadata and extract first frame"""
        try:
            self.root.after(0, lambda: self._update_status("Reading video metadata..."))
            metadata = self.video_service.load_video_metadata(file_path)

            self.root.after(0, lambda: self._update_status("Extracting first frame..."))
            metadata = self.video_service.load_video_with_frame(file_path)

            self._video_result_queue.put(("success", metadata))
        except VideoLoadError as e:
            self._video_result_queue.put(("error", str(e)))
        except Exception as e:
            self._video_result_queue.put(("error", f"Unexpected error: {e}"))

    def _check_video_result(self):
        """Check for video loading result from background thread"""
        try:
            result = self._video_result_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._check_video_result)
            return

        # Re-enable button
        self.btn_load_video.config(state=tk.NORMAL)

        if result[0] == "success":
            _, metadata = result
            self._update_video_state(metadata)
            self._display_video_metadata(metadata)
            self._display_first_frame(metadata.first_frame_path)
            self._update_playback_controls_state()
            self._update_position_display()
            self._rebuild_timeline()
            self._update_status("Video loaded")
        else:
            _, error_msg = result
            self._update_status(f"Failed to load video")
            messagebox.showerror("Load Video Failed", f"Failed to load video:\n{error_msg}")

    def _update_video_state(self, metadata):
        """Update application state with video metadata"""
        self.state.video_path = metadata.path
        self.state.video_width = metadata.width
        self.state.video_height = metadata.height
        self.state.video_fps = metadata.fps
        self.state.video_frame_count = metadata.frame_count
        self.state.video_duration_ms = metadata.duration_ms
        self.state.video_has_audio = metadata.has_audio
        self.state.video_first_frame_path = metadata.first_frame_path
        # Reset playback state for new video
        self.state.clear_playback_state()

    def _display_video_metadata(self, metadata):
        """Display video metadata in the UI"""
        self.lbl_resolution.config(text=f"{metadata.width} x {metadata.height}")
        self.lbl_fps.config(text=f"{metadata.fps:.2f}")

        duration_str = self._format_timestamp_display(metadata.duration_ms)
        self.lbl_duration.config(text=duration_str)

        if metadata.frame_count is not None:
            self.lbl_frames.config(text=str(metadata.frame_count))
        else:
            self.lbl_frames.config(text="Unknown")

        self.lbl_audio.config(text="Yes" if metadata.has_audio else "No")

    def _display_first_frame(self, frame_path: str):
        """Display the first frame in the video preview area"""
        if not frame_path:
            return

        try:
            # Load image using Tkinter PhotoImage (supports PNG)
            image = tk.PhotoImage(file=frame_path)

            # Get preview container dimensions (the constraining frame)
            label_width = self.video_preview_container.winfo_width()
            label_height = self.video_preview_container.winfo_height()

            # If container not yet sized, use reasonable defaults (matching new 385px height)
            if label_width <= 1:
                label_width = 1000
            if label_height <= 1:
                label_height = 385

            # Calculate scaling to preserve aspect ratio and fit within container
            img_width = image.width()
            img_height = image.height()

            if img_width <= 0 or img_height <= 0:
                return

            scale_w = (label_width - 20) / img_width  # Account for padding
            scale_h = (label_height - 20) / img_height
            scale = min(scale_w, scale_h, 1.0)  # Never upscale beyond 1.0

            # Subsample to resize (PhotoImage only supports integer subsampling)
            if scale < 1.0:
                # Need to subsample
                sub_x = max(1, int(1 / scale))
                sub_y = max(1, int(1 / scale))
                image = image.subsample(sub_x, sub_y)
            # Don't upscale - keep original size if it fits

            # Keep reference to prevent garbage collection
            self._preview_image = image

            # Update label
            self.video_preview_label.config(image=image, text="")

        except tk.TclError:
            # If PhotoImage fails (e.g., unsupported format), show error text
            self.video_preview_label.config(text="Cannot display frame\n(unsupported format)", image="")
            self._preview_image = None

    def _clear_video_preview(self):
        """Clear video preview and metadata display"""
        self.video_preview_label.config(image="", text="Video Preview")
        self._preview_image = None
        self.lbl_resolution.config(text="—")
        self.lbl_fps.config(text="—")
        self.lbl_duration.config(text="—")
        self.lbl_frames.config(text="—")
        self.lbl_audio.config(text="—")

    def _on_preview_resize(self, event):
        """Handle preview area resize - redisplay frame at new size"""
        if self.state.video_first_frame_path and self._preview_image:
            self._display_first_frame(self.state.video_first_frame_path)

    # Playback controls
    def _update_playback_controls_state(self):
        """Update playback button states based on video load state"""
        has_video = self.state.video_path is not None
        state = tk.NORMAL if has_video else tk.DISABLED
        
        self.btn_play.config(state=state)
        self.btn_pause.config(state=state)
        self.btn_stop.config(state=state)
        self.seek_scale.config(state=state)
        
        if has_video and self.state.video_duration_ms > 0:
            self.seek_scale.config(to=self.state.video_duration_ms)

    def _update_position_display(self):
        """Update position label, seek scale, and timeline playhead"""
        if self.state.video_duration_ms > 0:
            self.lbl_position.config(text=self._format_position_display(
                self.state.current_time_ms, self.state.video_duration_ms
            ))
            # Update seek scale without triggering callback
            if not self._seek_scale_updating:
                self.seek_var.set(self.state.current_time_ms)
            # Update timeline playhead
            self._update_playhead_position()

    def _on_play(self):
        """Handle Play button click"""
        if not self.state.video_path:
            self._update_status("No video loaded")
            return

        if self.state.is_playing:
            return  # Already playing

        print(f"[DEBUG] PLAY CLICK - video_path={self.state.video_path}, duration_ms={self.state.video_duration_ms}, current_time_ms={self.state.current_time_ms}")

        if self.state.is_paused:
            # Resume from paused position
            self._resume_playback()
        else:
            # Start from current position (could be 0 or a seeked position)
            self._start_playback()

    def _on_pause(self):
        """Handle Pause button click"""
        if not self.state.is_playing:
            return

        self._pause_playback()

    def _on_stop(self):
        """Handle Stop button click"""
        self._stop_playback()
        # Reset to first frame
        self.state.current_time_ms = 0
        self._update_position_display()
        if self.state.video_first_frame_path:
            self._display_first_frame(self.state.video_first_frame_path)
        self._update_status("Stopped")

    def _start_playback(self):
        """Start video playback from current position"""
        print(f"[DEBUG] PLAYBACK START - current_time_ms={self.state.current_time_ms}, duration_ms={self.state.video_duration_ms}")
        self._playback_stop_event.clear()
        self.state.is_playing = True
        self.state.is_paused = False
        self._playback_start_time = time.monotonic() - (self.state.current_time_ms / 1000.0)
        self._playback_paused_time = 0.0

        # Update UI
        self.btn_play.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL)
        self.seek_scale.config(state=tk.NORMAL)

        # Start playback worker thread
        self._playback_thread = threading.Thread(
            target=self._playback_worker,
            daemon=True
        )
        self._playback_thread.start()
        print(f"[DEBUG] WORKER THREAD STARTED")

        self._update_status("Playing")

    def _resume_playback(self):
        """Resume video playback from paused position"""
        print(f"[DEBUG] RESUME PLAYBACK - current_time_ms={self.state.current_time_ms}")
        self._playback_stop_event.clear()
        self.state.is_playing = True
        self.state.is_paused = False
        # Adjust start time to account for paused duration
        self._playback_start_time = time.monotonic() - (self.state.current_time_ms / 1000.0)
        self._playback_paused_time = 0.0

        # Update UI
        self.btn_play.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.NORMAL)
        self.seek_scale.config(state=tk.NORMAL)

        # Start playback worker thread
        self._playback_thread = threading.Thread(
            target=self._playback_worker,
            daemon=True
        )
        self._playback_thread.start()
        print(f"[DEBUG] WORKER THREAD STARTED (resume)")

        self._update_status("Playing")

    def _pause_playback(self):
        """Pause video playback"""
        if not self.state.is_playing:
            return

        # Calculate current position
        elapsed = time.monotonic() - self._playback_start_time
        self.state.current_time_ms = int(elapsed * 1000)
        if self.state.current_time_ms > self.state.video_duration_ms:
            self.state.current_time_ms = self.state.video_duration_ms

        self._playback_stop_event.set()
        self.state.is_playing = False
        self.state.is_paused = True
        self._playback_paused_time = time.monotonic()

        # Update UI
        self.btn_play.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.DISABLED)
        self._update_position_display()
        self._update_status("Paused")
        print(f"[DEBUG] PAUSE - current_time_ms={self.state.current_time_ms}")

    def _stop_playback(self):
        """Stop video playback"""
        if not self.state.is_playing and not self.state.is_paused:
            return

        self._playback_stop_event.set()
        self.state.is_playing = False
        self.state.is_paused = False

        # Update UI
        self.btn_play.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)

        # Reset position to 0 and update playhead
        self.state.current_time_ms = 0
        self._update_position_display()
        self._update_playhead_position()
        print(f"[DEBUG] STOP - position reset to 0")

    def _playback_worker(self):
        """Background worker for video playback frame extraction"""
        print(f"[DEBUG] WORKER START - video_path={self.state.video_path}, duration_ms={self.state.video_duration_ms}")
        frame_interval = 0.066  # ~15 FPS update interval (more realistic for FFmpeg)
        temp_dir = Path(tempfile.gettempdir()) / "video_voice_editor_playback"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            while not self._playback_stop_event.is_set():
                # Calculate current position based on elapsed time
                elapsed = time.monotonic() - self._playback_start_time
                current_ms = int(elapsed * 1000)

                # Check if we've reached the end
                if current_ms >= self.state.video_duration_ms:
                    current_ms = self.state.video_duration_ms
                    self._playback_result_queue.put(("ended", current_ms))
                    print(f"[DEBUG] WORKER END - reached end at {current_ms}ms")
                    break

                # Clamp to duration
                current_ms = min(current_ms, self.state.video_duration_ms)

                # Extract frame at current position
                frame_filename = f"playback_frame_{uuid.uuid4().hex[:8]}.png"
                frame_path = temp_dir / frame_filename

                try:
                    print(f"[DEBUG] REQUEST FRAME at {current_ms}ms")
                    success = self.video_service.extract_frame_at_timestamp(
                        self.state.video_path, current_ms, str(frame_path)
                    )
                    if success:
                        self._playback_result_queue.put(("frame", str(frame_path), current_ms))
                        print(f"[DEBUG] FRAME EXTRACTED at {current_ms}ms -> {frame_path}")
                    else:
                        self._playback_result_queue.put(("error", f"Frame extraction failed at {current_ms}ms"))
                        print(f"[DEBUG] FRAME EXTRACTION FAILED at {current_ms}ms")
                except VideoLoadError as e:
                    self._playback_result_queue.put(("error", str(e)))
                    print(f"[DEBUG] VIDEO LOAD ERROR: {e}")
                    break
                except Exception as e:
                    self._playback_result_queue.put(("error", f"Unexpected error: {e}"))
                    print(f"[DEBUG] UNEXPECTED ERROR: {e}")
                    break

                # Sleep until next frame
                time.sleep(frame_interval)

        except Exception as e:
            self._playback_result_queue.put(("error", f"Playback worker error: {e}"))
            print(f"[DEBUG] WORKER EXCEPTION: {e}")

    def _check_playback_result(self):
        """Check for playback results from background thread"""
        try:
            while True:
                result = self._playback_result_queue.get_nowait()
                result_type = result[0]
                print(f"[DEBUG] QUEUE RESULT: {result_type}")

                if result_type == "frame":
                    _, frame_path, position_ms = result
                    self.state.current_time_ms = position_ms
                    self._update_position_display()
                    self._update_playhead_position()
                    self._display_frame_in_preview(frame_path)
                    # Clean up temp frame file
                    try:
                        Path(frame_path).unlink(missing_ok=True)
                    except Exception:
                        pass

                elif result_type == "ended":
                    _, position_ms = result
                    self.state.current_time_ms = position_ms
                    self._update_position_display()
                    self._update_playhead_position()
                    self._on_playback_ended()

                elif result_type == "error":
                    _, error_msg = result
                    self._update_status(f"Playback error: {error_msg}")
                    self._stop_playback()

        except queue.Empty:
            pass

        # Keep polling always so Play worker results are never missed.
        # (Previously polling stopped at startup because is_playing=False,
        # so frames queued by _playback_worker were never consumed.)
        self.root.after(30, self._check_playback_result)

    def _display_frame_in_preview(self, frame_path: str):
        """Display a frame in the video preview area (for playback)"""
        print(f"[DEBUG] DISPLAY FRAME: {frame_path}")
        try:
            image = tk.PhotoImage(file=frame_path)

            # Get preview container dimensions (the constraining frame)
            label_width = self.video_preview_container.winfo_width()
            label_height = self.video_preview_container.winfo_height()

            if label_width <= 1:
                label_width = 1000
            if label_height <= 1:
                label_height = 385

            img_width = image.width()
            img_height = image.height()

            if img_width <= 0 or img_height <= 0:
                print(f"[DEBUG] DISPLAY FRAME - invalid image dimensions: {img_width}x{img_height}")
                return

            scale_w = (label_width - 20) / img_width
            scale_h = (label_height - 20) / img_height
            scale = min(scale_w, scale_h, 1.0)  # Never upscale beyond 1.0

            if scale < 1.0:
                sub_x = max(1, int(1 / scale))
                sub_y = max(1, int(1 / scale))
                image = image.subsample(sub_x, sub_y)
            # Don't upscale - keep original size if it fits

            self._preview_image = image
            self.video_preview_label.config(image=image, text="")
            print(f"[DEBUG] DISPLAY FRAME SUCCESS - image={img_width}x{img_height}, scale={scale:.3f}, label={label_width}x{label_height}")

        except tk.TclError as e:
            print(f"[DEBUG] DISPLAY FRAME TCLERROR: {e}")
            pass  # Ignore display errors during playback

    def _on_playback_ended(self):
        """Handle playback end"""
        print(f"[DEBUG] PLAYBACK ENDED")
        self.state.is_playing = False
        self.state.is_paused = False
        self.state.current_time_ms = self.state.video_duration_ms
        self._update_position_display()
        self.btn_play.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)
        self._update_status("Playback ended")

    def _on_seek_drag(self, value):
        """Handle seek scale drag (throttled)"""
        if not self.state.video_path:
            return
        # Update position display during drag but don't seek yet
        self._seek_scale_updating = True
        pos_ms = int(float(value))
        self.lbl_position.config(text=self._format_position_display(pos_ms, self.state.video_duration_ms))

    def _on_seek_release(self, event):
        """Handle seek scale release - perform actual seek"""
        if not self.state.video_path:
            return

        self._seek_scale_updating = False
        pos_ms = int(self.seek_var.get())
        pos_ms = max(0, min(pos_ms, self.state.video_duration_ms))
        self.state.current_time_ms = pos_ms
        self._update_position_display()

        # Extract frame at new position
        self._seek_to_position(pos_ms)

    def _seek_to_position(self, position_ms: int):
        """Seek to a specific position and update preview"""
        if not self.state.video_path:
            return

        was_playing = self.state.is_playing
        
        if was_playing:
            # Pause current playback
            self._playback_stop_event.set()
            self.state.is_playing = False

        # Extract frame at seek position
        def do_seek():
            temp_dir = Path(tempfile.gettempdir()) / "video_voice_editor_playback"
            temp_dir.mkdir(parents=True, exist_ok=True)
            frame_filename = f"seek_frame_{uuid.uuid4().hex[:8]}.png"
            frame_path = temp_dir / frame_filename

            try:
                success = self.video_service.extract_frame_at_timestamp(
                    self.state.video_path, position_ms, str(frame_path)
                )
                if success:
                    self.root.after(0, lambda: self._on_seek_frame_ready(frame_path, was_playing))
                else:
                    self.root.after(0, lambda: self._update_status("Seek failed: frame extraction failed"))
            except VideoLoadError as e:
                self.root.after(0, lambda: self._update_status(f"Seek failed: {e}"))

        threading.Thread(target=do_seek, daemon=True).start()

    def _on_seek_frame_ready(self, frame_path: str, was_playing: bool):
        """Handle frame ready after seek"""
        self._display_frame_in_preview(frame_path)
        self._update_playhead_position()
        try:
            Path(frame_path).unlink(missing_ok=True)
        except Exception:
            pass

        if was_playing:
            # Resume playback from new position
            self._playback_start_time = time.monotonic() - (self.state.current_time_ms / 1000.0)
            self._playback_stop_event.clear()
            self.state.is_playing = True
            self._playback_thread = threading.Thread(
                target=self._playback_worker,
                daemon=True
            )
            self._playback_thread.start()
            self._update_status("Playing")
        else:
            self._update_status(f"Seeked to {self._format_short_timestamp(self.state.current_time_ms)}")

    def _on_load_srt(self):
        """Handle Load SRT button click"""
        file_path = filedialog.askopenfilename(
            title="Load SRT File",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")]
        )
        if not file_path:
            return

        # Clear existing Treeview
        self._clear_subtitle_tree()

        # Disable Load SRT button during loading
        self.btn_load_srt.config(state=tk.DISABLED)
        self._update_status("Loading SRT...")

        # Start background worker
        self._srt_load_thread = threading.Thread(
            target=self._srt_load_worker,
            args=(file_path,),
            daemon=True
        )
        self._srt_load_thread.start()

    def _srt_load_worker(self, file_path: str):
        """Background worker to load and parse SRT file"""
        try:
            subtitles = SRTService.load_srt(file_path)
            self._srt_result_queue.put(("success", file_path, subtitles))
        except (SRTParseError, FileNotFoundError, OSError, UnicodeDecodeError) as e:
            self._srt_result_queue.put(("error", str(e)))
        except Exception as e:
            self._srt_result_queue.put(("error", f"Unexpected error: {e}"))

    def _check_srt_result(self):
        """Check for SRT loading result from background thread"""
        try:
            result = self._srt_result_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._check_srt_result)
            return

        # Re-enable button
        self.btn_load_srt.config(state=tk.NORMAL)

        if result[0] == "success":
            _, file_path, subtitles = result
            self.state.srt_path = file_path
            self.state.subtitles = subtitles
            self.state.clear_audio_mappings()
            self._batch_insert_subtitles = subtitles
            self._batch_insert_index = 0
            self._insert_batch()
            # Rebuild timeline to show subtitle blocks
            self._rebuild_timeline()
            self._update_batch_button_state()
        else:
            _, error_msg = result
            self._update_status(f"Failed to load SRT: {error_msg}")
            messagebox.showerror("Load SRT Failed", f"Failed to load SRT file:\n{error_msg}")

    def _insert_batch(self):
        """Insert a batch of subtitles into Treeview"""
        batch_size = 100
        subtitles = self._batch_insert_subtitles
        total = len(subtitles)
        start = self._batch_insert_index
        end = min(start + batch_size, total)

        for i in range(start, end):
            sub = subtitles[i]
            self.subtitle_tree.insert(
                "", tk.END,
                values=(
                    sub.index,
                    self._format_timestamp_display(sub.start_ms),
                    self._format_timestamp_display(sub.end_ms),
                    sub.text.replace('\n', ' | ') if '\n' in sub.text else sub.text,
                    sub.voice
                )
            )

        self._batch_insert_index = end

        if end < total:
            self._update_status(f"Loading subtitles {end} / {total}")
            self.root.after(10, self._insert_batch)
        else:
            self._update_status(f"Loaded {total} subtitles")

    def _clear_subtitle_tree(self):
        """Clear all items from subtitle Treeview"""
        for item in self.subtitle_tree.get_children():
            self.subtitle_tree.delete(item)

    def _on_subtitle_select(self, event):
        """Handle subtitle selection in Treeview"""
        selection = self.subtitle_tree.selection()
        if selection:
            item = selection[0]
            index = int(self.subtitle_tree.item(item, "values")[0])
            # Find subtitle in state
            for sub in self.state.subtitles:
                if sub.index == index:
                    self.state.selected_subtitle = sub
                    self._select_subtitle_by_index(sub.index)
                    break
        self._update_preview_button_state()

    # === Treeview Cell Editing ===
    def _on_treeview_double_click(self, event):
        """Handle double-click on Treeview cell to start editing"""
        region = self.subtitle_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        column = self.subtitle_tree.identify_column(event.x)
        item = self.subtitle_tree.identify_row(event.y)
        if not item:
            return
        
        # Only allow editing of start, end, and text columns
        col_name = self._get_col_name_from_column(column)
        if col_name not in ("start", "end", "text"):
            return
        
        # Get current value
        current_values = self.subtitle_tree.item(item, "values")
        if not current_values:
            return
        
        # Get column index
        col_idx = int(column.replace("#", "")) - 1
        current_value = current_values[col_idx]
        
        # Start editing
        self._start_treeview_edit(item, col_name, col_idx, current_value)

    def _start_treeview_edit(self, item, col_name, col_idx, current_value):
        """Start in-place editing of a Treeview cell"""
        if hasattr(self, '_edit_entry') and self._edit_entry:
            self._cancel_treeview_edit()
        
        # Get cell bounding box
        cell_bbox = self.subtitle_tree.bbox(item, f"#{col_idx+1}")
        if not cell_bbox or len(cell_bbox) < 4:
            return
        x, y, width, height = cell_bbox
        if width <= 0 or height <= 0:
            return
        
        # Create entry widget
        self._edit_entry = ttk.Entry(self.subtitle_tree)
        self._edit_entry.place(x=x, y=y, width=width, height=height)
        
        # Set initial value
        if self._edit_var is None:
            self._edit_var = tk.StringVar()
        self._edit_var.set(current_value)
        self._edit_entry.config(textvariable=self._edit_var)
        
        # Store edit context
        self._edit_item = item
        self._edit_col_name = self._get_col_name_from_column(f"#{col_idx+1}")
        self._edit_col_idx = col_idx
        
        # Bind events
        self._edit_entry.bind("<Return>", self._on_treeview_enter)
        self._edit_entry.bind("<Escape>", self._on_treeview_escape)
        self._edit_entry.bind("<FocusOut>", self._on_treeview_focus_out)
        
        # Focus and select all
        self._edit_entry.focus_set()
        self._edit_entry.select_range(0, tk.END)

    def _get_col_name_from_column(self, column):
        """Map column identifier to column name"""
        col_map = {"#1": "index", "#2": "start", "#3": "end", "#4": "text", "#5": "voice"}
        return col_map.get(column, "")

    def _get_subtitle_duration(self, subtitle_index: int) -> int:
        """Get the duration of a subtitle in milliseconds"""
        for sub in self.state.subtitles:
            if sub.index == subtitle_index:
                return sub.end_ms - sub.start_ms
        return 0

    def _on_treeview_enter(self, event=None):
        """Save Treeview cell edit"""
        self._save_treeview_edit()

    def _on_treeview_escape(self, event=None):
        """Cancel Treeview cell edit"""
        self._cancel_treeview_edit()

    def _on_treeview_focus_out(self, event=None):
        """Save edit when focus leaves entry"""
        # Small delay to allow click events to process
        self.root.after(100, self._save_treeview_edit)

    def _save_treeview_edit(self):
        """Save Treeview cell edit"""
        if not hasattr(self, '_edit_entry') or not self._edit_entry:
            return
        
        new_value = self._edit_var.get().strip()
        col_name = getattr(self, '_edit_col_name', '')
        col_idx = getattr(self, '_edit_col_idx', -1)
        item = getattr(self, '_edit_item', None)
        
        # Clean up entry
        self._edit_entry.destroy()
        self._edit_entry = None
        self._edit_var = None
        self._edit_item = None
        self._edit_col_name = None
        self._edit_col_idx = -1
        
        if not item or col_name not in ("start", "end", "text"):
            return
        
        # Get subtitle index
        values = self.subtitle_tree.item(item, "values")
        if not values:
            return
        sub_index = int(values[0])
        
        # Find subtitle in state
        subtitle = None
        for sub in self.state.subtitles:
            if sub.index == sub_index:
                subtitle = sub
                break
        
        if not subtitle:
            return
        
        # Store old values for potential revert
        old_start = subtitle.start_ms
        old_end = subtitle.end_ms
        old_text = subtitle.text
        
        try:
            if col_name == "text":
                # Update text
                subtitle.text = new_value
                # Update Treeview display text (replace newlines with | for display)
                display_text = new_value.replace('\n', ' | ')
                self.subtitle_tree.set(item, "text", display_text)
                # Update timeline block text
                self._update_subtitle_block_text(subtitle)
                
            elif col_name == "start":
                # Parse and validate start time
                new_start_ms = self._parse_time_input(new_value)
                if new_start_ms is None:
                    raise ValueError("Invalid start time format")
                if new_start_ms < 0:
                    raise ValueError("Start time cannot be negative")
                if new_start_ms >= subtitle.end_ms:
                    raise ValueError("Start time must be before end time")
                if self.state.video_duration_ms > 0 and new_start_ms > self.state.video_duration_ms:
                    raise ValueError("Start time exceeds video duration")
                
                subtitle.start_ms = new_start_ms
                self.subtitle_tree.set(item, "start", self._format_timestamp_display(new_start_ms))
                self._update_subtitle_block_position(subtitle)
                
            elif col_name == "end":
                # Parse and validate end time
                new_end_ms = self._parse_time_input(new_value)
                if new_end_ms is None:
                    raise ValueError("Invalid end time format")
                if new_end_ms <= subtitle.start_ms:
                    raise ValueError("End time must be after start time")
                if self.state.video_duration_ms > 0 and new_end_ms > self.state.video_duration_ms:
                    raise ValueError("End time exceeds video duration")
                
                subtitle.end_ms = new_end_ms
                self.subtitle_tree.set(item, "end", self._format_timestamp_display(new_end_ms))
                self._update_subtitle_block_position(subtitle)
            
            # Generated audio for this subtitle is stale after any edit.
            self.state.invalidate_subtitle_audio(subtitle.index)
            # Update timeline block
            self._rebuild_timeline()
            self._update_status(f"Updated {col_name} for subtitle {subtitle.index}")
            
        except ValueError as e:
            self._update_status(f"Error: {e}")
            # Revert Treeview to old value
            if col_name == "text":
                self.subtitle_tree.set(item, "text", old_text.replace('\n', ' | '))
            elif col_name == "start":
                self.subtitle_tree.set(item, "start", self._format_timestamp_display(old_start))
            elif col_name == "end":
                self.subtitle_tree.set(item, "end", self._format_timestamp_display(old_end))
            self._update_status(f"Error: {e}")
        except Exception as e:
            self._update_status(f"Unexpected error: {e}")
        
        # Clean up
        self._edit_entry = None
        self._edit_var = None
        self._edit_item = None
        self._edit_col_name = None
        self._edit_col_idx = -1

    def _cancel_treeview_edit(self):
        """Cancel Treeview cell edit"""
        if hasattr(self, '_edit_entry') and self._edit_entry:
            self._edit_entry.destroy()
            self._edit_entry = None
            self._edit_var = None
            self._edit_item = None
            self._edit_col_name = None
            self._edit_col_idx = -1

    def _parse_time_input(self, time_str: str) -> int:
        """Parse time string in MM:SS.mmm or HH:MM:SS.mmm format to milliseconds"""
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

    def _update_subtitle_block_text(self, subtitle):
        """Update subtitle block text on timeline"""
        if subtitle.index not in self._subtitle_block_ids:
            return
        rect_id, text_id = self._subtitle_block_ids[subtitle.index]
        rect_coords = self.timeline_canvas.coords(rect_id)
        if rect_coords:
            max_width_px = rect_coords[2] - rect_coords[0]
        else:
            max_width_px = 100
        display_text = self._truncate_subtitle_text(subtitle.text, max_width_px)
        self.timeline_canvas.itemconfig(text_id, text=display_text)

    def _update_subtitle_block_position(self, subtitle):
        """Update subtitle block position on timeline after timing change"""
        if subtitle.index not in self._subtitle_block_ids:
            return
        rect_id, text_id = self._subtitle_block_ids[subtitle.index]
        canvas_width = self.timeline_canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = 1000
        
        left_x = self._time_to_x(subtitle.start_ms, canvas_width)
        right_x = self._time_to_x(subtitle.end_ms, canvas_width)
        
        # Ensure minimum visual width
        min_width = 8
        if right_x - left_x < 8:
            right_x = left_x + 8
        
        # Clamp to timeline bounds
        left_x = max(self._timeline_margin_left, left_x)
        right_x = min(canvas_width - self._timeline_margin_right, right_x)
        
        if left_x < right_x:
            self.timeline_canvas.coords(rect_id, left_x, 
                self._timeline_margin_top + (self._timeline_height - self._timeline_margin_top - self._timeline_margin_bottom - 28) // 2,
                right_x, self._timeline_margin_top + (self._timeline_height - self._timeline_margin_top - self._timeline_margin_bottom - 28) // 2 + 28)
            # Update text position
            self.timeline_canvas.coords(text_id, (left_x + right_x) // 2, 
                self._timeline_margin_top + (self._timeline_height - self._timeline_margin_top - self._timeline_margin_bottom - 28) // 2 + 14)

    def _on_save_srt(self):
        self._update_status("Save SRT is not implemented yet.")

    def _on_generate_mp4(self):
        self._update_status("Generate Final MP4 is not implemented yet.")

    def run(self):
        """Start the application main loop"""
        self.root.mainloop()