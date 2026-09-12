"""从成员回复文本中提取结构化动作 JSON（容错解析）。"""
from __future__ import annotations

import json
import re
from typing import Optional

from .models import Action, ParsedReply

VALID_ACTIONS = {a.value for a in Action}

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    """按优先级提取 JSON 对象：```json 代码块 → 首个平衡的 {...}。"""
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def parse_reply(text: str, valid_msg_ids: set[str] | None = None) -> ParsedReply:
    """解析成员回复。无法解析出 JSON 时，整段文本视为普通发言。"""
    text = (text or "").strip()
    if not text:
        return ParsedReply(content="(空回复)")
    obj = _extract_json(text)
    if obj is None:
        return ParsedReply(content=text, raw=text)

    action_raw = str(obj.get("action", "reply")).strip().lower()
    action = Action.REPLY
    if action_raw in VALID_ACTIONS:
        action = Action(action_raw)

    target = obj.get("target")
    if not isinstance(target, str):
        target = None
    target = target.strip() if target else None
    if target and valid_msg_ids is not None and target not in valid_msg_ids:
        target = None

    content = obj.get("content")
    if not isinstance(content, str) or not content.strip():
        content = text
    content = content.strip()

    citations_raw = obj.get("citations")
    citations: list[str] = []
    if isinstance(citations_raw, list):
        citations = [str(c).strip() for c in citations_raw if str(c).strip()]

    return ParsedReply(
        action=action,
        target_id=target,
        content=content,
        citations=citations,
        raw=text,
    )
