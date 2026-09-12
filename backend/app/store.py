"""持久化：成员配置（config.json）+ 消息追溯日志（JSONL）。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .models import Member, Message


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.data_dir / "config.json"
        self.log_path: Optional[Path] = None

    # ---------- 成员配置 ----------

    def load_members(self) -> list[Member]:
        if not self.config_path.exists():
            return []
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            return [Member(**item) for item in raw.get("members", [])]
        except (json.JSONDecodeError, ValueError):
            return []

    def save_members(self, members: list[Member]) -> None:
        data = {"members": [m.model_dump() for m in members]}
        self.config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 会话日志 ----------

    def new_session_log(self) -> None:
        logs_dir = self.data_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        name = time.strftime("session_%Y%m%d_%H%M%S.jsonl")
        self.log_path = logs_dir / name

    def append_message(self, message: Message) -> None:
        if self.log_path is None:
            self.new_session_log()
        assert self.log_path is not None
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message.model_dump(), ensure_ascii=False) + "\n")
