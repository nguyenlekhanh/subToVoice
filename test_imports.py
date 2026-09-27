import sys
sys.path.insert(0, r'C:\khanh\python\30_2 subTheoVoice1')

try:
    from app.ui import VideoVoiceEditorApp
    from app.state import AppState
    from models.subtitle import Subtitle
    from services.srt_service import SRTService
    from services.video_service import VideoService
    from services.tts_service import TTSService
    from services.ffmpeg_service import FFmpegService
    print("All imports successful!")
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()