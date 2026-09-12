"""适配器单测：各协议族命令构造与输出解析（不真实调用 CLI）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.adapter import (
    FAMILY_AIDER, FAMILY_CLAUDE, FAMILY_GEMINI, FAMILY_GENERIC, FAMILY_OPENCODE,
    build_command, parse_aider, parse_claude, parse_gemini, parse_opencode,
)
from app.models import Member


def member(family: str, cli: str = "testcli", model=None, session_id=None) -> Member:
    return Member(name="测试", cli=cli, family=family, model=model, session_id=session_id)


def flat(cmd: list[str]) -> str:
    return " ".join(cmd)


# --- 1. opencode 族 ---
m = member(FAMILY_OPENCODE, "deveco", model="zai/glm-5.3", session_id="ses_123")
built = build_command(m, "你好")
s = flat(built.cmd)
assert "deveco run --format json" in s and "-m zai/glm-5.3" in s and "-s ses_123" in s, s
assert built.stdin_data == "你好"
print(f"1. opencode 族命令: {s} OK")

# --- 2. gemini 族（无 session 恢复，prompt 走 stdin）---
m = member(FAMILY_GEMINI, "gemini", model="gemini-2.5-pro")
built = build_command(m, "长prompt" * 1000)
s = flat(built.cmd)
assert s.startswith("cmd /c gemini" ) or s.startswith("gemini"), s
assert "-y" in s and "--output-format json" in s and "-m gemini-2.5-pro" in s, s
assert "ses_123" not in s
assert built.stdin_data == "长prompt" * 1000 and len(built.cmd) < 15, "长 prompt 必须走 stdin"
print(f"2. gemini 族命令: {s[:80]}... OK（prompt 走 stdin）")

# --- 3. claude 族 ---
m = member(FAMILY_CLAUDE, "claude", model="sonnet", session_id="abc")
built = build_command(m, "你好")
s = flat(built.cmd)
assert "claude -p --output-format json" in s and "--model sonnet" in s and "--resume abc" in s, s
assert built.stdin_data == "你好"
print(f"3. claude 族命令: {s} OK")

# --- 4. aider 族（prompt 内联在 --message）---
m = member(FAMILY_AIDER, "aider", model="deepseek")
built = build_command(m, "观点内容")
s = flat(built.cmd)
assert "--message 观点内容" in s and "--yes-always" in s and "--no-git" in s and "--model deepseek" in s, s
print(f"4. aider 族命令: {s[:80]}... OK")

# --- 5. generic 族（占位符）---
m = member(FAMILY_GENERIC, cli="mycli ask {prompt_file} --model {model}", model="m1")
built = build_command(m, "提示词内容")
s = flat(built.cmd)
assert "mycli ask" in s and "--model m1" in s and "{prompt_file}" not in s, s
assert built.prompt_file is not None and built.prompt_file.exists()
pf = built.prompt_file
assert pf.read_text(encoding="utf-8") == "提示词内容"
pf.unlink()
print(f"5. generic 族命令: {s} OK（prompt 已写临时文件）")

# --- 6. 各族输出解析 ---
oc = parse_opencode('{"type":"text","sessionID":"s1","part":{"text":"回复"}}\n'
                    '{"type":"step_finish","sessionID":"s1","part":{"tokens":{"output":5},"cost":0.01}}')
assert oc.text == "回复" and oc.session_id == "s1" and oc.cost == 0.01

gm = parse_gemini('{"session_id":"uuid-1","response":{"text":"G回复","usageMetadata":{"totalTokenCount":10}}}')
assert gm.text == "G回复" and gm.session_id == "uuid-1", gm

gm_err = parse_gemini('{"session_id":"x","error":{"message":"未登录","code":41}}')
assert gm_err.error == "未登录" and not gm_err.text

cl = parse_claude('{"result":"C回复","session_id":"s2","total_cost_usd":0.02,'
                  '"usage":{"input_tokens":10,"output_tokens":20}}')
assert cl.text == "C回复" and cl.session_id == "s2" and cl.cost == 0.02
assert cl.tokens is not None and cl.tokens["output"] == 20

ai = parse_aider("Aider v0.1\n\n一些日志行\n\n" + "这是助手的回复内容" * 10 + "\n")
assert "助手的回复内容" in ai.text and "Aider v0.1" not in ai.text, ai.text[:50]

print("6. 四族输出解析 OK")

# --- 7. 未知协议族报错 ---
try:
    build_command(member("bad_family"), "x")
    assert False, "应抛异常"
except ValueError:
    print("7. 未知协议族正确报错 OK")

print("\n适配器全部测试通过")
