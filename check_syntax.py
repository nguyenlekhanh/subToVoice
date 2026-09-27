import py_compile
import sys

try:
    py_compile.compile(r'C:\khanh\python\30_2 subTheoVoice1\app\ui.py', doraise=True)
    print("app/ui.py Syntax OK")
except py_compile.PyCompileError as e:
    print(f"Syntax Error at line {e.lineno}: {e.msg}")
except Exception as e:
    print(f"Error: {e}")