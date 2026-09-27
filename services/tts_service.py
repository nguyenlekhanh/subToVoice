"""
TTS Service - Placeholder for future Piper TTS functionality
NOTE: This will use LOCAL Piper Vietnamese voices.
Do NOT use Edge TTS.
Piper configuration will be handled in a later plan after inspecting actual Piper voice files.
"""


class TTSService:
    """Service for text-to-speech using local Piper TTS"""

    def __init__(self):
        # TODO: Initialize Piper TTS in a later plan
        self.piper_path = None
        self.voices_dir = None

    def generate_speech(self, text: str, voice: str, output_path: str):
        """Generate speech using Piper TTS"""
        # TODO: Implement Piper TTS generation in a later plan
        raise NotImplementedError("Piper TTS generation not implemented yet")

    def discover_voices(self):
        """Discover available Piper voice models"""
        # TODO: Implement voice discovery in a later plan
        raise NotImplementedError("Voice discovery not implemented yet")