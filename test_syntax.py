import ast
with open('app/ui.py', encoding='utf-8') as f:
    content = f.read()
ast.parse(content)
print("Syntax OK")