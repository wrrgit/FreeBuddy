# AGENTS.md — FreeBuddy 开发指南（供 AI 编码智能体阅读）

本文件面向继续开发本项目的 AI 编码智能体（deveco / opencode / claude / gemini 等）与人类开发者，
包含项目全貌、架构设计、关键决策、验证方式与已知陷阱。修改代码前请通读本文。

## 1. 项目是什么

FreeBuddy 是一个本地 Web 应用：把多个 AI CLI 编程智能体（deveco、opencode、claude、gemini、qwen、
aider、traecli 或任意自定义 CLI）放进一个群聊。用户提一个问题，各成员（CLI × 模型 × 角色）多轮讨论，
互相赞同/反对/追问，最终由主持人收敛为一份**可落地实施的技术架构方案**。

- 后端：Python 3.10+ / FastAPI / pydantic（`backend/`）
- 前端：Vue 3 + TypeScript + Vite + OpenTiny（`frontend/`）
- 无数据库：成员配置存 JSON，会话日志存 JSONL
- 纯本地运行，前端构建产物由后端直接托管
- 仓库：github.com/wrrgit/FreeBuddy（master 分支）

## 2. 目录结构

```
backend/
  app/
    __init__.py
    models.py        # Pydantic 数据模型：Member / Message / Action / ParsedReply
    adapter.py       # CLI 协议族注册表：命令构造 _build_* + 输出解析 parse_* + run_cli
    parser.py        # 从成员回复文本中容错提取动作 JSON
    transcript.py    # 群聊记录渲染 + 讨论/总结 prompt 组装
    orchestrator.py  # 调度器：轮转顺序、插话、停止、主持人总结
    store.py         # 持久化：data/config.json + data/logs/session_*.jsonl
    main.py          # FastAPI 入口：REST + WebSocket + 静态托管 + KNOWN_CLIS 注册表
  data/
    config.json      # 成员配置（运行时生成，gitignore）
    logs/            # 会话 JSONL 日志（gitignore）
  requirements.txt
  test_adapter.py    # 协议族命令构造/解析单测（不真实调用 CLI）
  test_schedule.py   # 调度逻辑单测
  test_e2e.py        # 真实 2 成员群聊端到端（会真实调用 CLI，耗时数分钟）
  test_ws.py         # WebSocket 全链路（需先启动服务）
frontend/
  src/
    main.ts / App.vue
    api.ts           # REST + WS 客户端
    types.ts         # 与后端 models 对应的 TS 类型
    components/
      MemberPanel.vue  # 成员增删改：协议族→CLI→模型 级联
      ChatMessage.vue  # 消息气泡：动作徽章（可点击跳转 target）、引用、meta 展开
      Composer.vue     # 输入区：开始/停止/插话/清空
  vite.config.ts    # dev 代理 /api、/ws → 127.0.0.1:8000
README.md           # 面向使用者的说明
AGENTS.md           # 本文件
```

## 3. 核心数据流（一轮讨论的生命周期）

```
用户在 Composer 提交问题
  → POST /api/discuss {question, max_rounds, skip_triage}
  → Orchestrator.start() 创建 asyncio 任务 _run()
  → _run():
      push 用户消息(round=0)
      if not skip_triage:
          triage = _triage()                        # 主持人判断是否需要讨论，见 §5
          if 判定无需讨论且给出答案:
              push 主持人直接回答的消息 → broadcast finished → 结束
      for round_no in 1..max_rounds:
          order = _order_for_round(round_no)        # 调度策略，见 §5
          for member in order:
              prompt = transcript.build_discuss_prompt(member, question, 全量messages, ...)
              result = adapter.run_cli(member, prompt)   # subprocess 无头调用 CLI
              parsed = parser.parse_reply(result.text)   # 容错提取动作 JSON
              push Message(action/target/content/citations/meta)  → WS 广播 + JSONL 落盘
      moderator = _pick_moderator()
      prompt = transcript.build_summary_prompt(...)  # 收敛为架构方案
      push Message(action=SUMMARY)
  → broadcast {"type": "finished"}
```

**关键设计：全量重放**。每轮每个成员的 prompt 都包含完整群聊记录（`transcript.render_transcript`），
不依赖 CLI 的会话恢复。因此 session resume（`--session` / `--resume`）只是 token 优化项，
任何"文本进 → 文本出"的 CLI 都能接入。不要把全量重放改成增量——这是正确性来源。

## 4. 数据模型（backend/app/models.py）

```python
Member:  id, name, cli, family, model(None=CLI默认), role(角色prompt片段),
         color, session_id(CLI会话缓存), enabled, summary_only(主持人标记)
Message: id(m_xxx), member_id("user"=用户), member_name, round(0=用户提问),
         action(reply|agree|disagree|ask|new_topic|summary), target_id(指向消息ID),
         content, citations[list[str]], timestamp, status(done|error),
         meta{cli, model, session_id, tokens, cost, raw}
```

