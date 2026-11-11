from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SAY = "/usr/bin/say"
AFINFO = "/usr/bin/afinfo"
AFCONVERT = "/usr/bin/afconvert"

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

# v1.4 起固定用婷婷朗读。v1.3 试过 Kokoro 神经语音，客观指标（频宽、底噪）
# 更好，但实听韵律别扭，用户对比后明确选择系统音色，因此神经引擎整套移除。
DEFAULT_VOICE = "Tingting"

# A voice that is listed but whose assets were never downloaded makes `say`
# silently write a ~16 ms empty file (rc=0, no stderr). Reject it explicitly.
MIN_AUDIO_DURATION = 0.2

# 缓存目录的软上限（MB）。设置面板一直写着「上限 500 MB」，但此前只有手动
# 清理，缓存只增不减：听一本长书就能堆到几百兆。现在每合成若干句检查一次。
CACHE_LIMIT_MB = 500

# 检查频率：每合成这么多句才扫一次目录。扫 5000 个文件的 stat 大约几十毫秒，
# 每句都扫会把切句的流畅感磨掉。
CACHE_CHECK_EVERY = 20

# Apple's newer Chinese voices (macOS 15+) are noticeably less robotic than
# the legacy Tingting/Meijia/Sinji set. Their identifiers carry a locale
# suffix, e.g. "Sandy (中文（中国大陆）)".
MODERN_CHINESE = (
    "Sandy", "Eddy", "Shelley", "Reed", "Rocko", "Flo", "Grandma", "Grandpa",
)
LEGACY_CHINESE = ("Tingting", "Ting-Ting", "Meijia", "Sinji")


@dataclass(frozen=True)
class Voice:
    identifier: str
    locale: str
    sample: str = ""

    @property
    def is_chinese(self) -> bool:
        return self.locale.lower().startswith("zh")

    @property
    def is_modern(self) -> bool:
        return any(
            self.identifier.startswith(name + " (") for name in MODERN_CHINESE
        )

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


def list_system_voices() -> list[Voice]:
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


# Kokoro 神经音色在 v1.3 短暂上线过，v1.4 已整体移除。保留这个空壳会让
# 老配置里的 ``zf_001`` 之类的值继续被当成有效音色，所以连入口一起删掉。
def list_voices() -> list[Voice]:
    """Every system voice the machine exposes."""
    return list_system_voices()


def _name_matches(voice: Voice, name: str) -> bool:
    return voice.identifier == name or voice.identifier.startswith(name + " (")


def choose_voice(voices: list[Voice], preferred: str = "") -> Voice | None:
    if preferred:
        for voice in voices:
            if voice.identifier == preferred or _name_matches(voice, preferred):
                return voice
    # 默认婷婷。系统里没有（或被删过）时才退到新一代中文音色。
    for name in (DEFAULT_VOICE,) + MODERN_CHINESE + LEGACY_CHINESE:
        for voice in voices:
            if _name_matches(voice, name):
                return voice
    chinese = [v for v in voices if v.is_chinese]
    if not chinese:
        return None
    mainland = [v for v in chinese if v.locale == "zh_CN"]
    return (mainland or chinese)[0]


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


def _write_wav(path: Path, samples, sample_rate: int) -> None:
    """把打磨后的 float32 波形写成单声道 PCM16，谁都能播。"""
    import wave

    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def _polish_file(source: Path, target: Path) -> bool:
    """把 ``say`` 写出的 aiff 打磨成 wav，失败返回 False 交给调用方兜底。

    ``say`` 的输出峰值只有 -3 dBFS 左右、整体电平 -18 dBFS，直接播偏小；
    打磨后大约提 3 dB，且首尾不再有切换爆音。
    """
    import wave

    import numpy as np

    from .loudness import polish

    converted = target.with_name(target.stem + ".conv.wav")
    try:
        result = _run(
            [AFCONVERT, "-f", "WAVE", "-d", "LEI16", str(source), str(converted)],
            timeout=60,
        )
        if result.returncode != 0 or not converted.exists():
            return False
        with wave.open(str(converted)) as handle:
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return False
        # 不裁尾：句末停顿是 render() 用 [[slnc]] 写在音频里的，裁掉会连读。
        _write_wav(target, polish(samples, rate, trim=False), rate)
        return True
    except Exception:  # noqa: BLE001 - 打磨是增强项，任何异常都降级
        return False
    finally:
        if converted.exists():
            try:
                os.remove(converted)
            except OSError:
                pass


