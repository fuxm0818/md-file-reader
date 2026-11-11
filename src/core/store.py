from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from .speech import APP_DIR

STATE_FILE = APP_DIR / "state.json"

DEFAULT_SETTINGS = {
    "voice": "",
    "rate": 200,
    "volume": 80,
    "mode": "sequence",  # sequence | loop_all | loop_one | shuffle
    "auto_scroll": True,
    "skip_code": True,
    "auto_resume": True,
    "oralize": True,           # 文档 → 口播稿（技术类文档自动关闭）
    "prosody_level": 2,        # 0 关闭 / 1 轻 / 2 标准 / 3 强
    "calibrations": {},
    "cache_limit_mb": 500,
}

MODES = {
    "sequence": "顺序播放",
    "loop_all": "列表循环",
    "loop_one": "单项循环",
    "shuffle": "随机播放",
}


def new_item(path: str) -> dict:
    return {
        "path": path,
        "position": 0,
        "doc_hash": "",
        "status": "pending",  # pending | reading | done | error
        "error": "",
    }


class Store:
    def __init__(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            if STATE_FILE.exists():
                self.data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        if not isinstance(self.data, dict):
            self.data = {}
        self.data.setdefault(
            "playlists",
            [{"id": "default", "name": "默认列表", "items": []}],
        )
        self.data.setdefault("active_playlist_id", "default")
        self.data.setdefault("last_item_path", "")
        settings = self.data.setdefault("settings", {})
        for key, value in DEFAULT_SETTINGS.items():
            settings.setdefault(key, value)
        self.data.setdefault("bookmarks", {})

    def save(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, STATE_FILE)
        except OSError:
            pass

    @property
    def settings(self) -> dict:
        return self.data["settings"]

    @property
    def playlists(self) -> list[dict]:
        return self.data["playlists"]

    @property
    def active(self) -> dict:
        for playlist in self.playlists:
            if playlist["id"] == self.data["active_playlist_id"]:
                return playlist
        self.data["active_playlist_id"] = self.playlists[0]["id"]
        return self.playlists[0]

    @property
    def items(self) -> list[dict]:
        return self.active["items"]

    def set_active(self, playlist_id: str) -> None:
        self.data["active_playlist_id"] = playlist_id
        self.save()

    def create_playlist(self, name: str) -> dict:
        playlist = {"id": uuid.uuid4().hex[:8], "name": name, "items": []}
        self.playlists.append(playlist)
        self.data["active_playlist_id"] = playlist["id"]
        self.save()
        return playlist

    def rename_playlist(self, name: str) -> None:
        self.active["name"] = name
        self.save()

    def delete_active_playlist(self) -> None:
        if len(self.playlists) <= 1:
            self.active["items"] = []
            self.active["name"] = "默认列表"
        else:
            self.playlists.remove(self.active)
            self.data["active_playlist_id"] = self.playlists[0]["id"]
        self.save()

    def add_items(self, paths: list[str], at: int | None = None) -> int:
        existing = {item["path"] for item in self.items}
        fresh = [new_item(p) for p in paths if p not in existing]
        if not fresh:
            return 0
        index = len(self.items) if at is None else max(0, min(at, len(self.items)))
        self.items[index:index] = fresh
        self.save()
        return len(fresh)

    def sync_order(self, paths: list[str]) -> None:
        lookup = {item["path"]: item for item in self.items}
        self.active["items"] = [lookup[p] for p in paths if p in lookup]
        self.save()

    def remove_paths(self, paths: set[str]) -> None:
        self.active["items"] = [i for i in self.items if i["path"] not in paths]
        self.save()

    def clear(self) -> None:
        self.active["items"] = []
        self.save()

    def bookmark(self, doc_hash: str, path: str, sentence: int) -> None:
        if not doc_hash:
            return
        self.data["bookmarks"][doc_hash] = {
            "path": path,
            "sentence": sentence,
        }
        for item in self.items:
            if item["path"] == path:
                item["position"] = sentence
                item["doc_hash"] = doc_hash
                break
        self.save()

    def get_bookmark(self, doc_hash: str) -> dict | None:
        return self.data["bookmarks"].get(doc_hash)
