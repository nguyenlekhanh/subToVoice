import os
from pathlib import Path

p = Path(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py')
print(f"File size: {p.stat().st_size} bytes")

with open(p, 'rb') as f:
    content = f.read()
    
# Check for BOM
print(f"First 3 bytes: {content[:3]}")
print(f"Last 10 bytes: {content[-10:]}")

# Check for any non-ASCII characters
with open(p, 'r', encoding='utf-8') as f:
    content = f.read()
    for i, ch in enumerate(content):
        if ord(ch) > 127:
            print(f"Non-ASCII at pos {i}: {repr(ch)} (U+{ord(ch):04X})")
            if i > 10:
                break