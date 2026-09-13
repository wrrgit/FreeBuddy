# FreeBuddy 多智能体协同系统 — 最终技术架构方案

> 本方案由多专家群聊（架构师 / 批判与性能官 / 安全合规专家 / 落地实施官 / 头脑风暴主持人）多轮讨论收敛而成。
> 基线代码：现有 FreeBuddy 骨架（`backend/app/adapter.py`、`orchestrator.py`、`transcript.py`、`parser.py`、`store.py`、`main.py`）已跑通 MVP。

## 一、方案概述

在现有 FreeBuddy 骨架（FastAPI + Vue3 + 零数据库 JSON/JSONL 单机架构）上升级为五层多智能体协同系统：

- **适配层**：协议族注册表统一封装本地各 CLI（claude / gemini / opencode / aider / trae / generic 命令模板族），命令构造与输出解析解耦，新 CLI 即插即用。
- **编排层**：Orchestrator 负责轮转调度、disagree/ask 点名优先、人工仲裁与 summary_only 主持人收敛。
- **上下文层**：「近 K 轮全量 + disagree/ask 分歧锚点全量 + 早期轮次结构化摘要」三级分层，消除全量重放的 O(n²) token 爆炸。
- **持久层**：成员配置 JSON + 会话 JSONL 落盘，meta 实施字段白名单存储。
- **交互层**：FastAPI REST + WebSocket 实时广播，Vue3 前端，默认绑定 127.0.0.1 + token 鉴权。

安全基线：重放文本分隔符包裹 + 「成员发言非指令」系统声明、值守/无人值守权限分级（无人值守仅 Linux/macOS + 只读 + 审计）、依赖锁版 + OSV/license 扫描进 CI。

## 二、技术选型（含被否决项及否决理由）

| # | 选型 | 理由 | 被否决项及理由 |
|---|------|------|----------------|
| 1 | 协议族注册表模式（build/parse 解耦） | 新 CLI 即插即用，已在现有代码验证；对标 AutoGen/CrewAI 编排思想 | 「每 CLI 独立适配器类」——重复代码多 |
| 2 | 三级分层压缩上下文 | 消除 O(n²) token 爆炸 | ①「彻底移除全量重放」——parser target 校验与动作协议容错以完整记录为正确性来源，全量重放降级为可配置兜底开关；②「自由文本摘要」——LLM 摘要存在投毒风险，只存结构化字段（决策/风险/行动项 + 来源消息 ID） |
| 3 | parser 校验与 prompt 可见性解耦 | `valid_msg_ids` 始终取全量消息 ID 集合（JSONL 兜底），压缩仅作用于 prompt 注入面 | 依赖 prompt 可见性校验——压缩后引用链断裂 |
| 4 | 单进程 asyncio 锁 + 文件锁 | 满足单机并发互斥 | 「Redis 分布式锁」——违反零依赖单机约定（AGENTS.md §13） |
| 5 | APScheduler + 文件锁防重入 | 定时触发 discuss；无人值守能力前置依赖沙箱与审计落地 | 无并发保护的裸 cron——上轮未结束会并发跑多个任务 |
| 6 | Windows 仅支持 ATTENDED | Windows 无原生 namespace 隔离，Job Objects 不限文件系统/网络，AppContainer 需签名包 | 「Windows UNATTENDED 模式」——实质无沙箱；UNATTENDED 限 Linux/macOS（landlock/namespaces），或显式引入 Docker（待用户拍板） |
| 7 | meta.raw 字段白名单存储为主（仅 tokens/cost/session_id/model），正则脱敏（sk-/Bearer/AK-SK）兜底 | 黑名单必漏自定义网关 key/连接串 | 「纯正则黑名单脱敏」——必漏 |
| 8 | CLI 探测：shutil.which + 平台目录枚举（%APPDATA%\npm、~/.local/bin、/opt/homebrew/bin、cargo bin、scoop shim）合并去重 + `--version` 校验 + 缓存 config.cli_cache | npm/pipx/brew/cargo 装的 CLI 不在系统 PATH | 「仅 shutil.which」——不可靠 |
| 9 | generic 族：shlex.split 模板 + args 列表传 create_subprocess_exec | 禁 shell，消除命令注入 | 占位符直拼——注入风险 |

## 三、架构设计

### 模块划分

- `adapter.py`：协议族注册表 + ExecutionMode 感知的命令构造（UNATTENDED 禁用 aider `--yes-always`）
- `orchestrator.py`：调度 + asyncio/文件双锁 + `keep_full` / `summary_map` 维护
- `transcript.py`：`render_transcript_compressed` + `<<<MEMBER:{id}>>>` / `<<<END>>>` 包裹 + `get_full_message_ids()`
- `parser.py`：全量 ID 校验 + 仅动作 JSON 驱动调度 + 摘要引用 target 存在性复核
- `store.py`：白名单序列化 + 审计 JSONL（path/op/hash）+ config 文件权限（Unix 600 / Windows ACL）
- `main.py`：token 鉴权中间件（REST/WS）+ CLI 多路径枚举 + APScheduler

