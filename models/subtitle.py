"""
Subtitle model
"""
from dataclasses import dataclass


@dataclass
class Subtitle:
    """Represents a single subtitle entry"""
    index: int
    start_ms: int
    end_ms: int
    text: str
    voice: str = ""

    def __post_init__(self):
        if self.start_ms < 0:
            raise ValueError(f"start_ms cannot be negative: {self.start_ms}")
        if self.end_ms < 0:
            raise ValueError(f"end_ms cannot be negative: {self.end_ms}")
        if self.end_ms <= self.start_ms:
            raise ValueError(f"end_ms ({self.end_ms}) must be greater than start_ms ({self.start_ms})")
        if not isinstance(self.index, int) or self.index <= 0:
            raise ValueError(f"index must be a positive integer: {self.index}")

    def __repr__(self):
        return f"Subtitle({self.index}, {self.start_ms}-{self.end_ms}, '{self.text[:30]}...')"