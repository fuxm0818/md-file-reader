from __future__ import annotations

import os
import random
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .core.models import Document
from .core.oralizer import oralize, oralize_enabled
from .core.parsers import parse
from .core.prosody import LEVEL_LABELS, pause_budget, render, sanitize
from .core.speech import (
    CACHE_LIMIT_MB,
    MIN_AUDIO_DURATION,
    SpeechEngine,
    choose_voice,
    list_voices,
)
from .core.store import Store
from .core.textclean import clean_symbols
from .core.timeline import PAUSE, Timeline
from .core.voices import describe

PREVIEW_TEXT = (
    "文档本身没有时间轴，所以程序按语速把字数换算成时间。"
    "已经读过的句子会用真实时长替换估算值，剩余时间会越听越准。"
)

# 缓存键格式或音频容器变了就 +1，升级时会清一次旧缓存。
CACHE_SCHEMA = 2


class _PrefetchSignals(QObject):
    done = Signal(int, str, float, str)


class _Prefetch(QRunnable):
    def __init__(self, engine, index, text, signals):
        super().__init__()
        self.engine = engine
        self.index = index
        self.text = text
        self.signals = signals

    def run(self):
        try:
            path, duration, error = self.engine.synthesize(self.text)
            self.signals.done.emit(
                self.index, str(path) if path else "", duration, error
            )
        except Exception as exc:
            # 退出时留在线程池里的任务会走到这里：信号对象已随窗口销毁，
            # emit 本身抛 RuntimeError。任务已经没人要了，静默收场即可。
            try:
                self.signals.done.emit(self.index, "", 0.0, str(exc))
            except RuntimeError:
                pass


class _EstimateSignals(QObject):
    done = Signal()
    failed = Signal(str)


class _Estimate(QRunnable):
    def __init__(self, store, sec_per_char, signals, pause: float = PAUSE):
        super().__init__()
        self.store = store
        self.sec_per_char = sec_per_char
        self.pause = pause
        self.signals = signals

    def run(self):
        try:
            self._estimate()
        except Exception as exc:
            self.signals.failed.emit(f"列表时长估算失败：{exc}")

    def _estimate(self) -> None:
        changed = False
        for item in list(self.store.items):
            path = item["path"]
            try:
                stat = os.stat(path)
                signature = f"{path}|{stat.st_mtime_ns}|{stat.st_size}"
            except OSError:
                signature = f"{path}|missing"
            if item.get("est_hash") == signature:
                continue
            try:
                doc = parse(path, True)
                if doc.ok:
                    item["est_seconds"] = round(
                        sum(s.char_count * self.sec_per_char + self.pause for s in doc.sentences), 1
                    )
                    item["error"] = ""
                    if item.get("status") == "error":
                        item["status"] = "pending"
                else:
                    item["est_seconds"] = 0
                    item["error"] = doc.error
                    item["status"] = "error"
                item["est_hash"] = signature
                changed = True
            except Exception as exc:
                item["error"] = str(exc)
                changed = True
        if changed:
            self.store.save()
            self.signals.done.emit()


