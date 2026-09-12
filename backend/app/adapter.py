"""CLI 适配器：按协议族无头驱动各种 AI 编程 CLI。

协议族注册表：
  opencode_family  deveco / opencode —— `<cli> run --format json`，prompt 走 stdin，
                   JSONL 事件流输出（text / step_finish），支持 --session 会话恢复
  gemini_family    gemini / qwen —— `<cli> -p <触发> -y --output-format json`，
                   prompt 主体走 stdin，输出单个 JSON（含 session_id 与 response）
  claude_family    claude —— `claude -p --output-format json`，prompt 走 stdin，
                   输出单个 JSON（result / session_id / cost），支持 --resume
  aider_family     aider —— `aider --message <prompt>`，纯文本输出，无会话恢复
  generic_family   自定义命令模板：{prompt_file} / {prompt} / {model} 占位符，
                   prompt 写入临时文件，stdout 全量作为回复
"""
from __future__ import annotations

import asyncio
import json
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import Member

IS_WINDOWS = sys.platform == "win32"
DEFAULT_TIMEOUT = 600.0

FAMILY_OPENCODE = "opencode_family"
FAMILY_GEMINI = "gemini_family"
FAMILY_CLAUDE = "claude_family"
FAMILY_AIDER = "aider_family"
FAMILY_GENERIC = "generic_family"

FAMILIES = [FAMILY_OPENCODE, FAMILY_GEMINI, FAMILY_CLAUDE, FAMILY_AIDER, FAMILY_GENERIC]


@dataclass
class CliResult:
    text: str = ""
    session_id: Optional[str] = None
    tokens: Optional[dict] = None
    cost: Optional[float] = None
    error: Optional[str] = None
    events: list[dict] = field(default_factory=list)


def _win(cmd: list[str]) -> list[str]:
    """Windows 下 npm 安装的 CLI 多为 .cmd 包装，需经 cmd /c 调用。"""
    return ["cmd", "/c", *cmd] if IS_WINDOWS else cmd


class BuiltCommand:
    """一次成员调用的完整命令：cmd 为参数列表；stdin_data 为标准输入内容（可空）；
    prompt_file 若非 None，表示 prompt 已写入该文件（generic 模板用完负责清理）。"""

    def __init__(self, cmd: list[str], stdin_data: str = "",
                 prompt_file: Optional[Path] = None):
        self.cmd = cmd
        self.stdin_data = stdin_data
        self.prompt_file = prompt_file


# ---------- 各协议族命令构造 ----------

def _build_opencode(member: Member, prompt: str) -> BuiltCommand:
    cmd = [member.cli, "run", "--format", "json"]
    if member.model:
        cmd += ["-m", member.model]
    if member.session_id:
        cmd += ["-s", member.session_id]
    return BuiltCommand(_win(cmd), stdin_data=prompt)


def _build_gemini(member: Member, prompt: str) -> BuiltCommand:
    # -p 是 headless 触发条件，且官方说明为 "Appended to input on stdin (if any)"，
    # 因此 prompt 主体走 stdin，-p 传触发短句，规避命令行长度限制。
    cmd = [member.cli, "-p", "(完整指令见 stdin 输入，请直接执行其中要求)",
           "-y", "--output-format", "json"]
    if member.model:
        cmd += ["-m", member.model]
    return BuiltCommand(_win(cmd), stdin_data=prompt)


def _build_claude(member: Member, prompt: str) -> BuiltCommand:
    cmd = [member.cli, "-p", "--output-format", "json"]
    if member.model:
        cmd += ["--model", member.model]
    if member.session_id:
        cmd += ["--resume", member.session_id]
    return BuiltCommand(_win(cmd), stdin_data=prompt)


def _build_aider(member: Member, prompt: str) -> BuiltCommand:
    cmd = [member.cli, "--message", prompt, "--yes-always", "--no-git",
           "--no-auto-commits", "--no-pretty", "--no-stream",
           "--no-check-update", "--no-show-model-warnings"]
    if member.model:
        cmd += ["--model", member.model]
    return BuiltCommand(_win(cmd))


def _build_generic(member: Member, prompt: str) -> BuiltCommand:
    """member.cli 为命令模板，支持占位符：
    {prompt_file} - prompt 写入的临时文件路径（推荐，无长度限制）
    {prompt}       - prompt 全文内联（受命令行长度限制）
    {model}        - 成员配置的模型（未配置则替换为空字符串）
    未使用任何占位符时，prompt 仍通过 stdin 传入（若命令会读 stdin）。
    """
    tmp: Optional[Path] = None
    template = member.cli
    if "{prompt_file}" in template:
        f = tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8")
        f.write(prompt)
        f.close()
        tmp = Path(f.name)
        template = template.replace("{prompt_file}", str(tmp))
    template = template.replace("{model}", member.model or "")
    if "{prompt}" in template:
        template = template.replace("{prompt}", prompt.replace('"', '\\"'))
    try:
        cmd = shlex.split(template, posix=IS_WINDOWS is False)
    except ValueError as e:
        raise ValueError(f"自定义命令模板无法解析: {e}") from e
    stdin_data = "" if tmp is not None else prompt
    return BuiltCommand(_win(cmd), stdin_data=stdin_data, prompt_file=tmp)


