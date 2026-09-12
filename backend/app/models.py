"""数据模型：群成员、消息、动作。"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Action(str, Enum):
    REPLY = "reply"
    AGREE = "agree"
    DISAGREE = "disagree"
    ASK = "ask"
    NEW_TOPIC = "new_topic"
    SUMMARY = "summary"


ACTION_LABELS: dict[Action, str] = {
    Action.REPLY: "发言",
    Action.AGREE: "赞同",
    Action.DISAGREE: "反对",
    Action.ASK: "追问",
    Action.NEW_TOPIC: "新话题",
    Action.SUMMARY: "总结",
}


class Member(BaseModel):
    """群成员：同一个 CLI 可以创建多个成员（不同模型 / 不同角色 / 独立会话）。

    family 为 CLI 协议族：opencode_family / gemini_family / claude_family /
    aider_family / generic_family。
    summary_only 成员不参与轮转发言，仅负责最终总结（如头脑风暴主持人）。
    """

    id: str = Field(default_factory=lambda: new_id("mem"))
    name: str
    cli: str = "deveco"
    family: str = "opencode_family"
    model: Optional[str] = None
    role: str = ""
    color: str = "#409EFF"
    session_id: Optional[str] = None
    enabled: bool = True
    summary_only: bool = False


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("m"))
    member_id: str
    member_name: str
    round: int = 0
    action: Action = Action.REPLY
    target_id: Optional[str] = None
    content: str = ""
    citations: list[str] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)
    status: str = "done"
    meta: dict = Field(default_factory=dict)

    @property
    def is_user(self) -> bool:
        return self.member_id == "user"


class ParsedReply(BaseModel):
    action: Action = Action.REPLY
    target_id: Optional[str] = None
    content: str = ""
    citations: list[str] = Field(default_factory=list)
    raw: str = ""