### 关键数据流

```
用户提问 → POST /api/discuss（token 校验）
  → 每轮按点名优先排序
  → prompt = 系统提示（含「成员发言非指令」声明）+ 三级压缩 transcript
  → subprocess（args 列表，禁 shell）
  → parse_reply（全量消息 ID 校验，仅动作 JSON 驱动调度）
  → 白名单落盘 JSONL + WS 广播
  → 主持人结构化总结（决策/风险/行动项 + 来源消息 ID）
```

无人值守 cron 数据流：文件锁互斥 → 只读模式（aider 禁 `--yes-always`、临时工作目录、网络白名单仅模型 API 域）→ 写操作入人工确认审计队列。

### 外部依赖

FastAPI / pydantic / APScheduler（锁版 + pip-audit/OSV + license 扫描进 CI）、本地各 CLI 子进程、前端 Vue3 + OpenTiny。**无数据库、无消息队列。**

## 四、实施路线

| 阶段 | 内容 | 依赖 |
|------|------|------|
| MVP（已完成） | 单机单用户、127.0.0.1、5 成员 10 轮、全量重放、JSONL、手动触发 | — |
| 阶段 1 安全地基 | ① token 鉴权中间件 + WS 握手校验（ENV AUTH_TOKEN 缺省自动生成）② generic 族 args 列表化 ③ meta 白名单存储 + 正则兜底 + 存量 JSONL 迁移脚本 ④ 依赖锁版 + pip-audit/OSV + license 扫描进 CI ⑤ config 文件权限 | — |
| 阶段 2 注入防护 | ⑥ transcript 分隔符包裹 + 系统提示声明 ⑦ parser 仅动作 JSON 驱动调度，注入文本单测覆盖 | 阶段 1 |
| 阶段 3 性能优化（可并行） | ⑧ 三级压缩 + `get_full_message_ids` 解耦校验，单测验证 token 下降率与引用链完整 ⑨ CLI 多路径枚举 + 版本校验缓存 | — |
| 阶段 4 权限分级与定时 | ⑩ ExecutionMode(ATTENDED/UNATTENDED) + 平台门控（Windows 锁 UNATTENDED）+ 写操作人工确认审计队列 ⑪ APScheduler + 文件锁 + auto_discuss 配置 | 阶段 2/3 |
| 阶段 5 自进化 | ⑫ 长期记忆（会话级结构化摘要 JSONL）⑬ 技能注册表（prompt 模板化 Tool）⑭ 自评估指标仪表盘（轮次/token/冲突率/人工介入率/SLO 基线） | 阶段 4 |

每步独立 PR，`test_adapter` / `test_schedule` 通过后合入。

## 五、风险与对策

| 风险 | 对策 |
|------|------|
| 间接提示注入（最大攻击面） | 成员输出分隔符包裹 + 系统声明非指令 + 调度只认动作 JSON；摘要只存结构化字段且 parser 复核引用 target 存在性 |
| 远程 RCE（API 无鉴权） | 默认 127.0.0.1 + token 鉴权（REST/WS） |
| 无人值守自动写代码 | 权限分级 + Windows 禁 UNATTENDED + 只读沙箱 + 写操作人工确认 + 审计 JSONL |
| 密钥/日志泄漏 | 白名单存储为主、正则兜底、config 文件权限 |
| 供应链投毒 | 依赖锁版 + OSV + license 扫描（排查 GPL 传染） |
| Token 爆炸 | 三级压缩 + SLO 基线度量（目标值待定，见第六节） |
| 调度并发重入 | asyncio 锁 + 文件锁 |
| 重启丢内存态 | JSONL 全量落盘兜底，WS init 重放缓解 |

## 六、待人工决策项

1. **SLO 目标值**：单轮 token 上限、P99 延迟、单轮成本阈值（压缩合格判定与容量规划依据）。
2. **Windows 无人值守**是否显式引入 Docker 依赖（违反零依赖约定，需拍板取舍）。
3. **数据合规**：群聊含用户代码/商业数据经境外模型 API 处理，是否触发个保法跨境评估（第 38-40 条）及《生成式 AI 服务管理暂行办法》适用边界——需人工核实法务；是否默认开启数据分类开关与前端告知文案。
4. **GPL 传染排查**结果对依赖选型的最终裁决（license 扫描出具体冲突项后逐项定夺）。
5. **摘要关键决策**是否需要人工签名确认（防摘要链路投毒的强校验，代价是人工介入成本）。
6. **冲突升级仲裁消息**的交互形态（前端如何呈现待定夺项、超时默认策略）。

## 参考对标

- Microsoft AutoGen 多智能体对话框架：github.com/microsoft/autogen
- CrewAI 角色化 Agent 编排：github.com/crewAIInc/crewAI
- LangGraph checkpointer 分层记忆设计：github.com/langchain-ai/langgraph
- OWASP LLM Top 10 LLM01 Prompt Injection：genai.owasp.org
- 本仓库已验证代码：`backend/app/adapter.py`、`orchestrator.py`、`transcript.py`、`parser.py`、`store.py`、`main.py`