_BUILDERS = {
    FAMILY_OPENCODE: _build_opencode,
    FAMILY_GEMINI: _build_gemini,
    FAMILY_CLAUDE: _build_claude,
    FAMILY_AIDER: _build_aider,
    FAMILY_GENERIC: _build_generic,
}


def build_command(member: Member, prompt: str) -> BuiltCommand:
    builder = _BUILDERS.get(member.family)
    if builder is None:
        raise ValueError(f"未知协议族: {member.family}")
    return builder(member, prompt)


# ---------- 输出解析 ----------

def parse_opencode(stdout: str) -> CliResult:
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


def _parse_json_object(stdout: str) -> Optional[dict]:
    start = stdout.find("{")
    if start == -1:
        return None
    # 从末尾往前找平衡的 }
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(stdout):
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
            if depth == 0 and i >= start:
                try:
                    obj = json.loads(stdout[start:i + 1])
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    return None
    return None


def parse_gemini(stdout: str) -> CliResult:
    result = CliResult()
    obj = _parse_json_object(stdout)
    if obj is None:
        return result
    result.events.append(obj)
    result.session_id = obj.get("session_id")
    err = obj.get("error")
    if isinstance(err, dict) and err.get("message"):
        result.error = str(err.get("message"))
        return result
    resp = obj.get("response") or {}
    text = resp.get("text") if isinstance(resp, dict) else None
    result.text = (text or "").strip()
    usage = resp.get("usageMetadata") if isinstance(resp, dict) else None
    if isinstance(usage, dict):
        result.tokens = usage
    return result


def parse_claude(stdout: str) -> CliResult:
    result = CliResult()
    obj = _parse_json_object(stdout)
    if obj is None:
        return result
    result.events.append(obj)
    result.session_id = obj.get("session_id")
    result.text = (obj.get("result") or "").strip()
    cost = obj.get("total_cost_usd")
    if cost is not None:
        result.cost = float(cost)
    usage = obj.get("usage") or {}
    if isinstance(usage, dict) and usage:
        result.tokens = {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "cache": {
                "read": usage.get("cache_read_input_tokens", 0),
                "write": usage.get("cache_creation_input_tokens", 0),
            },
        }
    if obj.get("is_error"):
        result.error = result.text or "claude 运行错误"
    return result


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def parse_aider(stdout: str) -> CliResult:
    """aider 为纯文本输出，混杂日志。启发式：按空行分块，取最后一个
    长度 >= 40 的文本块作为回复。"""
    text = _ANSI_RE.sub("", stdout)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    for block in reversed(blocks):
        if len(block) >= 40:
            return CliResult(text=block)
    return CliResult()


def parse_generic(stdout: str) -> CliResult:
    text = _ANSI_RE.sub("", stdout).strip()
    return CliResult(text=text)


_PARSERS = {
    FAMILY_OPENCODE: parse_opencode,
    FAMILY_GEMINI: parse_gemini,
    FAMILY_CLAUDE: parse_claude,
    FAMILY_AIDER: parse_aider,
    FAMILY_GENERIC: parse_generic,
}


# ---------- 统一入口 ----------

async def run_cli(member: Member, prompt: str, timeout: float = DEFAULT_TIMEOUT) -> CliResult:
    """以无头模式运行一次成员 CLI，返回解析结果。"""
    try:
        built = build_command(member, prompt)
    except ValueError as e:
        return CliResult(error=str(e))
    try:
        proc = await asyncio.create_subprocess_exec(
            *built.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        if built.prompt_file is not None:
            built.prompt_file.unlink(missing_ok=True)
        return CliResult(error=f"CLI 未安装或不在 PATH 中: {member.cli}")
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(built.stdin_data.encode("utf-8")), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        if built.prompt_file is not None:
            built.prompt_file.unlink(missing_ok=True)
        return CliResult(error=f"运行超时（>{timeout:.0f}s）")
    finally:
        if built.prompt_file is not None:
            built.prompt_file.unlink(missing_ok=True)

    stdout = out.decode("utf-8", errors="replace")
    parser = _PARSERS.get(member.family, parse_generic)
    result = parser(stdout)
    if not result.text and not result.error:
        stderr = err.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            result.error = stderr[-500:] or f"CLI 异常退出（code={proc.returncode}）"
        else:
            result.error = "CLI 未返回任何文本"
    return result
