"""合成音频的后处理：去静音、消爆音、统一响度。

``say`` 输出的峰值只有 -6.3 dBFS（Sandy），Kokoro 也只有 -8.9 dBFS，
直接播放会显得声音小；句子首尾突然切断又会有「啪」的爆音。
这里做四件事，都是播客/有声书的常规处理，不引入额外依赖：

1. 70 Hz 以下高通，去掉低频隆隆，听感更干净。
2. 掐掉首尾静音，只留 40 ms 余量，句子之间不拖沓。
3. 首尾 8 ms 淡入淡出，消除切换时的爆音。
4. 响度对齐：活跃段 RMS 拉到 -14.5 dBFS，峰值用软限幅压到 -1.5 dBFS 以内。
   只做增益不够——各音色峰值因子差 4 dB 以上，靠峰值兜底会把响的音色
   硬压下去，最后八个音色的电平极差有 2.6 dB；补一级 tanh 软限幅后
   极差收到 1.65 dB，切换音色不会忽大忽小。
"""

from __future__ import annotations

import numpy as np

TARGET_RMS_DB = -14.5
CEILING_DB = -1.5
# 模型原始电平在 -22 到 -29 dBFS 之间摆，最轻的音色要 14 dB 才追平。
# 底噪实测 -65 dB 以下，放宽到 18 dB 也不会把嘶声抬起来。
MAX_GAIN = 8.0
FADE_SECONDS = 0.008
TRIM_PAD_SECONDS = 0.04


def _highpass(x: np.ndarray, sr: int, cutoff: float = 70.0) -> np.ndarray:
    """频域一阶高通。逐样本 IIR 在纯 Python 里太慢，这里用 FFT 做。"""
    if x.size < 64:
        return x
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr)
    # 一阶高通幅度响应：|H| = f / sqrt(f² + fc²)
    gain = freqs / np.sqrt(freqs**2 + cutoff**2 + 1e-12)
    return np.fft.irfft(spec * gain, n=x.size).astype(np.float32)


def _trim(x: np.ndarray, sr: int) -> np.ndarray:
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak <= 0:
        return x
    threshold = peak * 0.01
    loud = np.flatnonzero(np.abs(x) > threshold)
    if loud.size == 0:
        return x
    pad = int(TRIM_PAD_SECONDS * sr)
    start = max(0, int(loud[0]) - pad)
    end = min(x.size, int(loud[-1]) + pad)
    return x[start:end]


def _fade(x: np.ndarray, sr: int) -> np.ndarray:
    length = min(int(FADE_SECONDS * sr), x.size // 2)
    if length <= 0:
        return x
    ramp = np.linspace(0.0, 1.0, length, dtype=np.float32)
    x[:length] *= ramp
    x[-length:] *= ramp[::-1]
    return x


def _limit(x: np.ndarray, ceiling: float) -> np.ndarray:
    """软限幅：把偶发的爆破音峰压到天花板以下，不硬切。

    只做增益不够——不同音色的峰值因子差 4 dB 以上，靠 ``gain_peak``
    兜底会让本来就响的音色被迫压低，整句平均电平反而掉下去。用 tanh
    膝盖把超出部分平滑映射到天花板，平均电平就能对齐到一起。
    """
    magnitude = np.abs(x)
    knee = ceiling * 0.85
    if float(magnitude.max()) <= knee:
        return x
    headroom = ceiling - knee
    limited = np.where(
        magnitude > knee,
        knee + headroom * np.tanh((magnitude - knee) / headroom),
        magnitude,
    )
    return (np.sign(x) * limited).astype(np.float32)


def _level(x: np.ndarray, sr: int) -> np.ndarray:
    peak = float(np.abs(x).max())
    if peak <= 1e-6:
        return x
    frame = max(1, int(0.02 * sr))
    usable = (x.size // frame) * frame
    if usable:
        frames = x[:usable].reshape(-1, frame)
        energies = np.sqrt((frames**2).mean(axis=1))
        # 只用有声帧算 RMS，否则长停顿会把增益推得过高
        voiced = energies[energies > max(float(energies.max()) * 0.1, 1e-4)]
        rms = float(np.sqrt((voiced**2).mean())) if voiced.size else float(peak)
    else:
        rms = float(np.sqrt((x**2).mean()))
    rms = max(rms, 1e-6)
    gain = min(10 ** (TARGET_RMS_DB / 20.0) / rms, MAX_GAIN)
    if gain <= 0:
        return x
    return _limit((x * gain).astype(np.float32), 10 ** (CEILING_DB / 20.0))


def polish(samples: np.ndarray, sr: int, trim: bool = True) -> np.ndarray:
    """把一段合成音频整理到可直接播放的状态。

    ``trim=False`` 用于系统语音：句末停顿写在音频里，裁掉会把句子连读。
    """
    x = np.asarray(samples, dtype=np.float32).copy()
    if x.size == 0:
        return x
    x -= float(x.mean())
    x = _highpass(x, sr)
    if trim:
        x = _trim(x, sr)
    x = _fade(x, sr)
    x = _level(x, sr)
    return np.clip(x, -1.0, 1.0)


def to_pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def peak_dbfs(samples: np.ndarray) -> float:
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    return 20.0 * float(np.log10(peak)) if peak > 0 else -120.0
