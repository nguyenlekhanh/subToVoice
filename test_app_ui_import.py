import sys
sys.path.insert(0, r'C:\khanh\python\30_2 subTheoVoice1')

try:
    import app.ui
    print("Import OK")
except Exception as e:
    print(f"Import Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()