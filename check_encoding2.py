import os
from pathlib import Path

p = Path(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py')
print(f"File size: {p.stat().st_size} bytes")

with open(p, 'rb') as f:
    content = f.read()
    
# Check for BOM
print(f"First 3 bytes: {content[:3]}")
print(f"Last 20 bytes: {content[-20:]}")

# Check line endings
has_crlf = b'\r\n' in content
has_lf = b'\n' in content
has_cr = b'\r' in content and b'\r\n' not in content
print(f"Has CRLF: {has_crlf}")
print(f"Has LF only: {has_lf and not has_crlf}")
print(f"Has CR only: {has_cr}")

# Check for any non-ASCII characters
with open(p, 'r', encoding='utf-8') as f:
    content = f.read()
    non_ascii = [(i, ch) for i, ch in enumerate(content) if ord(ch) > 127]
    if non_ascii:
        for i, ch in non_ascii[:20]:
            print(f"Non-ASCII at pos {i}: {repr(ch)} (U+{ord(ch):04X})")
    else:
        print("No non-ASCII characters found (pure ASCII)")

# Verify UTF-8 decode works
try:
    with open(p, 'r', encoding='utf-8') as f:
        f.read()
    print("UTF-8 decode: OK")
except UnicodeDecodeError as e:
    print(f"UTF-8 decode failed: {e}")