class SpeechEngine:
    def __init__(self, voice: Voice, rate: int = 200, cache_limit_mb: int = CACHE_LIMIT_MB):
        self.voice = voice
        self.rate = max(60, min(400, int(rate)))
        self.cache_limit_mb = max(0, int(cache_limit_mb))
        self._writes_since_check = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def suffix(self) -> str:
        return ".wav"

    def key(self, text: str) -> str:
        payload = f"{self.voice.identifier}|{self.rate}|{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:24]

    def audio_path(self, text: str) -> Path:
        return CACHE_DIR / (self.key(text) + self.suffix)

    def cached(self, text: str) -> tuple[Path | None, float]:
        path = self.audio_path(text)
        if path.exists() and path.stat().st_size > 100:
            duration = probe_duration(path)
            if duration >= MIN_AUDIO_DURATION:
                return path, duration
        return None, 0.0

    def synthesize(self, text: str) -> tuple[Path | None, float, str]:
        path, duration = self.cached(text)
        if path:
            return path, duration, ""
        return self._synthesise_say(text, self.audio_path(text))

    def _synthesise_say(self, text: str, final: Path) -> tuple[Path | None, float, str]:
        """``say`` 合成 → 响度打磨 → 写出 wav。

        ``say`` 只能写 aiff/caf，所以先落到临时 aiff，再用 afconvert 转成
        可读的 PCM，打磨后存成 wav。缓存文件因此不再依赖系统音频容器，
        迁移到别的机器上也能直接播。
        """
        raw = final.with_name(final.stem + ".raw.aiff")
        for stale in (raw, final):
            if stale.exists():
                try:
                    os.remove(stale)
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
                    str(raw),
                ],
                input_text=text,
            )
            if result.returncode != 0 or not raw.exists():
                return None, 0.0, (result.stderr or "语音合成失败").strip()
            if not _polish_file(raw, final):
                # 打磨是锦上添花：numpy 或 afconvert 出问题时，宁可少几个
                # dB 的音量，也不能让整本书读不下去。
                os.replace(raw, final)
            elif raw.exists():
                try:
                    os.remove(raw)
                except OSError:
                    pass
            duration = probe_duration(final)
            if duration < MIN_AUDIO_DURATION:
                # Listed-but-not-downloaded voice: drop the empty file so the
                # controller can fall back to a usable one.
                try:
                    os.remove(final)
                except OSError:
                    pass
                return None, 0.0, f"EMPTY_AUDIO:{self.voice.identifier}"
            self._note_write()
            return final, duration, ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, 0.0, str(exc)

    def calibrate(self) -> float:
        _, duration, error = self.synthesize(CALIBRATION_TEXT)
        if error or duration <= 0:
            return DEFAULT_SEC_PER_CHAR
        chars = len(re.sub(r"[\s，。！？、；：]", "", CALIBRATION_TEXT))
        return round(duration / max(chars, 1), 4)

    def _note_write(self) -> None:
        """新音频落盘后按频率触发一次淘汰。"""
        self._writes_since_check += 1
        if self._writes_since_check >= CACHE_CHECK_EVERY:
            self._writes_since_check = 0
            self.enforce_cache_limit()

    def enforce_cache_limit(self) -> int:
        """超过上限时按最后修改时间删最旧的文件，返回删除数量。

        删到上限的 85% 而不是刚好卡在上限：留出余量，否则下一句合成完又要
        重扫一遍目录，变成每句都淘汰一次。正在播的那句永远是最新的，按
        mtime 升序删不会动到它。
        """
        limit_mb = self.cache_limit_mb
        if limit_mb <= 0:
            return 0
        try:
            entries = [
                (item.stat().st_mtime, item.stat().st_size, item)
                for item in CACHE_DIR.iterdir()
                if item.is_file()
            ]
        except OSError:
            return 0
        total = sum(size for _, size, _ in entries)
        limit = limit_mb * 1024 * 1024
        if total <= limit:
            return 0
        target = int(limit * 0.85)
        removed = 0
        for _, size, item in sorted(entries, key=lambda e: e[0]):
            if total <= target:
                break
            try:
                item.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        return removed

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
