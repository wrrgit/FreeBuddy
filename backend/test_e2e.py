"""端到端核心流程验证：2 成员 × 1 轮 + 总结，真实 CLI 调用。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.models import Action, Member
from app.orchestrator import Orchestrator


async def main() -> None:
    members = [
        Member(name="研究员", cli="deveco", role="研究员：提供事实依据"),
        Member(name="评审员", cli="opencode", role="评审员：审查逻辑漏洞"),
    ]

    events: list[dict] = []

    async def broadcast(payload: dict) -> None:
        events.append(payload)
        etype = payload["type"]
        if etype == "typing":
            print(f"\n--- {payload['member_name']} 正在思考 (第{payload['round']}轮) ---")
        elif etype == "round_start":
            print(f"\n========== 第 {payload['round']}/{payload['max_rounds']} 轮 ==========")
        elif etype == "message":
            m = payload["message"]
            print(f"[{m['member_name']}] action={m['action']} target={m['target_id']}")
            print(f"  {m['content'][:300]}")
            if m["citations"]:
                print(f"  citations: {m['citations']}")
            if m["status"] == "error":
                print(f"  !! ERROR: {m['content']}")

    orch = Orchestrator(members=members, broadcast=broadcast, on_members_updated=lambda: None)
    print("=== 测试: 解析器 ===")
    from app.parser import parse_reply
    p1 = parse_reply('{"action":"disagree","target":"m_abc","content":"测试","citations":["x"]}', {"m_abc"})
    assert p1.action == Action.DISAGREE and p1.target_id == "m_abc", p1
    p2 = parse_reply("没有 JSON 的普通回复", set())
    assert p2.action == Action.REPLY and p2.content == "没有 JSON 的普通回复"
    p3 = parse_reply('前置说明 ```json\n{"action":"ask","target":null,"content":"?","citations":[]}\n``` 后缀', set())
    assert p3.action == Action.ASK, p3
    print("解析器 OK")

    print("\n=== 测试: 真实群聊 (1轮+总结) ===")
    # skip_triage=True：本测试固定验证讨论链路本身，跳过「是否需要讨论」前置判断
    orch.start("Python 和 Go 哪个更适合写命令行工具？请简短回答。", max_rounds=1,
               skip_triage=True)
    assert orch.task is not None
    await orch.task

    msgs = [m for m in orch.messages]
    print(f"\n=== 结果: 共 {len(msgs)} 条消息 ===")
    ok = [m for m in msgs if m.status == "done" and not m.is_user]
    err = [m for m in msgs if m.status == "error"]
    print(f"成功 {len(ok)} 条, 失败 {len(err)} 条")
    for m in msgs:
        print(f"  - [{m.member_name}] round={m.round} action={m.action.value} status={m.status}")
    sessions = {m.name: m.session_id for m in members}
    print(f"会话ID: {sessions}")
    if err:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
