"""调度逻辑单测：summary_only 跳过、被点名优先排序、主持人选取。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.models import Action, Member, Message
from app.orchestrator import Orchestrator


async def noop(payload):
    pass


def make_member(name: str, summary_only: bool = False) -> Member:
    return Member(name=name, cli="deveco", summary_only=summary_only)


members = [
    make_member("架构师"),
    make_member("批判与性能官"),
    make_member("安全合规专家"),
    make_member("落地实施官"),
    make_member("头脑风暴主持人", summary_only=True),
]
orch = Orchestrator(members=members, broadcast=noop, on_members_updated=lambda: None)

# --- 1. summary_only 成员不参与轮转 ---
speakers = [m.name for m in orch.speaking_members]
assert "头脑风暴主持人" not in speakers, speakers
assert len(speakers) == 4, speakers
print(f"1. 轮转成员(不含主持人): {speakers} OK")

# --- 2. 第 1 轮按列表顺序 ---
order1 = [m.name for m in orch._order_for_round(1)]
assert order1 == ["架构师", "批判与性能官", "安全合规专家", "落地实施官"], order1
print(f"2. 第1轮固定顺序: {order1} OK")

# --- 3. 第 2 轮被点名优先 ---
# 构造历史：用户提问 + 第1轮发言；第2轮中架构师被 disagree 2 次、安全专家被 ask 1 次
m_user = Message(id="m_u", member_id="user", member_name="用户", round=0, content="Q")
m1 = Message(id="m1", member_id=members[0].id, member_name="架构师", round=1, content="草案")
m2 = Message(id="m2", member_id=members[1].id, member_name="批判与性能官", round=1, content="批1")
m3 = Message(id="m3", member_id=members[2].id, member_name="安全合规专家", round=1, content="安1")
m4 = Message(id="m4", member_id=members[3].id, member_name="落地实施官", round=1, content="落1")
d1 = Message(id="m5", member_id=members[1].id, member_name="批判与性能官", round=2,
             action=Action.DISAGREE, target_id="m1", content="反对1")
d2 = Message(id="m6", member_id=members[2].id, member_name="安全合规专家", round=2,
             action=Action.DISAGREE, target_id="m1", content="反对2")
d3 = Message(id="m7", member_id=members[3].id, member_name="落地实施官", round=2,
             action=Action.ASK, target_id="m3", content="追问")
agree = Message(id="m8", member_id=members[1].id, member_name="批判与性能官", round=2,
                action=Action.AGREE, target_id="m4", content="赞同不算点名")
orch.messages = [m_user, m1, m2, m3, m4, d1, d2, d3, agree]

order2 = [m.name for m in orch._order_for_round(3)]
# 架构师被点名2次 > 安全专家1次 > 其余随机
assert order2[0] == "架构师", order2
assert order2[1] == "安全合规专家", order2
assert set(order2) == {"架构师", "批判与性能官", "安全合规专家", "落地实施官"}, order2
print(f"3. 第3轮被点名优先: {order2} OK（架构师×2 第一、安全专家×1 第二、其余随机）")

# --- 4. 主持人选取 ---
mod = orch._pick_moderator()
assert mod is not None and mod.summary_only and mod.name == "头脑风暴主持人", mod
print(f"4. 主持人: {mod.name} OK")

# --- 5. 无 summary_only 时回退到角色含"主持" ---
members2 = [make_member("甲"), make_member("乙", )]
members2[1].role = "主持人：负责总结"
orch2 = Orchestrator(members=members2, broadcast=noop, on_members_updated=lambda: None)
mod2 = orch2._pick_moderator()
assert mod2 is not None and mod2.name == "乙", mod2
print("5. 无 summary_only 时回退到角色含「主持」的成员 OK")

# --- 6. 总结 prompt 含最终方案模板 ---
from app.transcript import build_summary_prompt
prompt = build_summary_prompt(members[4], "测试主题", orch.messages, {m.id: m for m in members})
assert "最终技术架构方案" in prompt
assert "头脑风暴主持人" in prompt
assert "实施路线" in prompt and "待人工决策项" in prompt
print("6. 总结 prompt 为最终架构方案模板 OK")

# --- 7. triage 判断解析（容错 + fail-open）---
from app.parser import parse_triage

need, reason, answer = parse_triage(
    '{"need_discussion": false, "reason": "事实性问题", "direct_answer": "Go 是 Google 开发的编译型语言"}')
assert need is False and reason == "事实性问题" and "Google" in answer, (need, reason, answer)

need, _, _ = parse_triage('{"need_discussion": true, "reason": "多方案权衡", "direct_answer": null}')
assert need is True

need, _, _ = parse_triage("这问题挺复杂的，我觉得得聊聊")   # 非 JSON → 放行讨论
assert need is True

need, _, _ = parse_triage('```json\n{"need_discussion": "false", "reason": "r", "direct_answer": "a"}\n```')
assert need is False   # 字符串 "false" 容错

need, _, answer2 = parse_triage('{"need_discussion": false, "reason": "r"}')  # 缺 direct_answer
assert need is False and answer2 == ""
print("7. triage 判断解析（JSON块/裸JSON/非JSON/字符串布尔/缺字段 全部容错） OK")

# --- 8. triage prompt 模板 ---
from app.transcript import build_triage_prompt
tp = build_triage_prompt("如何设计一个限流中间件？")
assert "是否" in tp and "need_discussion" in tp and "如何设计一个限流中间件？" in tp
assert "direct_answer" in tp
print("8. triage prompt 模板 OK")

# --- 9. _triage：无需讨论返回直接答案，CLI 失败 fail-open ---
import asyncio
from app import adapter as adapter_mod
from app.adapter import CliResult


async def fake_ok(member, prompt, timeout=600.0):
    assert "need_discussion" in prompt, "triage 必须走专用 prompt"
    return CliResult(text='{"need_discussion": false, "reason": "事实问答", "direct_answer": "直接答案"}')


async def fake_err(member, prompt, timeout=600.0):
    return CliResult(error="CLI 挂了")


orig_run_cli = adapter_mod.run_cli
adapter_mod.run_cli = fake_ok
try:
    r = asyncio.run(orch._triage())
    assert r is not None, "正常判断不应返回 None"
    triager, need, reason, answer3 = r
    assert triager.summary_only and triager.name == "头脑风暴主持人", triager.name  # 判断者=主持人
    assert need is False and answer3 == "直接答案" and reason == "事实问答"
    adapter_mod.run_cli = fake_err
    r2 = asyncio.run(orch._triage())
    assert r2 is None, "CLI 失败应返回 None（调用方放行走讨论）"
finally:
    adapter_mod.run_cli = orig_run_cli
print("9. _triage 无需讨论路径 + 失败放行（fail-open） OK")

print("\n全部调度逻辑测试通过")
