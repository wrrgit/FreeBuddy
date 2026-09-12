"""FastAPI 服务：REST + WebSocket，本地运行，前端构建产物可直接托管。"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .models import Member, Message
from .orchestrator import Orchestrator
from .store import Store

SUPPORTED_CLIS = ["deveco", "opencode"]

app = FastAPI(title="multi-cli group chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
store = Store(DATA_DIR)

_members: list[Member] = store.load_members()
if not _members:
    _members = [
        Member(
            name="架构师", cli="deveco", model=None,
            role="架构师：负责设计整体技术架构。方案必须对照业界标杆实践"
                 "（对标案例写入 citations），每轮基于他人意见完善方案，而不是推倒重来",
            color="#409EFF",
        ),
        Member(
            name="批判与性能官", cli="opencode", model=None,
            role="批判与性能官：专职找方案的问题——逻辑风险、过度设计、依赖陷阱，"
                 "以及容量瓶颈、性能热点、SLO 可达成性。每轮必须指出至少 1 个具体问题并给出论据，"
                 "不得说「整体没问题」",
            color="#F56C6C",
        ),
        Member(
            name="安全合规专家", cli="deveco", model=None,
            role="安全合规专家：威胁建模（攻击面、鉴权、密钥与敏感数据、供应链安全）、"
                 "数据合规（个保法/数据出境）、开源协议风险。对方案主动指出安全隐患（用 disagree/ask），"
                 "不确定的法规条款必须标注「需人工核实」",
            color="#E6A23C",
        ),
        Member(
            name="落地实施官", cli="opencode", model=None,
            role="落地实施官：不推翻方案，只回答「怎么落地」——分几步走、"
                 "每步的卡点与依赖、MVP 切分、渐进式迁移策略",
            color="#67C23A",
        ),
        Member(
            name="头脑风暴主持人", cli="deveco", model=None,
            role="头脑风暴主持人：不参与争论，把群聊讨论收敛为一份可落地实施的最终技术架构方案",
            color="#9254DE", summary_only=True,
        ),
    ]
    store.save_members(_members)

_ws_clients: set[WebSocket] = set()
_model_cache: dict[str, tuple[float, list[str]]] = {}


async def _broadcast(payload: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.discard(ws)


orchestrator = Orchestrator(
    members=_members,
    broadcast=_broadcast,
    on_members_updated=lambda: store.save_members(_members),
)


# ---------- WebSocket ----------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.add(ws)
    try:
        await ws.send_json({
            "type": "init",
            "messages": [m.model_dump() for m in orchestrator.messages],
            "running": orchestrator.running,
            "question": orchestrator.question,
        })
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


# ---------- 成员管理 ----------

class MemberIn(BaseModel):
    name: str
    cli: str = "deveco"
    model: Optional[str] = None
    role: str = ""
    color: str = "#409EFF"
    enabled: bool = True
    summary_only: bool = False


@app.get("/api/members")
async def get_members() -> list[dict[str, Any]]:
    return [m.model_dump() for m in _members]


@app.post("/api/members")
async def add_member(body: MemberIn) -> dict[str, Any]:
    member = Member(**body.model_dump())
    _members.append(member)
    store.save_members(_members)
    return member.model_dump()


@app.put("/api/members/{member_id}")
async def update_member(member_id: str, body: MemberIn) -> Optional[dict[str, Any]]:
    for i, m in enumerate(_members):
        if m.id == member_id:
            body_dict = body.model_dump()
            if not body_dict.get("session_id"):
                body_dict["session_id"] = m.session_id
            _members[i] = Member(**body_dict, id=m.id)
            store.save_members(_members)
            return _members[i].model_dump()
    return None


@app.delete("/api/members/{member_id}")
async def delete_member(member_id: str) -> dict[str, bool]:
    global _members
    if orchestrator.running:
        return {"ok": False, "error": "讨论进行中，无法删除成员"}
    before = len(_members)
    _members = [m for m in _members if m.id != member_id]
    orchestrator.members = _members
    store.save_members(_members)
    return {"ok": len(_members) < before}


@app.get("/api/clis")
async def list_clis() -> list[dict[str, Any]]:
    return [
        {"name": name, "installed": shutil.which(name) is not None}
        for name in SUPPORTED_CLIS
    ]


@app.get("/api/models")
async def list_models(cli: str) -> dict[str, Any]:
    if cli not in SUPPORTED_CLIS or shutil.which(cli) is None:
        return {"models": [], "error": f"CLI 不可用: {cli}"}
    cached = _model_cache.get(cli)
    if cached:
        return {"models": cached[1]}
    try:
        proc = await asyncio.create_subprocess_exec(
            "cmd", "/c", cli, "models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        models = [
            line.strip() for line in out.decode("utf-8", errors="replace").splitlines()
            if line.strip() and "/" in line.strip()
        ]
        _model_cache[cli] = (0.0, models)
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}


# ---------- 讨论 ----------

class DiscussIn(BaseModel):
    question: str
    max_rounds: int = 3


@app.post("/api/discuss")
async def discuss(body: DiscussIn) -> dict[str, Any]:
    if orchestrator.running:
        return {"ok": False, "error": "讨论已在进行中"}
    if not body.question.strip():
        return {"ok": False, "error": "问题不能为空"}
    if not orchestrator.active_members:
        return {"ok": False, "error": "没有启用的群成员"}
    try:
        orchestrator.start(body.question.strip(), body.max_rounds)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@app.post("/api/stop")
async def stop_discuss() -> dict[str, bool]:
    orchestrator.stop()
    return {"ok": True}


class InterjectIn(BaseModel):
    content: str


@app.post("/api/interject")
async def interject(body: InterjectIn) -> dict[str, Any]:
    if not body.content.strip():
        return {"ok": False, "error": "内容不能为空"}
    msg = orchestrator.interject(body.content.strip())
    store.append_message(msg)
    await _broadcast({"type": "message", "message": msg.model_dump()})
    return {"ok": True, "message": msg.model_dump()}


@app.post("/api/clear")
async def clear_session() -> dict[str, Any]:
    if orchestrator.running:
        return {"ok": False, "error": "讨论进行中，无法清空"}
    orchestrator.clear()
    await _broadcast({"type": "cleared"})
    return {"ok": True}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return {
        "running": orchestrator.running,
        "question": orchestrator.question,
        "rounds_done": orchestrator._current_round(),
        "max_rounds": orchestrator.max_rounds,
        "message_count": len(orchestrator.messages),
    }


@app.get("/api/messages")
async def messages() -> list[dict[str, Any]]:
    return [m.model_dump() for m in orchestrator.messages]


# 消息持久化：挂载到广播链
_orig_broadcast = _broadcast


async def _broadcast_with_log(payload: dict[str, Any]) -> None:
    if payload.get("type") == "message":
        store.append_message(Message(**payload["message"]))
    await _orig_broadcast(payload)


orchestrator.broadcast = _broadcast_with_log

# ---------- 前端静态托管（构建后生效） ----------

_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
