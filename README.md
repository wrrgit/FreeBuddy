# FreeBuddy · 多 CLI 群聊

把本地多个 AI CLI（deveco、opencode，同一 CLI 可开多个"窗口"）放进一个群聊：
用户提问后，多个成员各自回答、互相赞同 / 反对 / 追问、另起新话题，最后由主持人总结。
每条消息带结构化动作与引用链，全程可追溯。

## 特性

- **多成员群聊**：成员 = CLI × 模型 × 角色。同一个 CLI 可以创建多个成员（不同模型 / 不同角色 / 独立会话）
- **协议族适配**：支持 6 个 CLI 协议族，覆盖主流免费 AI 编程 CLI——
  - `opencode_family`：**deveco**、**opencode**（内置免费模型，开箱即用）
  - `gemini_family`：**gemini**（Google 免费额度）、**qwen**（Qwen Code，每日千次免费）
  - `claude_family`：**claude**（Claude Code）
  - `aider_family`：**aider**（配 OpenRouter 免费模型 / Ollama 本地模型）
  - `trae_family`：**traecli**（TraeCode CLI，`exec --json` 无头模式；需 TRAE 账号登录
    或在 `~/.trae/trae_cli.yaml` 配置 OpenAI/Claude 兼容自定义模型）
  - `generic_family`：**自定义命令模板**——任何能"无头：文本进 → 文本出"的 CLI，
    填 `mycli ask {prompt_file}` 这类模板即可进群（占位符：`{prompt_file}` / `{prompt}` / `{model}`）
- **讨论前置判断**：提交问题后，主持人先轻量判断是否需要群聊讨论——
  事实性问答/概念解释等无需讨论的问题由主持人直接回答，不召集成员；
  判断失败一律放行讨论（fail-open）；可勾选「跳过判断，直接讨论」强制开轮
- **结构化讨论**：每条消息带动作（发言 / 赞同 / 反对 / 追问 / 新话题 / 总结），反对必须指向具体消息 ID，点击徽章可跳转溯源
- **分工与独立见解**：成员角色可自定义（架构师 / 批判与性能官 / 安全合规专家 / 落地实施官…），prompt 中强制要求"不附和、不确定要明说"
- **主持人调度**：第 1 轮按列表顺序（设计者先出草案），之后轮次**被反对/追问最多的成员优先回应**，其余随机；支持轮数上限、随时停止、运行中插话；主持人（summary_only）仅在最终轮输出可落地的技术架构方案
- **事实与追溯**：消息要求携带 citations；每条消息记录 CLI、模型、session、token 成本、原始输出；会话全量落盘 JSONL（`backend/data/logs/`）
- **实时 Web UI**：Vue3 + OpenTiny，WebSocket 实时推送，成员面板可视化增删改

## 架构

```
Vue3 + OpenTiny 前端（群聊界面）
        │  REST + WebSocket
Python FastAPI 后端
  ├─ Orchestrator    主持人规则调度（轮转 / 终止 / 总结）
  ├─ Transcript      群聊记录格式化注入（含动作标注与引用）
  ├─ Parser          结构化动作 JSON 容错解析
  ├─ Adapter         subprocess 无头驱动 CLI（stdin 传 prompt，无长度限制）
  └─ Store           成员配置 + JSONL 追溯日志
        │
  deveco run --format json / opencode run --format json
  （--session 会话保持，-m 指定模型）
```

## 快速开始

前置：Python 3.10+，Node 18+，已安装并登录至少一个 CLI（`deveco` 或 `opencode`）。

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（构建后由后端托管）
cd frontend
npm install
npm run build
```

打开 http://127.0.0.1:8000 即可使用。

开发模式（前端热更新）：

```bash
cd frontend
npm run dev   # http://localhost:5173，自动代理 /api 与 /ws 到 8000
```

## 使用

1. 左侧面板添加成员：名称、CLI（deveco / opencode）、模型（留空 = CLI 默认）、角色分工
2. 输入问题，选择讨论轮数，点击"开始讨论"——主持人会先判断问题是否需要讨论：
   不需要则直接给出回答（可展开消息来源查看判断理由），需要则进入多轮群聊；
   勾选「跳过判断，直接讨论」可强制开轮
3. 观察群聊：成员依次发言，动作徽章（赞同 / 反对 → #消息ID）可点击跳转
4. 讨论中可"插话"（下一轮可见）或"停止"；结束后主持人输出总结
5. 消息下方"来源信息"可展开查看模型 / token / 成本与原始输出

## 扩展新 CLI

三种方式，按成本从低到高：

1. **generic 模板**（零代码）：CLI 有任何无头用法即可，在成员编辑中选"自定义命令模板"，
   填如 `mycli ask {prompt_file}`（prompt 自动写入临时文件）或 `mycli ask "{prompt}"`
2. **加入现有协议族**（一行配置）：同构 CLI 只需在 `main.py` 的 `KNOWN_CLIS` 中登记。
   例如新的 opencode fork、gemini fork（如 Qwen Code）
3. **新增协议族**（一个函数）：在 `adapter.py` 中新增 `build_xxx` 命令构造与
   `parse_xxx` 输出解析，注册到 `_BUILDERS` / `_PARSERS` 即可

由于每轮讨论是**全量重放群聊记录**，会话恢复（session resume）只是 token 优化项，
不是接入门槛——只要 CLI 能"接收一段文本 → 返回一段回复"就能参与讨论。

## 测试

```bash
cd backend
python test_adapter.py    # 协议族命令构造与输出解析
python test_schedule.py   # 调度逻辑（summary_only / 被点名优先）
python test_e2e.py        # 2 成员真实群聊（1 轮 + 总结）
python test_ws.py         # WebSocket 全链路（需先启动服务）
```
