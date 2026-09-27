with open(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py', 'rb') as f:
    content = f.read()
lines = content.splitlines(keepends=True)
print(f'Total lines: {len(lines)}')
print(f'Line 754 (idx 753) bytes: {list(lines[753])}')
print(f'Line 754: {repr(lines[753])}')
print(f'Line 726 (idx 725) bytes: {list(lines[725])}')
print(f'Line 726: {repr(lines[725])}')