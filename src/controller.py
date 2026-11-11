from __future__ import annotations

import os
import random
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from .core.models import Document
from .core.parsers import parse
from .core.speech import SpeechEngine, choose_voice, list_voices
from .core.store import Store
from .core.timeline import Timeline


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
            self.signals.done.emit(self.index, "", 0.0, str(exc))


class _EstimateSignals(QObject):
    done = Signal()
    failed = Signal(str)


class _Estimate(QRunnable):
    def __init__(self, store, sec_per_char, signals):
        super().__init__()
        self.store = store
        self.sec_per_char = sec_per_char
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
                        sum(s.char_count * self.sec_per_char + 0.18 for s in doc.sentences), 1
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
        if self.voice:
            self.engine = SpeechEngine(self.voice, self.rate)
            self.sec_per_char = self._calibration()
            self.settings["voice"] = self.voice.identifier

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
        self.pool.start(_Estimate(self.store, self.sec_per_char, self.estimate_signals))

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
        self.timeline = Timeline(doc, self.sec_per_char)
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
        text = self.doc.sentences[index].text
        path, duration, error = self.engine.synthesize(text)
        if not path:
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
            text = self.doc.sentences[index].text
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
        self.engine = SpeechEngine(self.voice, self.rate)
        self.sec_per_char = self._calibration()
        if self.doc:
            index = self.sentence_index
            self.timeline = Timeline(self.doc, self.sec_per_char)
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
        self.player.stop()
        self.playing = False
        self.save_session()
        self.pool.waitForDone(1000)

    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
