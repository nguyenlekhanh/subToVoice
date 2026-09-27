"""
SRT Service - SRT parsing and writing functionality
"""
import re
from pathlib import Path
from typing import List, Optional

from models.subtitle import Subtitle


class SRTParseError(Exception):
    """Raised when SRT file parsing fails"""
    pass


class SRTService:
    """Service for parsing and writing SRT files"""

    # Regex patterns
    TIMESTAMP_PATTERN = re.compile(
        r'^(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})$'
    )
    INDEX_PATTERN = re.compile(r'^\d+$')

    @staticmethod
    def parse_timestamp(timestamp_str: str) -> int:
        """
        Convert SRT timestamp (HH:MM:SS,mmm) to milliseconds.

        Args:
            timestamp_str: Timestamp string like "00:00:02,000"

        Returns:
            Milliseconds as integer

        Raises:
            SRTParseError: If timestamp format is invalid
        """
        match = re.match(r'^(\d{2}):(\d{2}):(\d{2}),(\d{3})$', timestamp_str.strip())
        if not match:
            raise SRTParseError(f"Invalid timestamp format: '{timestamp_str}'. Expected HH:MM:SS,mmm")

        hours, minutes, seconds, milliseconds = map(int, match.groups())

        if minutes >= 60:
            raise SRTParseError(f"Invalid minutes in timestamp: {minutes} (must be < 60)")
        if seconds >= 60:
            raise SRTParseError(f"Invalid seconds in timestamp: {seconds} (must be < 60)")
        if milliseconds >= 1000:
            raise SRTParseError(f"Invalid milliseconds in timestamp: {milliseconds} (must be < 1000)")

        return hours * 3600 * 1000 + minutes * 60 * 1000 + seconds * 1000 + milliseconds

    @staticmethod
    def format_timestamp(ms: int) -> str:
        """
        Convert milliseconds to SRT timestamp (HH:MM:SS,mmm).

        Args:
            ms: Milliseconds as integer

        Returns:
            Timestamp string like "00:00:02,000"

        Raises:
            ValueError: If ms is negative
        """
        if ms < 0:
            raise ValueError(f"Cannot format negative milliseconds: {ms}")

        hours = ms // (3600 * 1000)
        ms_remaining = ms % (3600 * 1000)
        minutes = ms_remaining // (60 * 1000)
        ms_remaining = ms_remaining % (60 * 1000)
        seconds = ms_remaining // 1000
        milliseconds = ms_remaining % 1000

        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    @classmethod
    def load_srt(cls, file_path: str) -> List[Subtitle]:
        """
        Parse an SRT file and return list of Subtitle objects.

        Args:
            file_path: Path to the SRT file

        Returns:
            List of Subtitle objects

        Raises:
            SRTParseError: If file cannot be parsed
            FileNotFoundError: If file does not exist
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"SRT file not found: {file_path}")

        # Read file with UTF-8, handle BOM
        content = path.read_text(encoding='utf-8-sig')

        if not content.strip():
            return []

        # Split into blocks by double newlines (blank lines)
        blocks = re.split(r'\n\s*\n', content.strip())

        subtitles = []

        for block_idx, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue

            lines = block.split('\n')
            if len(lines) < 3:
                raise SRTParseError(
                    f"Block {block_idx + 1}: Invalid subtitle block - "
                    f"expected at least 3 lines (index, timestamp, text), got {len(lines)}"
                )

            # Parse index
            index_line = lines[0].strip()
            if not cls.INDEX_PATTERN.match(index_line):
                raise SRTParseError(
                    f"Block {block_idx + 1}: Invalid subtitle index: '{index_line}'"
                )
            try:
                index = int(index_line)
            except ValueError:
                raise SRTParseError(f"Block {block_idx + 1}: Index is not a valid integer: '{index_line}'")

            # Parse timestamp line
            timestamp_line = lines[1].strip()
            timestamp_match = cls.TIMESTAMP_PATTERN.match(timestamp_line)
            if not timestamp_match:
                raise SRTParseError(
                    f"Block {block_idx + 1}: Invalid timestamp line: '{timestamp_line}'. "
                    f"Expected format: HH:MM:SS,mmm --> HH:MM:SS,mmm"
                )

            try:
                start_h, start_m, start_s, start_ms, end_h, end_m, end_s, end_ms = map(int, timestamp_match.groups())
            except ValueError as e:
                raise SRTParseError(f"Block {block_idx + 1}: Failed to parse timestamp numbers: {e}")

            # Validate time components
            for label, val, max_val in [
                ("start minutes", start_m, 60),
                ("start seconds", start_s, 60),
                ("start milliseconds", start_ms, 1000),
                ("end minutes", end_m, 60),
                ("end seconds", end_s, 60),
                ("end milliseconds", end_ms, 1000),
            ]:
                if val >= max_val:
                    raise SRTParseError(f"Block {block_idx + 1}: Invalid {label}: {val} (must be < {max_val})")

            start_ms_total = start_h * 3600 * 1000 + start_m * 60 * 1000 + start_s * 1000 + start_ms
            end_ms_total = end_h * 3600 * 1000 + end_m * 60 * 1000 + end_s * 1000 + end_ms

            if end_ms_total <= start_ms_total:
                raise SRTParseError(
                    f"Block {block_idx + 1}: End time ({end_ms_total}ms) must be greater than "
                    f"start time ({start_ms_total}ms)"
                )

            # Parse text (remaining lines, preserving newlines)
            text_lines = lines[2:]
            if not text_lines:
                raise SRTParseError(f"Block {block_idx + 1}: Missing subtitle text")

            text = '\n'.join(text_lines)

            subtitle = Subtitle(
                index=index,
                start_ms=start_ms_total,
                end_ms=end_ms_total,
                text=text,
                voice=""
            )
            subtitles.append(subtitle)

        return subtitles

    @classmethod
    def save_srt(cls, file_path: str, subtitles: List[Subtitle]) -> None:
        """
        Write subtitles to an SRT file.

        Args:
            file_path: Path to write the SRT file
            subtitles: List of Subtitle objects

        Raises:
            ValueError: If subtitles list is invalid
            OSError: If file cannot be written
        """
        if not subtitles:
            Path(file_path).write_text("", encoding='utf-8')
            return

        lines = []
        for i, subtitle in enumerate(subtitles):
            # Add blank line between subtitle blocks (except first)
            if i > 0:
                lines.append("")

            # Index
            lines.append(str(subtitle.index))

            # Timestamp line
            start_ts = cls.format_timestamp(subtitle.start_ms)
            end_ts = cls.format_timestamp(subtitle.end_ms)
            lines.append(f"{start_ts} --> {end_ts}")

            # Text (preserve multi-line)
            lines.append(subtitle.text)

        content = '\n'.join(lines) + '\n'
        Path(file_path).write_text(content, encoding='utf-8')