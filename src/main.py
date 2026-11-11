from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.version import __version__  # noqa: E402


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
        "version": __version__,
        "voices": len(voices),
        "voice": voice.identifier if voice else None,
        "fallback": fallback,
    }
    result.update(outcome)
    # End-to-end check for the naturalness modules: a frozen build could omit
    # them silently, or the embedded [[slnc]] commands could stop working.
    sample_path = None
    if voice and outcome.get("ok"):
        try:
            from src.core.oralizer import oralize
            from src.core.prosody import render

            stamp = datetime.now().strftime("%H%M%S")
            sample = render(
                oralize(f"文档本身没有时间轴，程序按语速把字数换算成时间。{stamp}"),
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
    # 打磨后级（numpy + afconvert）最容易在打包时被漏掉：漏了不会报错，
    # 只是音量悄悄掉回 -18 dBFS，用户只感觉「声音又变小了」。这里实测
    # 峰值，证明后级真的跑了。
    if voice and outcome.get("ok"):
        try:
            import wave

            import numpy as np

            with wave.open(str(sample_path)) as handle:
                rate = handle.getframerate()
                frames = handle.readframes(handle.getnframes())
            pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            peak = 20.0 * float(np.log10(max(float(np.abs(pcm).max()), 1e-9)))
            result["sample_rate"] = rate
            result["peak_dbfs"] = round(peak, 2)
            result["polished"] = bool(-3.5 <= peak <= -0.5)
            if not result["polished"]:
                result["ok"] = False
                result["error"] = f"音频打磨未生效（峰值 {peak:.1f} dBFS）"
        except Exception as exc:  # noqa: BLE001
            result["polished"] = False
            result["ok"] = False
            result["error"] = f"音频打磨不可用：{exc}"

    # Symbol cleaning and the voice profiles are pure Python, so a frozen build
    # could drop them without any visible symptom until a user hears "斜杠".
    try:
        from src.core.textclean import clean_symbols
        from src.core.voices import describe

        cleaned = clean_symbols("路径 /usr/local/bin 以及 A-B 两处")
        result["symbol_cleaning"] = bool(
            cleaned and "/" not in cleaned and "\\" not in cleaned
        )
        result["voice_label"] = describe(voice) if voice else ""
        if not result["symbol_cleaning"]:
            result["ok"] = False
            result["error"] = result.get("error") or "符号清理模块未生效"
    except Exception as exc:
        result["symbol_cleaning"] = False
        result["ok"] = False
        result["error"] = f"符号清理模块不可用：{exc}"
    text = json.dumps(result, ensure_ascii=False)
    print(text)
    Path("/tmp/docreader_selftest.json").write_text(text, encoding="utf-8")
    return 0 if result["ok"] else 1


def diagnose() -> int:
    """冻结包里的语音链路逐段自诊。

    自检用固定文本，一旦命中缓存就成了假阳性——看起来 ok，其实这条链路
    根本没跑。这个入口每次生成新文本、不走缓存，逐段报告。
    """
    from src.core.speech import MIN_AUDIO_DURATION, SpeechEngine, choose_voice, list_voices

    info: dict = {}
    info["version"] = __version__
    info["say"] = os.path.exists("/usr/bin/say")
    info["afconvert"] = os.path.exists("/usr/bin/afconvert")
    try:
        import numpy  # noqa: F401

        info["numpy"] = "ok"
    except Exception as exc:  # noqa: BLE001
        info["numpy"] = f"{type(exc).__name__}: {exc}"

    voices = list_voices()
    info["voices"] = len(voices)
    # 图标是打包时最容易「看起来有、实际没进去」的东西：少了不报错，
    # 只是 Dock 和窗口上光秃秃的。顺手在这里报出来。
    icon = app_icon_path()
    info["icon"] = str(icon) if icon else None
    info["meipass"] = getattr(sys, "_MEIPASS", None)
    voice = choose_voice(voices)
    info["voice"] = voice.identifier if voice else None
    if not voice:
        info["synth_ok"] = False
        print(json.dumps(info, ensure_ascii=False))
        return 1

    stamp = datetime.now().strftime("%H%M%S%f")
    path, duration, error = SpeechEngine(voice, 200).synthesize(
        f"诊断文本 {stamp}，用来确认这条链路真的跑通。"
    )
    info["synth_ok"] = bool(path and duration >= MIN_AUDIO_DURATION)
    info["duration"] = round(duration, 2)
    info["suffix"] = path.suffix if path else ""
    if error:
        info["error"] = error
    if path:
        try:
            import wave

            import numpy as np

            with wave.open(str(path)) as handle:
                rate = handle.getframerate()
                frames = handle.readframes(handle.getnframes())
            pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            info["sample_rate"] = rate
            info["peak_dbfs"] = round(
                20.0 * float(np.log10(max(float(np.abs(pcm).max()), 1e-9))), 2
            )
            info["polished"] = path.suffix == ".wav"
        except Exception as exc:  # noqa: BLE001
            info["polished"] = False
            info["read_error"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(info, ensure_ascii=False))
    return 0 if info.get("synth_ok") and info.get("polished") else 1


def app_icon_path() -> Path | None:
    """窗口图标的位置：开发时在仓库里，打包后在 PyInstaller 的解包目录。

    macOS 的 .app 里，PyInstaller 把 ``--add-data`` 的内容放在
    ``Contents/Resources``，而 ``sys._MEIPASS`` 指向 ``Contents/Frameworks``，
    所以两个位置都要找一遍。Dock 图标由 Info.plist 决定，这里只服务于
    窗口与「关于」面板，找不到不影响运行。
    """
    bases: list[Path] = []
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        bases.append(Path(frozen))
        bases.append(Path(frozen).parent / "Resources")
    bases.append(ROOT)
    for base in bases:
        for name in ("assets/AppIcon.png", "assets/AppIcon.icns"):
            candidate = base / name
            if candidate.exists():
                return candidate
    return None


def main() -> None:
    if os.environ.get("DOCREADER_DIAG") == "1":
        sys.exit(diagnose())
    if os.environ.get("DOCREADER_SELFTEST") == "1":
        sys.exit(self_test())

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from src.ui import theme
    from src.ui.main_window import MainWindow

    QApplication.setApplicationName("文档朗读器")
    QApplication.setOrganizationName("LocalTools")
    QApplication.setApplicationVersion(__version__)
    # Qt 6 起 setApplicationDisplayName 不会自动带上版本号，Dock 菜单和
    # 部分系统面板读的是这个字段，显式写全免得显示成「文档朗读器 0.0.0」。
    QApplication.setApplicationDisplayName(f"文档朗读器 {__version__}")
    app = QApplication(sys.argv)
    icon = app_icon_path()
    # .app 的 Dock 图标由 Info.plist 指定，这条是给 `python src/main.py`
    # 直接跑源码的情况以及窗口/关于面板用的。
    if icon:
        app.setWindowIcon(QIcon(str(icon)))
    app.setStyleSheet(theme.stylesheet(theme.palette(app)))
    window = MainWindow()
    # 主窗口建好后再挂主题钩子，这样 allWidgets() 能覆盖到所有部件；
    # 之后系统切换深浅色时会自动重刷，不用重启。
    theme.apply(app)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
