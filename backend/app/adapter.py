"""CLI 适配器：无头驱动 deveco / opencode（同构 CLI，run 子命令 + stdin 传 prompt）。

输出为 JSONL 事件流：
  {"type":"step_start", "sessionID":...}
  {"type":"text", "part":{"text":...}}
  {"type":"step_finish", "part":{"tokens":..., "cost":...}}
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

from .models import Member

IS_WINDOWS = sys.platform == "win32"
DEFAULT_TIMEOUT = 600.0


@dataclass
class CliResult:
    text: str = ""
    session_id: Optional[str] = None
    tokens: Optional[dict] = None
    cost: Optional[float] = None
    error: Optional[str] = None
    events: list[dict] = field(default_factory=list)


def build_cmd(member: Member) -> list[str]:
    """prompt 走 stdin，避免 Windows 命令行长度限制。"""
    cmd = [member.cli, "run", "--format", "json"]
    if member.model:
        cmd += ["-m", member.model]
    if member.session_id:
        cmd += ["-s", member.session_id]
    if IS_WINDOWS:
        return ["cmd", "/c", *cmd]
    return cmd


def parse_events(stdout: str) -> CliResult:
    result = CliResult()
    texts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        result.events.append(ev)
        sid = ev.get("sessionID")
        if sid:
            result.session_id = sid
        if ev.get("type") == "text":
            part = ev.get("part") or {}
            t = part.get("text")
            if t:
                texts.append(t)
        elif ev.get("type") == "step_finish":
            part = ev.get("part") or {}
            if part.get("tokens"):
                result.tokens = part.get("tokens")
            if part.get("cost") is not None:
                result.cost = part.get("cost")
    result.text = "".join(texts).strip()
    return result


async def run_cli(member: Member, prompt: str, timeout: float = DEFAULT_TIMEOUT) -> CliResult:
    """以无头模式运行一次成员 CLI，返回解析结果。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *build_cmd(member),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return CliResult(error=f"CLI 未安装或不在 PATH 中: {member.cli}")
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return CliResult(error=f"运行超时（>{timeout:.0f}s）: {member.cli}")

    stdout = out.decode("utf-8", errors="replace")
    result = parse_events(stdout)
    if not result.text:
        stderr = err.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            result.error = stderr or f"CLI 异常退出（code={proc.returncode}）"
        else:
            result.error = "CLI 未返回任何文本"
    return result
