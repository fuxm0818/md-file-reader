from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SAY = "/usr/bin/say"
AFINFO = "/usr/bin/afinfo"

APP_DIR = Path.home() / "Library" / "Application Support" / "文档朗读器"
CACHE_DIR = APP_DIR / "cache"

# A fixed sample used to measure the real speaking speed of the chosen voice.
CALIBRATION_TEXT = (
    "文档朗读器需要把文字转换成语音，让使用者可以一边查看内容一边收听。"
    "程序会先把整篇文档按句子切开，再根据当前音色的实际语速估算每一句需要的时间。"
    "已经合成过的句子会使用音频的真实时长替换估算值，这样进度条和剩余时间就会越来越准确。"
    "拖动进度条时，程序会把落点吸附到最近的句子边界，然后从那一句重新开始朗读。"
)

DEFAULT_SEC_PER_CHAR = 0.196


@dataclass(frozen=True)
class Voice:
    identifier: str
    locale: str
    sample: str = ""

    @property
    def is_chinese(self) -> bool:
        return self.locale.lower().startswith("zh")

    @property
    def label(self) -> str:
        return f"{self.identifier}  [{self.locale}]"


def cleaned_env() -> dict:
    """PyInstaller rewrites DYLD_* which breaks system binaries in subprocesses."""
    env = os.environ.copy()
    for key in (
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "LD_LIBRARY_PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "_MEIPASS2",
        "_PYI_ARCHIVE_FILE",
    ):
        env.pop(key, None)
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    return env


def _run(
    args: list[str], timeout: int = 120, input_text: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        env=cleaned_env(),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def list_voices() -> list[Voice]:
    try:
        result = _run([SAY, "-v", "?"], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    pattern = re.compile(
        r"^(?P<name>.*?)\s+(?P<locale>[a-zA-Z]{2,3}_[A-Za-z]{2,4})\s+#\s*(?P<sample>.*)$"
    )
    voices: list[Voice] = []
    for line in result.stdout.splitlines():
        m = pattern.match(line.strip())
        if m:
            voices.append(
                Voice(m.group("name").strip(), m.group("locale"), m.group("sample"))
            )
    return voices


def choose_voice(voices: list[Voice], preferred: str = "") -> Voice | None:
    if preferred:
        for voice in voices:
            if voice.identifier == preferred:
                return voice
    chinese = [v for v in voices if v.is_chinese]
    if not chinese:
        return None
    for name in ("Tingting", "Ting-Ting", "Meijia", "Sinji"):
        for voice in chinese:
            if voice.identifier.lower() == name.lower():
                return voice
    mainland = [v for v in chinese if v.locale == "zh_CN"]
    return mainland[0] if mainland else chinese[0]


def probe_duration(path: Path) -> float:
    try:
        result = _run([AFINFO, str(path)], timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    m = re.search(
        r"estimated duration:\s*([0-9]+(?:\.[0-9]+)?)\s*sec", result.stdout, re.I
    )
    if m:
        return float(m.group(1))
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*sec", result.stdout, re.I)
    return float(m.group(1)) if m else 0.0


class SpeechEngine:
    def __init__(self, voice: Voice, rate: int = 200):
        self.voice = voice
        self.rate = max(60, min(400, int(rate)))
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def key(self, text: str) -> str:
        payload = f"{self.voice.identifier}|{self.rate}|{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:24]

    def audio_path(self, text: str) -> Path:
        return CACHE_DIR / (self.key(text) + ".aiff")

    def cached(self, text: str) -> tuple[Path | None, float]:
        path = self.audio_path(text)
        if path.exists() and path.stat().st_size > 100:
            return path, probe_duration(path)
        return None, 0.0

    def synthesize(self, text: str) -> tuple[Path | None, float, str]:
        path, duration = self.cached(text)
        if path:
            return path, duration, ""
        key = self.key(text)
        tmp = CACHE_DIR / (key + ".pending.aiff")
        final = CACHE_DIR / (key + ".aiff")
        if tmp.exists():
            try:
                os.remove(tmp)
            except OSError:
                pass
        try:
            # Feed text through stdin: no temporary text file, safe for worker threads.
            result = _run(
                [
                    SAY,
                    "-v",
                    self.voice.identifier,
                    "-r",
                    str(self.rate),
                    "-f",
                    "-",
                    "-o",
                    str(tmp),
                ],
                input_text=text,
            )
            if result.returncode != 0 or not tmp.exists():
                return None, 0.0, (result.stderr or "语音合成失败").strip()
            os.replace(tmp, final)
            return final, probe_duration(final), ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, 0.0, str(exc)

    def calibrate(self) -> float:
        _, duration, error = self.synthesize(CALIBRATION_TEXT)
        if error or duration <= 0:
            return DEFAULT_SEC_PER_CHAR
        chars = len(re.sub(r"[\s，。！？、；：]", "", CALIBRATION_TEXT))
        return round(duration / max(chars, 1), 4)

    def clear_cache(self) -> int:
        count = 0
        for item in CACHE_DIR.glob("*"):
            try:
                if item.is_file():
                    os.remove(item)
                    count += 1
            except OSError:
                pass
        return count

    @staticmethod
    def cache_size_mb() -> float:
        total = sum(f.stat().st_size for f in CACHE_DIR.glob("*") if f.is_file())
        return round(total / 1024 / 1024, 1)
