with open(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Extract the try block (lines 726-755)
try_block = ''.join(lines[725:755])
print("Try block content:")
print(try_block)

# Count brackets
paren = 0
bracket = 0
brace = 0
for i, ch in enumerate(try_block):
    if ch == '(':
        paren += 1
    elif ch == ')':
        paren -= 1
    elif ch == '[':
        bracket += 1
    elif ch == ']':
        bracket -= 1
    elif ch == '{':
        brace += 1
    elif ch == '}':
        brace -= 1

print(f"Parentheses: {paren} (should be 0)")
print(f"Brackets: {bracket} (should be 0)")
print(f"Braces: {brace} (should be 0)")