- 动作语义：agree/disagree/ask 必须带 target_id（parser 会校验，非法 target 置 None）
- summary_only 成员不参与轮转，只做最终总结

## 5. 调度规则（backend/app/orchestrator.py）

- **讨论前置判断** `_triage()`：主持人（见下）用 `transcript.build_triage_prompt`
  判断问题是否需要群聊讨论；无需讨论且给出答案时直接 push 回答并结束。
  **fail-open**：CLI 报错 / 解析失败 / 无答案一律放行走讨论（parser.parse_triage 同样容错），
  `skip_triage=True`（API 字段或 UI 勾选「跳过判断」）可跳过该步骤
- **第 1 轮**：按成员列表顺序（设计者先出草案）
- **第 2+ 轮**：上一轮被 disagree/ask 点名最多的成员优先（按次数降序），其余随机洗牌
- **主持人选择** `_pick_moderator()`：第一个 enabled 且 summary_only 的成员 →
  否则 role 含「主持」→ 否则第一个发言成员
- **插话** `interject()`：追加用户消息（round=当前轮），下一轮 prompt 中可见
- **停止** `stop()`：设置 stop_event，当前成员说完后 break；停止则跳过总结
- 并发模型：单讨论任务，成员串行发言（同一时刻只有一个 CLI 子进程）

## 6. 协议族适配（backend/app/adapter.py）— 最重要的扩展点

注册表模式：`_BUILDERS[family] = build_xxx`（Member+prompt → BuiltCommand）、
`_PARSERS[family] = parse_xxx`（stdout → CliResult）。`run_cli()` 统一执行 subprocess。

| family | 命令（prompt 传递方式） | 输出解析 |
|---|---|---|
| opencode_family | `<cli> run --format json [-m model] [-s session]`，prompt 走 stdin | JSONL 事件流：type=text 取 part.text，type=step_finish 取 tokens/cost，sessionID |
| gemini_family | `<cli> -p "触发短句" -y --output-format json [-m model]`，prompt 主体走 stdin | 单 JSON：response.text / session_id / error.message |
| claude_family | `claude -p --output-format json [--model] [--resume session]`，prompt 走 stdin | 单 JSON：result / session_id / total_cost_usd / usage / is_error |
| aider_family | `aider --message <prompt全文> --yes-always --no-git ...` | 纯文本启发式：按空行分块取最后一个 >=40 字符的块，先剥 ANSI |
| trae_family | `traecli exec --json --skip-git-repo-check -s read-only -o <tmpfile> [-m model] -`，prompt 走 stdin | 正文读 `-o` 输出文件（JSONL 事件 schema 未公开，只从中尽力取 session_id/error） |
| generic_family | 用户命令模板，占位符 `{prompt_file}`(写临时文件，推荐)/`{prompt}`(内联)/`{model}` | stdout 全量剥 ANSI 作为回复 |

Windows 细节（勿改动）：npm 安装的 CLI 是 .cmd 包装，所有命令经 `_win()` 加 `cmd /c` 前缀；
prompt 一律走 stdin（规避 cmd 8191 字符限制）；generic 的 `{prompt_file}` 用 NamedTemporaryFile。

CliResult: text / session_id / tokens / cost / error / events。
run_cli 失败兜底：无文本且 returncode!=0 时取 stderr 尾部 500 字符为 error。

## 7. 动作协议与容错解析（backend/app/parser.py + transcript.py）

成员被要求输出严格 JSON（见 transcript.JSON_PROTOCOL）：
`{"action": "...", "target": "消息ID或null", "content": "...", "citations": [...]}`

