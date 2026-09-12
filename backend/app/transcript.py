"""群聊 transcript 组装：把群聊记录 + 角色设定 + 输出协议注入成员 prompt。"""
from __future__ import annotations

from typing import Optional

from .models import ACTION_LABELS, Action, Member, Message

JSON_PROTOCOL = """\
请严格输出一个 JSON 对象（不要输出任何 JSON 以外的文字）：
{
  "action": "reply | agree | disagree | ask | new_topic",
  "target": "你回应的消息 ID，没有则填 null",
  "content": "你的观点正文（300 字以内）",
  "citations": ["你的依据来源：文件、命令输出、可验证事实，可为空数组"]
}
动作说明：
- agree: 明确赞同 target 消息的观点
- disagree: 反对 target 消息的观点，必须给出具体论据
- ask: 向 target 消息的作者追问或反问
- new_topic: 在当前讨论基础上提出一个新的子话题或补充视角
- reply: 一般性发言"""

GROUP_RULES = """\
【群聊规则】
- 尊重事实：不确定的观点必须明说"我不确定"，严禁编造；有依据时写入 citations
- 独立思考：不要为了附和而附和，与其他成员有分歧时必须明确表达并说明理由
- 有来有往：回应他人观点时，target 必须填对应消息 ID
- 简洁直接：正文 300 字以内，不要客套"""


def _render_message(msg: Message, members: dict[str, Member]) -> str:
    role = ""
    m = members.get(msg.member_id)
    if m and m.role:
        role = f"（{m.role}）"
    prefix = f"[#{msg.id} · {msg.member_name}{role}]"
    if msg.action == Action.REPLY:
        return f"{prefix} {msg.content}"
    if msg.action in (Action.AGREE, Action.DISAGREE, Action.ASK):
        label = ACTION_LABELS[msg.action]
        target = f" → #{msg.target_id}" if msg.target_id else ""
        return f"{prefix} （{label}{target}） {msg.content}"
    if msg.action == Action.NEW_TOPIC:
        return f"{prefix} （新话题） {msg.content}"
    return f"{prefix} {msg.content}"


def render_transcript(messages: list[Message], members: dict[str, Member]) -> str:
    lines: list[str] = []
    current_round = -1
    for msg in messages:
        if msg.round != current_round:
            current_round = msg.round
            if msg.round == 0:
                lines.append("— 用户提问 —")
            else:
                lines.append(f"— 第 {msg.round} 轮 —")
        lines.append(_render_message(msg, members))
        if msg.citations:
            for i, c in enumerate(msg.citations, 1):
                lines.append(f"    〔依据{i}〕{c}")
    return "\n".join(lines)


def build_discuss_prompt(
    member: Member,
    question: str,
    messages: list[Message],
    members: dict[str, Member],
    round_no: int,
) -> str:
    """讨论轮 prompt。"""
    parts: list[str] = []
    role_line = f"，角色定位：{member.role}" if member.role else ""
    parts.append(
        f"你是多专家群聊中的成员「{member.name}」{role_line}。\n"
        f"群成员来自不同的 AI 模型与 CLI，正在就用户的提问展开讨论。\n{GROUP_RULES}"
    )
    parts.append(f"【讨论主题】\n{question}")
    if messages:
        parts.append(f"【群聊记录】\n{render_transcript(messages, members)}")
        parts.append(f"【你的发言（第 {round_no} 轮）】\n{JSON_PROTOCOL}")
    else:
        parts.append(
            f"【你的发言（第 1 轮，首轮）】\n"
            f"请针对讨论主题给出你的初步观点。如果你有可查证的依据（本地文件、"
            f"常识性事实、逻辑推演），写入 citations。\n{JSON_PROTOCOL}"
        )
    return "\n\n".join(parts)


def build_summary_prompt(
    member: Member,
    question: str,
    messages: list[Message],
    members: dict[str, Member],
) -> str:
    """最终轮 prompt：把群聊讨论收敛为可落地实施的技术架构方案。"""
    role_line = f"你的角色定位：{member.role}。" if member.role else ""
    parts: list[str] = []
    parts.append(
        f"你是「{member.name}」，本次头脑风暴的主持人。{role_line}"
        f"讨论已结束，请你阅读完整群聊记录，把各方观点收敛为一份可落地实施的最终技术架构方案。"
    )
    parts.append(f"【讨论主题】\n{question}")
    parts.append(f"【完整群聊记录】\n{render_transcript(messages, members)}")
    parts.append(
        "【最终方案要求】\n"
        "1. 必须吸收群聊中各方有价值观点，被否决的选项要写明否决理由\n"
        "2. 批判/安全/性能维度提出的问题，要么在方案中给出对策，要么列入待决策项\n"
        "3. 方案要具体可执行，不写空话\n"
        "请严格输出一个 JSON 对象（不要输出任何 JSON 以外的文字）：\n"
        "{\n"
        '  "action": "summary",\n'
        '  "target": null,\n'
        '  "content": "最终技术架构方案，用以下结构：\\n'
        '一、方案概述（核心架构一段话）\\n'
        '二、技术选型（每项选型 + 理由，含被否决项及否决理由）\\n'
        '三、架构设计（模块划分、关键数据流、外部依赖）\\n'
        '四、实施路线（分阶段里程碑：MVP → 迭代，各阶段依赖关系）\\n'
        '五、风险与对策（安全/合规/性能风险清单及对应措施）\\n'
        '六、待人工决策项（需要用户拍板的问题清单）",\n'
        '  "citations": ["方案依据的关键消息 ID，如 #m1"]\n'
        "}"
    )
    return "\n\n".join(parts)
