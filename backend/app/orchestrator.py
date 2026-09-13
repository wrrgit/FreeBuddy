"""群聊调度器（主持人规则主导）。

流程：
  用户提问 → 第 1 轮（全员依次首次观点）→ 第 2..N 轮（全员基于上一轮表态/追问）
  → 主持人总结（优先选角色含"主持"的成员，否则第一个启用成员）
终止：达到最大轮数 / 用户停止 / 成员全部失败。
"""
from __future__ import annotations

import asyncio
import random
import traceback
from typing import Any, Awaitable, Callable, Optional

from . import adapter, parser, transcript
from .models import Action, Member, Message, new_id

Broadcast = Callable[[dict[str, Any]], Awaitable[None]]


class Orchestrator:
    def __init__(
        self,
        members: list[Member],
        broadcast: Broadcast,
        on_members_updated: Callable[[], None],
        cli_timeout: float = 600.0,
    ):
        self.members = members
        self.broadcast = broadcast
        self.on_members_updated = on_members_updated
        self.cli_timeout = cli_timeout
        self.messages: list[Message] = []
        self.question: str = ""
        self.max_rounds: int = 3
        self.skip_triage: bool = False
        self.stop_event = asyncio.Event()
        self.running = False
        self.task: Optional[asyncio.Task] = None

    # ---------- 对外接口 ----------

    @property
    def active_members(self) -> list[Member]:
        return [m for m in self.members if m.enabled]

    @property
    def speaking_members(self) -> list[Member]:
        """参与轮转发言的成员（不含仅总结的主持人）。"""
        return [m for m in self.members if m.enabled and not m.summary_only]

    def start(self, question: str, max_rounds: int, skip_triage: bool = False) -> None:
        if self.running:
            raise RuntimeError("讨论已在进行中")
        if not self.speaking_members:
            raise RuntimeError("没有可发言的群成员")
        self.question = question
        self.max_rounds = max(1, max_rounds)
        self.skip_triage = skip_triage
        self.stop_event = asyncio.Event()
        self.running = True
        self.task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self.stop_event.set()

    def interject(self, content: str) -> Message:
        """用户插话：追加一条用户消息，下一轮讨论可见。"""
        msg = Message(
            id=new_id("m"),
            member_id="user",
            member_name="用户",
            round=self._current_round(),
            action=Action.REPLY,
            content=content,
        )
        self.messages.append(msg)
        return msg

    def clear(self) -> None:
        if self.running:
            raise RuntimeError("讨论进行中，无法清空")
        self.messages = []
        self.question = ""
        for m in self.members:
            m.session_id = None
        self.on_members_updated()

    # ---------- 内部调度 ----------

    def _current_round(self) -> int:
        return max((m.round for m in self.messages), default=0)

    def _member_map(self) -> dict[str, Member]:
        return {m.id: m for m in self.members}

    def _valid_target_ids(self) -> set[str]:
        return {m.id for m in self.messages if not m.is_user}

    async def _push_message(self, msg: Message) -> None:
        self.messages.append(msg)
        await self.broadcast({"type": "message", "message": msg.model_dump()})

    async def _triage(self) -> Optional[tuple[Member, bool, str, str]]:
        """讨论前置判断：由主持人判断该问题是否需要群聊讨论。

        返回 (判断成员, need_discussion, reason, direct_answer)；
        判断失败（CLI 报错 / 无可用成员）返回 None，调用方应放行走讨论（fail-open）。
        """
        triager = self._pick_moderator()
        if triager is None:
            return None
        await self.broadcast(
            {"type": "typing", "member_id": triager.id,
             "member_name": triager.name, "round": 0, "triage": True}
        )
        result = await adapter.run_cli(
            triager, transcript.build_triage_prompt(self.question),
            timeout=self.cli_timeout,
        )
        if result.error or not result.text:
            return None
        need, reason, answer = parser.parse_triage(result.text)
        return triager, need, reason, answer

    async def _run(self) -> None:
        try:
            user_msg = Message(
                member_id="user",
                member_name="用户",
                round=0,
                action=Action.REPLY,
                content=self.question,
            )
            await self._push_message(user_msg)

            if not self.skip_triage:
                triage = await self._triage()
                if triage is not None:
                    triager, need, reason, answer = triage
                    await self.broadcast(
                        {"type": "triage", "need_discussion": need, "reason": reason}
                    )
                    if not need and answer:
                        # 无需讨论：主持人直接回答，不进入轮转
                        await self._push_message(Message(
                            member_id=triager.id,
                            member_name=triager.name,
                            round=0,
                            action=Action.REPLY,
                            content=answer,
                            meta={
                                "cli": triager.cli,
                                "model": triager.model,
                                "triage_reason": reason,
                            },
                        ))
                        await self.broadcast({"type": "finished", "stopped": False})
                        return
                    # need=False 但没给答案，或 need=True：继续走讨论

            for round_no in range(1, self.max_rounds + 1):
                if self.stop_event.is_set():
                    break
                order = self._order_for_round(round_no)
                await self.broadcast(
                    {
                        "type": "round_start",
                        "round": round_no,
                        "max_rounds": self.max_rounds,
                        "order": [m.name for m in order],
                    }
                )
                for member in order:
                    if self.stop_event.is_set():
                        break
                    await self._member_turn(member, round_no)

            if not self.stop_event.is_set():
                moderator = self._pick_moderator()
                if moderator is not None:
                    await self._summary_turn(moderator)

            await self.broadcast({"type": "finished", "stopped": self.stop_event.is_set()})
        except Exception:
            await self.broadcast(
                {"type": "error", "error": traceback.format_exc(limit=3)}
            )
            await self.broadcast({"type": "finished", "stopped": True})
        finally:
            self.running = False

    def _pick_moderator(self) -> Optional[Member]:
        for m in self.members:
            if m.enabled and m.summary_only:
                return m
        for m in self.active_members:
            if "主持" in (m.role or ""):
                return m
        return self.speaking_members[0] if self.speaking_members else None

    def _order_for_round(self, round_no: int) -> list[Member]:
        """发言顺序：第 1 轮按列表顺序（设计者先出草案）；
        之后轮次，上一轮被反对/追问最多的成员优先，其余随机洗牌。"""
        speakers = self.speaking_members
        if round_no <= 1 or len(speakers) <= 1:
            return list(speakers)
        msg_owner = {m.id: m.member_id for m in self.messages}
        counts: dict[str, int] = {m.id: 0 for m in speakers}
        prev = round_no - 1
        for msg in self.messages:
            if (
                msg.round == prev
                and msg.target_id
                and msg.action in (Action.DISAGREE, Action.ASK)
            ):
                owner = msg_owner.get(msg.target_id)
                if owner in counts:
                    counts[owner] += 1
        mentioned = sorted(
            (m for m in speakers if counts[m.id] > 0), key=lambda m: -counts[m.id]
        )
        rest = [m for m in speakers if counts[m.id] == 0]
        random.shuffle(rest)
        return mentioned + rest

    async def _member_turn(self, member: Member, round_no: int) -> None:
        await self.broadcast(
            {"type": "typing", "member_id": member.id, "member_name": member.name,
             "round": round_no}
        )
        prompt = transcript.build_discuss_prompt(
            member, self.question, self.messages, self._member_map(), round_no
        )
        result = await adapter.run_cli(member, prompt, timeout=self.cli_timeout)
        if result.session_id:
            member.session_id = result.session_id
            self.on_members_updated()

        if result.error:
            await self._push_message(Message(
                member_id=member.id,
                member_name=member.name,
                round=round_no,
                action=Action.REPLY,
                content=f"（执行失败：{result.error}）",
                status="error",
                meta={"cli": member.cli, "model": member.model},
            ))
            return

        parsed = parser.parse_reply(result.text, self._valid_target_ids())
        await self._push_message(Message(
            member_id=member.id,
            member_name=member.name,
            round=round_no,
            action=parsed.action,
            target_id=parsed.target_id,
            content=parsed.content,
            citations=parsed.citations,
            meta={
                "cli": member.cli,
                "model": member.model,
                "session_id": result.session_id,
                "tokens": result.tokens,
                "cost": result.cost,
                "raw": parsed.raw,
            },
        ))

    async def _summary_turn(self, moderator: Member) -> None:
        await self.broadcast(
            {"type": "typing", "member_id": moderator.id,
             "member_name": moderator.name, "round": self.max_rounds + 1, "summary": True}
        )
        prompt = transcript.build_summary_prompt(
            moderator, self.question, self.messages, self._member_map()
        )
        result = await adapter.run_cli(moderator, prompt, timeout=self.cli_timeout)
        if result.session_id:
            moderator.session_id = result.session_id
            self.on_members_updated()
        if result.error:
            content = f"（总结失败：{result.error}）"
            status = "error"
        else:
            parsed = parser.parse_reply(result.text)
            content = parsed.content
            status = "done"
        await self._push_message(Message(
            member_id=moderator.id,
            member_name=moderator.name,
            round=self.max_rounds + 1,
            action=Action.SUMMARY,
            content=content,
            status=status,
            meta={
                "cli": moderator.cli,
                "model": moderator.model,
                "session_id": result.session_id,
                "tokens": result.tokens,
                "cost": result.cost,
                "raw": result.text,
            },
        ))