class ReaderController(QObject):
    documentLoaded = Signal(object)
    listChanged = Signal()
    positionChanged = Signal(float, float, float, int, int)
    sentenceChanged = Signal(int)
    stateChanged = Signal(bool)
    itemChanged = Signal(int)
    message = Signal(str)
    settingsChanged = Signal()

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.settings = store.settings

        self.voices = list_voices()
        self.voice = choose_voice(self.voices, self.settings.get("voice", ""))
        self.rate = int(self.settings.get("rate", 200))
        self.engine: SpeechEngine | None = None
        self.sec_per_char = 0.196
        self.startup_message = ""
        self._preview_player: tuple | None = None
        if self.voice:
            self.engine = self._make_engine(self.voice)
            self._migrate_cache()
            self._ensure_usable_voice()
            self.sec_per_char = self._calibration()
            self.settings["voice"] = self.voice.identifier
            self.store.save()

        self.audio = QAudioOutput(self)
        self.audio.setVolume(max(0.0, min(1.0, self.settings.get("volume", 80) / 100)))
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_player_error)

        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(2)
        self.prefetch_signals = _PrefetchSignals()
        self.prefetch_signals.done.connect(self._on_prefetched)
        self.estimate_signals = _EstimateSignals()
        self.estimate_signals.done.connect(self.listChanged)
        self.estimate_signals.failed.connect(self.message)
        self._inflight: set[int] = set()
        self._pending_load: tuple[int, bool] | None = None

        self.doc: Document | None = None
        self.timeline: Timeline | None = None
        self.current_item = -1
        self.sentence_index = 0
        self.playing = False
        self._advancing = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(150)

    # ---------------------------------------------------------------- setup
    def _make_engine(self, voice) -> SpeechEngine:
        """建引擎的统一入口：缓存上限从设置里读，各处新建都走同一份。"""
        return SpeechEngine(
            voice,
            self.rate,
            cache_limit_mb=int(self.settings.get("cache_limit_mb", CACHE_LIMIT_MB)),
        )

    def _migrate_cache(self) -> None:
        """v1.4 换了缓存键格式与音频容器，旧文件永远不会再被命中。

        不清的话，升级后硬盘上会留下一堆几十 MB 的死音频。做一次性清理，
        用版本号守住，别每次启动都删。
        """
        if int(self.settings.get("cache_schema", 0)) >= CACHE_SCHEMA:
            return
        removed = self.engine.clear_cache() if self.engine else 0
        self.settings["cache_schema"] = CACHE_SCHEMA
        self.store.save()
        if removed:
            self.startup_message = f"已清理 {removed} 个旧版音频缓存，音色换成婷婷"

    def _ensure_usable_voice(self) -> bool:
        """A listed voice may have no downloaded assets: ``say`` then writes a
        silent 16 ms file with rc=0. Probe once and fall back automatically.

        Returns True when the voice was actually switched.
        """
        if not self.engine or not self.voice:
            return False
        tried = {self.voice.identifier}
        switched = False
        for _ in range(len(self.voices) + 1):
            _, duration, error = self.engine.synthesize("语音测试。")
            if duration >= MIN_AUDIO_DURATION and not error:
                return switched
            candidates = [
                v
                for v in self.voices
                if v.is_chinese and v.identifier not in tried
            ]
            if not candidates:
                self.startup_message = "本机中文音色资源不可用，请到系统设置下载中文音色"
                return switched
            failed = error.rsplit(":", 1)[-1] or "原音色"
            nxt = candidates[0]
            tried.add(nxt.identifier)
            self.voice = nxt
            self.engine = self._make_engine(nxt)
            self.settings["voice"] = nxt.identifier
            self.startup_message = f"音色 {failed} 没有声音资源，已切换到 {nxt.identifier}"
            switched = True
        return switched

    def _prosody_level(self) -> int:
        return max(0, min(3, int(self.settings.get("prosody_level", 2))))

    def _pause(self) -> float:
        return PAUSE + pause_budget(self._prosody_level())

    def _speech_text(self, index: int) -> str:
        """Build the synthesis copy for one sentence.

        The visible document and its sentence spans are never modified; only
        this copy is rewritten, so highlighting and seek stay in sync.
        """
        assert self.doc is not None
        sentence = self.doc.sentences[index]
        raw = sanitize(sentence.text)
        if self.settings.get("clean_symbols", True):
            # Symbol noise (paths, bullets, table pipes) is read out loud by
            # `say`; strip it before any prose rewriting. Empty means the
            # sentence carried nothing but decoration - keep the original so
            # the sentence never turns into silence.
            cleaned = clean_symbols(raw)
            raw = cleaned or raw
        text = (
            oralize(raw)
            if oralize_enabled(self.doc.path, bool(self.settings.get("oralize", True)))
            else raw
        )
        sentences = self.doc.sentences
        para_end = (
            index + 1 >= len(sentences)
            or sentences[index + 1].para != sentence.para
        )
        para_start = index == 0 or sentences[index - 1].para != sentence.para
        return render(
            text,
            self._prosody_level(),
            self.rate,
            is_para_end=para_end,
            is_para_start=para_start,
        )

    def _calibration(self) -> float:
        assert self.engine and self.voice
        key = f"{self.voice.identifier}|{self.rate}"
        cache = self.settings.setdefault("calibrations", {})
        if key in cache:
            return float(cache[key])
        value = self.engine.calibrate()
        cache[key] = value
        self.store.save()
        return value

    def has_chinese_voice(self) -> bool:
        return self.voice is not None

    def estimate_durations(self) -> None:
        self.pool.start(
            _Estimate(self.store, self.sec_per_char, self.estimate_signals, self._pause())
        )

    # ------------------------------------------------------------- documents
    def select_item(self, index: int, auto_play: bool = True) -> None:
        items = self.store.items
        if not items:
            self.stop()
            return
        index = max(0, min(index, len(items) - 1))
        self.current_item = index
        item = items[index]
        doc = parse(item["path"], bool(self.settings.get("skip_code", True)))
        if not doc.ok:
            item["status"] = "error"
            item["error"] = doc.error
            self.store.save()
            self.message.emit(f"跳过 {Path(item['path']).name}：{doc.error}")
            self.listChanged.emit()
            QTimer.singleShot(60, lambda: self._next_item(auto=True))
            return

        self.doc = doc
        self.timeline = Timeline(doc, self.sec_per_char, self._pause())
        previous_hash = item.get("doc_hash", "")
        item["doc_hash"] = doc.doc_hash
        item["status"] = "reading"
        item["error"] = ""
        item["est_seconds"] = round(self.timeline.total(), 1)
        self.store.data["last_item_path"] = item["path"]
        self.store.save()

        start = 0
        if bool(self.settings.get("auto_resume", True)):
            bookmark = self.store.get_bookmark(doc.doc_hash)
            if previous_hash and previous_hash != doc.doc_hash:
                self.message.emit("文档内容已变化，原断点失效，将从头开始")
            elif bookmark and bookmark.get("path") == item["path"]:
                start = max(0, int(bookmark.get("sentence", 0)) - 1)
            elif previous_hash == doc.doc_hash and item.get("position"):
                start = max(0, int(item["position"]) - 1)

        self.sentence_index = max(0, min(start, len(doc.sentences) - 1))
        self._inflight.clear()
        self.documentLoaded.emit(doc)
        self.itemChanged.emit(index)
        self.listChanged.emit()
        self.sentenceChanged.emit(self.sentence_index)
        self._prefetch(self.sentence_index, self.sentence_index + 1)
        self._load_sentence(self.sentence_index, play=auto_play)
        self.message.emit(
            f"{doc.title} · {len(doc.sentences)} 句 · 约 {self._fmt(self.timeline.total())}"
        )

    def restore_session(self) -> None:
        items = self.store.items
        if not items:
            self.message.emit("把文档拖进左侧列表，或点「添加文件」开始")
            self.listChanged.emit()
            return
        last = self.store.data.get("last_item_path", "")
        index = next((i for i, it in enumerate(items) if it["path"] == last), 0)
        self.select_item(index, auto_play=False)
        self.estimate_durations()
        self.message.emit("已恢复上次位置，点播放继续")
        if self.startup_message:
            self.message.emit(self.startup_message)

    # -------------------------------------------------------------- playback
    def _load_sentence(self, index: int, play: bool = True) -> None:
        if not self.doc or not self.timeline or not self.engine:
            self.message.emit("当前系统没有可用的中文语音，请在设置中检查")
            return
        if not self.doc.sentences:
            return
        index = max(0, min(index, len(self.doc.sentences) - 1))
        self.sentence_index = index
        self._advancing = False
        text = self._speech_text(index)
        cached_path, cached_duration = self.engine.cached(text)
        if not cached_path:
            # 合成一句要几十到几百毫秒。在主线程里等会把界面冻住，
            # 所以先挂起，交给线程池合成，完成后再回来播。
            if index not in self._inflight:
                self._inflight.add(index)
                self.pool.start(
                    _Prefetch(self.engine, index, text, self.prefetch_signals)
                )
            self._pending_load = (index, play)
            self.message.emit("正在合成这一句…")
            return
        # 命中缓存就直接用，不要再走一次 synthesize：它内部还会 cached()
        # 一遍，等于每句多跑一次 afinfo 子进程。
        path, duration, error = cached_path, cached_duration, ""
        if not path:
            if error.startswith("EMPTY_AUDIO:") and self._ensure_usable_voice():
                self.message.emit(self.startup_message)
                self._load_sentence(index, play=play)
                return
            self.message.emit(f"语音合成失败：{error}")
            return
        self.timeline.set_real(index, duration)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        if play:
            self.player.play()
            self.playing = True
        else:
            self.player.stop()
            self.playing = False
        self.stateChanged.emit(self.playing)
        self.sentenceChanged.emit(index)
        self._save_bookmark(index)
        self._prefetch(index + 1, index + 2, index + 3)

    def _prefetch(self, *indices: int) -> None:
        if not self.doc or not self.engine:
            return
        for index in indices:
            if index < 0 or index >= len(self.doc.sentences) or index in self._inflight:
                continue
            text = self._speech_text(index)
            cached_path, cached_duration = self.engine.cached(text)
            if cached_path:
                if self.timeline and cached_duration > 0:
                    self.timeline.set_real(index, cached_duration)
                continue
            self._inflight.add(index)
            self.pool.start(
                _Prefetch(self.engine, index, text, self.prefetch_signals)
            )

    def _on_prefetched(self, index: int, path: str, duration: float, error: str) -> None:
        self._inflight.discard(index)
        if self.timeline and duration > 0 and self.doc and index < len(self.doc.sentences):
            self.timeline.set_real(index, duration)
        pending = self._pending_load
        if pending and pending[0] == index:
            self._pending_load = None
            if error or not path:
                self.message.emit(f"语音合成失败：{error or '没有音频'}")
                return
            self._load_sentence(index, play=pending[1])

    def _on_media_status(self, status) -> None:
        if (
            status == QMediaPlayer.MediaStatus.EndOfMedia
            and self.playing
            and not self._advancing
        ):
            self._advancing = True
            QTimer.singleShot(0, self._advance)

    def _on_player_error(self, error, text: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self.message.emit(f"播放错误：{text}")

    def _advance(self) -> None:
        if not self.doc or not self.playing:
            return
        if self.sentence_index + 1 < len(self.doc.sentences):
            self._load_sentence(self.sentence_index + 1)
            return
        items = self.store.items
        if 0 <= self.current_item < len(items):
            items[self.current_item]["status"] = "done"
            self.store.save()
            self.listChanged.emit()
        mode = self.settings.get("mode", "sequence")
        if mode == "loop_one":
            self._load_sentence(0)
        else:
            self._next_item(auto=True)

    def _tick(self) -> None:
        if not self.timeline or not self.doc:
            self.positionChanged.emit(0.0, 0.0, 0.0, 0, 0)
            return
        offset = self.player.position() / 1000.0 if self.playing else 0.0
        if not self.playing and self.player.playbackState() == QMediaPlayer.PlaybackState.PausedState:
            offset = self.player.position() / 1000.0
        current = self.timeline.start_of(self.sentence_index) + offset
        total = self.timeline.total()
        self.positionChanged.emit(
            current,
            total,
            self.timeline.fraction_at(current),
            self.sentence_index,
            len(self.doc.sentences),
        )

    # ---------------------------------------------------------- public calls
    def play_pause(self) -> None:
        if not self.doc:
            if self.store.items:
                self.select_item(max(0, self.current_item), auto_play=True)
            else:
                self.message.emit("播放列表是空的")
            return
        if self.playing:
            self.player.pause()
            self.playing = False
            self.stateChanged.emit(False)
        else:
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia:
                self._load_sentence(self.sentence_index, play=True)
            else:
                self.player.play()
                self.playing = True
                self.stateChanged.emit(True)

    def stop(self) -> None:
        self.player.stop()
        self.playing = False
        self.stateChanged.emit(False)

    def toggle_play(self) -> None:
        self.play_pause()

    def seek_fraction(self, fraction: float) -> None:
        if not self.timeline:
            return
        target = self.timeline.time_at_fraction(fraction)
        index = self.timeline.sentence_at(target)
        self._load_sentence(index, play=self.playing)
        self.message.emit(f"跳到第 {index + 1} 句")

    def seek_sentence(self, index: int) -> None:
        self._load_sentence(index, play=True)
        self.message.emit(f"从第 {index + 1} 句开始朗读")

    def skip_seconds(self, delta: float) -> None:
        if not self.timeline:
            return
        offset = self.player.position() / 1000.0
        current = self.timeline.start_of(self.sentence_index) + offset
        target = max(0.0, current + delta)
        index = self.timeline.sentence_at(target)
        if index != self.sentence_index:
            self._load_sentence(index, play=self.playing)
        else:
            local = max(0.0, target - self.timeline.start_of(index))
            self.player.setPosition(int(local * 1000))

    def next_sentence(self) -> None:
        if self.doc:
            self._load_sentence(self.sentence_index + 1, play=self.playing)

    def prev_sentence(self) -> None:
        if self.doc:
            self._load_sentence(self.sentence_index - 1, play=self.playing)

    def next_item(self) -> None:
        self._next_item(auto=False)

    def prev_item(self) -> None:
        items = self.store.items
        if not items:
            return
        self.select_item((self.current_item - 1) % len(items), auto_play=self.playing)

    def _next_item(self, auto: bool) -> None:
        items = self.store.items
        if not items:
            self.stop()
            return
        mode = self.settings.get("mode", "sequence")
        if mode == "shuffle" and len(items) > 1:
            choices = [i for i in range(len(items)) if i != self.current_item]
            target = random.choice(choices)
        else:
            target = self.current_item + 1
            if target >= len(items):
                if mode == "loop_all":
                    target = 0
                elif auto:
                    self.stop()
                    self.message.emit("列表播放完毕")
                    return
                else:
                    target = len(items) - 1
        self.select_item(target, auto_play=auto or self.playing)

    # ------------------------------------------------------------- settings
    def _rebuild_for_voice(self) -> None:
        if not self.voice:
            return
        self.engine = self._make_engine(self.voice)
        self.sec_per_char = self._calibration()
        if self.doc:
            index = self.sentence_index
            self.timeline = Timeline(self.doc, self.sec_per_char, self._pause())
            self._inflight.clear()
            self._prefetch(index, index + 1)
            self._load_sentence(index, play=self.playing)
        self.settingsChanged.emit()

    def set_voice(self, identifier: str) -> None:
        for voice in self.voices:
            if voice.identifier == identifier:
                self.voice = voice
                self.settings["voice"] = identifier
                self.store.save()
                self._rebuild_for_voice()
                return

    def set_rate(self, rate: int) -> None:
        self.rate = max(80, min(350, int(rate)))
        self.settings["rate"] = self.rate
        self.store.save()
        self._rebuild_for_voice()
        self.message.emit(f"语速 {self.rate} 字/分，已重新标定")

    def set_volume(self, value: int) -> None:
        self.audio.setVolume(max(0.0, min(1.0, value / 100)))
        self.settings["volume"] = value
        self.store.save()

    def set_oralize(self, enabled: bool) -> None:
        self.settings["oralize"] = bool(enabled)
        self.store.save()
        self._rebuild_for_voice()
        self.message.emit("口语优化已开启" if enabled else "口语优化已关闭，按原文朗读")

    def set_prosody_level(self, level: int) -> None:
        self.settings["prosody_level"] = max(0, min(3, int(level)))
        self.store.save()
        self._rebuild_for_voice()
        self.message.emit(f"朗读节奏：{LEVEL_LABELS[self._prosody_level()]}")

    def preview_voice(self, identifier: str = "") -> None:
        """Play a short sample; never disturbs playback.

        ``identifier`` lets the voice browser audition any voice without
        changing the saved setting first.
        """
        voice = self.voice
        if identifier:
            voice = next((v for v in self.voices if v.identifier == identifier), None)
            if voice is None:
                self.message.emit("这个音色已不在系统里了")
                return
        if not voice:
            self.message.emit("本机没有可用的朗读音色")
            return
        engine = self.engine if voice is self.voice else self._make_engine(voice)
        if engine is None:
            self.message.emit("本机没有可用的朗读音色")
            return
        text = PREVIEW_TEXT
        if self.settings.get("clean_symbols", True):
            text = clean_symbols(text) or text
        if self.settings.get("oralize", True):
            text = oralize(text) or text
        rendered = render(text, self._prosody_level(), self.rate, is_para_end=True)
        path, _, error = engine.synthesize(rendered)
        if not path:
            if error.startswith("EMPTY_AUDIO:"):
                self.message.emit(
                    f"{voice.identifier} 只注册没有下载，按系统设置提示下载后再试"
                )
            else:
                self.message.emit(f"试听失败：{error}")
            return
        # Reuse one preview player for the whole session. Allocating a new
        # QMediaPlayer per audition left the previous one alive as a child of
        # the controller, so auditioning several voices in a row stacked their
        # audio on top of each other.
        if self._preview_player is None:
            output = QAudioOutput(self)
            player = QMediaPlayer(self)
            player.setAudioOutput(output)
            self._preview_player = (player, output)
        player, output = self._preview_player
        output.setVolume(self.audio.volume())
        player.stop()
        player.setSource(QUrl())
        player.setSource(QUrl.fromLocalFile(str(path)))
        player.play()
        from .core.voices import describe

        self.message.emit(
            f"正在试听 {describe(voice)} · {LEVEL_LABELS[self._prosody_level()]}"
        )

    def set_symbol_cleaning(self, enabled: bool) -> None:
        self.settings["clean_symbols"] = bool(enabled)
        self.store.save()
        self._rebuild_for_voice()
        self.message.emit(
            "已跳过斜杠、破折号这类符号" if enabled else "符号按原样送去朗读"
        )

    def set_mode(self, mode: str) -> None:
        self.settings["mode"] = mode
        self.store.save()

    def set_auto_scroll(self, enabled: bool) -> None:
        self.settings["auto_scroll"] = enabled
        self.store.save()

    def set_skip_code(self, enabled: bool) -> None:
        self.settings["skip_code"] = enabled
        self.store.save()

    # -------------------------------------------------------------- helpers
    def _save_bookmark(self, index: int) -> None:
        if self.doc and 0 <= self.current_item < len(self.store.items):
            item = self.store.items[self.current_item]
            self.store.bookmark(self.doc.doc_hash, item["path"], index)

    def reset(self) -> None:
        self.stop()
        self.doc = None
        self.timeline = None
        self.current_item = -1
        self.sentence_index = 0
        self._inflight.clear()
        self.positionChanged.emit(0.0, 0.0, 0.0, 0, 0)

    def set_auto_resume(self, enabled: bool) -> None:
        self.settings["auto_resume"] = enabled
        self.store.save()

    def save_session(self) -> None:
        self._save_bookmark(self.sentence_index)
        self.store.save()

    def shutdown(self) -> None:
        self.timer.stop()
        if self._preview_player:
            try:
                self._preview_player[0].stop()
            except RuntimeError:
                pass
            self._preview_player = None
        self.player.stop()
        self.playing = False
        self.save_session()
        # 合成一句要 0.9 s 上下（say 占大头），队列里通常还有两三句。等 1 秒
        # 会让剩下的任务在窗口销毁后继续跑，既写缓存又对着死信号 emit。
        self.pool.waitForDone(6000)

    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