parser 容错策略（按优先级）：```json 代码块 → 首个括号平衡的 {...} → 整段文本视为普通 reply。
target 不在已有消息 ID 集合中则置 None。**不要收紧容错**——真实 CLI 输出经常带废话。

讨论前置判断 parse_triage 同样容错（字符串 "false"、缺 direct_answer 均可处理），
解析失败返回 need=True 放行讨论。

总结轮（build_summary_prompt）强制输出结构化方案：
概述 / 技术选型（含否决项）/ 架构设计 / 实施路线 / 风险对策 / 待人工决策项。

## 8. API 一览（backend/app/main.py）

REST：
- `GET /api/members` | `POST /api/members` | `PUT/DELETE /api/members/{id}`
- `GET /api/families` — 协议族 + 已知 CLI + 安装状态（shutil.which）+ generic hint
- `GET /api/models?cli=&family=` — 仅对支持 `<cli> models` 的族有效（opencode 系），其余返回空让用户手填
- `POST /api/discuss {question, max_rounds, skip_triage}` / `POST /api/stop`
- `POST /api/interject {content}` / `POST /api/clear`
- `GET /api/status` / `GET /api/messages`

WebSocket `/ws`：
- 连接即推 `{"type":"init", messages, running, question}`
- 服务端事件：`message`(新消息) / `round_start`(round,max_rounds,order) /
  `typing`(member_id,member_name,round[,summary|triage]) /
  `triage`(need_discussion,reason) / `finished`(stopped) / `cleared` / `error`

持久化链：`_broadcast_with_log` 包装广播，type=message 时同步 `store.append_message()` 落 JSONL。

新 CLI 接入 main.py 需同步登记：`KNOWN_CLIS`（供 /api/families 与 /api/models 校验）+
`FAMILY_LABELS`（前端显示名）。

## 9. 运行 / 构建 / 测试

```bash
# 后端
cd backend && pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（构建后由后端托管于 :8000）
cd frontend && npm install && npm run build
# 前端开发热更新（:5173，代理 /api /ws）
cd frontend && npm run dev

# 测试（改后端代码后必须跑前三个；test_e2e 会真实调用 CLI）
cd backend
python test_adapter.py     # 8 项：6 族命令构造 + 5 族解析 + 未知族报错
python test_schedule.py    # 9 项：summary_only 跳过 / 首轮顺序 / 点名优先 / 主持人挑选 / 总结模板 /
                           #       triage 解析容错 / triage prompt / triage fail-open
python test_e2e.py         # 真实 2 成员 1 轮讨论 + 总结（需 deveco 可用）
python test_ws.py          # 需先启动 uvicorn
```

改前端后需 `npm run build` 才会在 :8000 生效。

## 10. 默认成员配置（backend/app/main.py）

5 人配置（首次启动无 config.json 时生成）：架构师(deveco)、批判与性能官(opencode)、
安全合规专家(deveco)、落地实施官(opencode)、头脑风暴主持人(deveco, summary_only=True)。
角色 prompt 均要求"不附和、不确定要明说、批判官每轮必须指出至少 1 个具体问题"。

## 11. 已知陷阱（历史上真踩过的坑）

1. **Windows PowerShell 5.1**：`Get-Process` 无 CommandLine（用 `Get-CimInstance Win32_Process`）；
   PS 控制台显示 UTF-8 乱码是显示问题，数据本身没问题，不要"修复"它。
2. **中文角色字符串里的 ASCII 引号**会引发 Python SyntaxError——中文文案一律用「」引号。
3. **store.log_path 曾误设为目录**导致 PermissionError——log_path 必须指向 .jsonl 文件。
4. **npm CLI 在 Windows 需 `cmd /c` 包装**（asyncio.create_subprocess_exec 直接调 .ps1/.cmd 会失败）。
5. **PS `2>&1` 会把 stderr 输出包装成 NativeCommandError**（外观问题，非真错误）。
6. traecli 的 `exec` 无 `--resume`，靠全量重放即可，勿依赖其会话。
7. `~/.config/deveco/deveco.jsonc` 与 `~/.config/opencode/opencode.json` 配置了
   superpowers 本地插件路径（用户环境相关，与本项目代码无关）。

## 12. 待办 / 已知边界（接手者优先看这里）

- trae_family 已实现但**未端到端验证**：需 TRAE 账号登录（`traecli login`）或
  在 `~/.trae/trae_cli.yaml` 配 OpenAI/Claude 兼容自定义模型后跑一次真实讨论
- gemini_family 同样未端到端验证（gemini CLI 未登录，报错 41）
- qwen / aider 本机未安装，adapter 按同构协议实现但未实测
- /api/models 仅支持 opencode 系的 `<cli> models`；其他族模型需手填
- 成员发言串行；未来可做可控并发（注意 CLI 速率限制与 transcript 一致性）
- 讨论中途 reload 页面：WS init 会重发全部消息，但 running 状态下无法恢复实时推送的
  后续轮次（前端靠 init 兜底，可接受）
- WorkBuddy 调研已放弃（无可验证的 CLI 形态）

## 13. 代码约定

- 后端中文注释与 docstring；模块顶部 docstring 说明职责
- 不引入数据库/消息队列，保持零依赖可单机运行
- 新协议族 = adapter.py 一个 build 函数 + 一个 parse 函数 + 两处注册 + main.py 登记处
- 测试为可直接 `python test_xxx.py` 运行的脚本式断言（无 pytest 依赖），保持该风格
- 提交信息风格：简短中文/英文混合，如「多协议族适配」「remove 免费模型.txt」
- `免费模型.txt` 为本地参考文件，已被 .gitignore 排除，**严禁提交**
