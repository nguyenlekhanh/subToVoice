#!/usr/bin/env python3
"""PLAN 15 FIX 2 manual check: which Piper runtime does THIS Python use?

NOT a unit test. Run manually with a working Python:

    python tests/manual_piper_runtime_check.py

It uses the real banmai model from config/piper/ and reports the runtime,
return code, and output WAV facts. Compares nothing by itself: paste the
[PIPER RUNTIME] block next to the app's log lines to see whether APP RUNTIME
and MANUAL RUNTIME match. Never touches Tkinter or the GUI preview path.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.piper_service import (
    PiperSynthesisError,
    PiperVoice,
    describe_piper_runtime,
    discover_voices,
    synthesize,
    wav_info,
)

TEXT_A = "Mẹ ơi, ba ơi, cho con đi chơi với các bạn nha?"


def main():
    print("=== APP RUNTIME (this interpreter) ===")
    info = describe_piper_runtime()
    if info["piper_command"] is None:
        print(f"ABORT: {info['command_error']}")
        return 1

    voices = {voice.name: voice for voice in discover_voices()}
    voice = voices.get("banmai")
    if voice is None:
        print("ABORT: banmai model not discovered in config/piper/.")
        return 1
    print(f"MODEL: {voice.model_path}")
    print(f"CONFIG: {voice.config_path}")

    out_wav = (Path(__file__).resolve().parent.parent / "temp" / "preview"
               / f"manual_runtime_{uuid.uuid4().hex[:8]}.wav")
    try:
        result = synthesize(TEXT_A, voice, out_wav, request_id="manual")
    except PiperSynthesisError as exc:
        print(f"SYNTHESIS FAILED: {exc}")
        return 1
    details = wav_info(result)
    print("=== RESULT ===")
    print(f"output_wav={details['path']}")
    print(f"wav_exists=True wav_size={details['size']} "
          f"duration={details['duration_s']}s sha256={details['sha256'][:16]}")
    print("Compare the [PIPER RUNTIME] block above with the app's log lines:")
    print("  same piper_command + piper_version => runtimes match;")
    print("  different => the mismatch hypothesis needs a listening A/B test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
