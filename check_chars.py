with open(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check for any control characters or non-printable
for i, ch in enumerate(content):
    if ord(ch) < 32 and ch not in '\n\r\t':
        print(f"Control char at pos {i}: U+{ord(ch):04X} ({repr(ch)})")
    elif ord(ch) > 127:
        print(f"Non-ASCII at pos {i}: U+{ord(ch):04X} ({ch})")

# Check for any zero-width or invisible characters
import unicodedata
for i, ch in enumerate(content):
    if unicodedata.category(ch) in ('Cf', 'Cc') and ch not in '\n\r\t':
        print(f"Format/control char at pos {i}: U+{ord(ch):04X} category {unicodedata.category(ch)}")