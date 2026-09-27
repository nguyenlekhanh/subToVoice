with open(r'C:/khanh/python/30_2 subTheoVoice1/app/ui.py', 'rb') as f:
    content = f.read()
lines = content.splitlines(keepends=True)
for i in range(750, 760):
    line = lines[i]
    print(f'Line {i+1}: {list(line)}')