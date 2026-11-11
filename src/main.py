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
    from src.core.speech import (
        MIN_AUDIO_DURATION,
        SpeechEngine,
        choose_voice,
        list_voices,
    )

    voices = list_voices()
    chosen = choose_voice(voices)
    preferred = chosen.identifier if chosen else ""
    candidates = ([chosen] if chosen else []) + [
        v for v in voices if v.identifier != preferred
    ]
    voice = None
    fallback = False
    outcome = {"ok": False, "error": "系统没有任何可用语音"}
    for index, candidate in enumerate(candidates):
        engine = SpeechEngine(candidate, 200)
        text = (
            "自检：打包环境下的语音合成测试。"
            if candidate.is_chinese
            else "DocReader speech synthesis self test."
        )
        path, duration, error = engine.synthesize(text)
        # A listed-but-not-downloaded voice yields a silent ~16 ms file.
        if path and duration >= MIN_AUDIO_DURATION:
            voice = candidate
            fallback = index > 0 or not candidate.is_chinese
            outcome = {"ok": True, "duration": round(duration, 2), "error": ""}
            break
        outcome["error"] = error or "语音资源不可用"
    result = {
        "voices": len(voices),
        "voice": voice.identifier if voice else None,
        "fallback": fallback,
    }
    result.update(outcome)
    # End-to-end check for the naturalness modules: a frozen build could omit
    # them silently, or the embedded [[slnc]] commands could stop working.
    if voice and outcome.get("ok"):
        try:
            from src.core.oralizer import oralize
            from src.core.prosody import render

            sample = render(
                oralize("文档本身没有时间轴，所以程序按语速把字数换算成时间。"),
                2,
                200,
            )
            sample_path, sample_duration, sample_error = SpeechEngine(
                voice, 200
            ).synthesize(sample)
            result["naturalness"] = bool(
                sample_path
                and sample_duration >= MIN_AUDIO_DURATION
                and "[[slnc" in sample
            )
            if not result["naturalness"]:
                result["error"] = sample_error or "韵律合成未通过"
                result["ok"] = False
        except Exception as exc:
            result["naturalness"] = False
            result["error"] = f"自然度模块不可用：{exc}"
            result["ok"] = False
    else:
        result["naturalness"] = False
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
