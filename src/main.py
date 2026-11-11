from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def self_test() -> int:
    """Verify that the frozen .app can still call the system speech synthesizer.

    CI runners often have no downloaded Chinese voice. Falling back to any
    available system voice keeps the packaging check meaningful (the check is
    about the frozen process reaching /usr/bin/say, not about a specific voice).
    """
    from src.core.speech import SpeechEngine, choose_voice, list_voices

    voices = list_voices()
    voice = choose_voice(voices)
    fallback = False
    if not voice and voices:
        voice = voices[0]
        fallback = True
    result = {
        "voices": len(voices),
        "voice": voice.identifier if voice else None,
        "fallback": fallback,
    }
    if voice:
        engine = SpeechEngine(voice, 200)
        text = (
            "自检：打包环境下的语音合成测试。"
            if voice.is_chinese
            else "DocReader speech synthesis self test."
        )
        path, duration, error = engine.synthesize(text)
        result.update(
            {"ok": bool(path), "duration": round(duration, 2), "error": error}
        )
    else:
        result.update({"ok": False, "error": "系统没有任何可用语音"})
    text = json.dumps(result, ensure_ascii=False)
    print(text)
    Path("/tmp/docreader_selftest.json").write_text(text, encoding="utf-8")
    return 0 if result["ok"] else 1


def main() -> None:
    if os.environ.get("DOCREADER_SELFTEST") == "1":
        sys.exit(self_test())

    from PySide6.QtWidgets import QApplication

    from src.ui.main_window import MainWindow

    QApplication.setApplicationName("文档朗读器")
    QApplication.setOrganizationName("LocalTools")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
