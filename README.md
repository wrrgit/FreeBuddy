# FreeBuddy · 多 CLI 群聊

把本地多个 AI CLI（deveco、opencode，同一 CLI 可开多个"窗口"）放进一个群聊：
用户提问后，多个成员各自回答、互相赞同 / 反对 / 追问、另起新话题，最后由主持人总结。
每条消息带结构化动作与引用链，全程可追溯。

## 特性

- **多成员群聊**：成员 = CLI × 模型 × 角色。同一个 CLI 可以创建多个成员（不同模型 / 不同角色 / 独立会话）
- **结构化讨论**：每条消息带动作（发言 / 赞同 / 反对 / 追问 / 新话题 / 总结），反对必须指向具体消息 ID，点击徽章可跳转溯源
- **分工与独立见解**：成员角色可自定义（研究员 / 评审员 / 魔鬼代言人…），prompt 中强制要求"不附和、不确定要明说"
- **事实与追溯**：消息要求携带 citations；每条消息记录 CLI、模型、session、token 成本、原始输出；会话全量落盘 JSONL（`backend/data/logs/`）
- **主持人调度**：规则化轮转（首轮全员观点 → 逐轮表态 → 主持人总结），支持轮数上限、随时停止、运行中插话
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
2. 输入问题，选择讨论轮数，点击"开始讨论"
3. 观察群聊：成员依次发言，动作徽章（赞同 / 反对 → #消息ID）可点击跳转
4. 讨论中可"插话"（下一轮可见）或"停止"；结束后主持人输出总结
5. 消息下方"来源信息"可展开查看模型 / token / 成本与原始输出

## 扩展新 CLI

`app/adapter.py` 的适配器面向「`<cli> run --format json` + stdin」协议。
支持该协议的 CLI（如 opencode 系）只需在 `main.py` 的 `SUPPORTED_CLIS` 中加入名字；
协议不同的 CLI（如 `claude -p`、`codex exec`）需在 `adapter.py` 中新增对应的
`build_cmd` 与事件解析分支。

## 测试

```bash
cd backend
python test_e2e.py   # 解析器单测 + 2 成员真实群聊（1 轮 + 总结）
python test_ws.py    # WebSocket 全链路（需先启动服务）
```
