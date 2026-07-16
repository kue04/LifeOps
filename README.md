# LifeOps Agent

LifeOps Agent 是一个面向出行、餐饮、跑腿和待办场景的生活规划系统。系统将自然语言需求转换为结构化意图合同，由 Supervisor 委派专项 Agent，经过工具执行、结果合并、风险检查和 Critic 复核，最终生成可执行、可追踪的计划。

当前项目不是普通 Chatbot：它具备状态流转、任务拆解、工具调用、短期上下文、SQLite 用户画像、失败降级、定向修订和前端执行轨迹展示。

## 当前能力

- 识别任务类型、日期、地点、预算、偏好、避雷项、节奏和出发地/目的地角色。
- 支持 `travel`、`meal`、`errand`、`todo` 以及混合任务。
- 支持多轮重规划，例如修改预算、追加餐饮任务、删除已有偏好。
- Supervisor 使用 Pydantic Contract 生成最多 4 个 `AgentTask`；LLM 不可用或决策非法时自动回退规则 Planner。
- Travel / Meal / Errand / Todo Specialist 在隔离状态中运行各自 LangGraph 子图，并受严格工具白名单限制。
- Composer 合并多个 `AgentProposal`，统一生成路线、预算、时间线和确认动作。
- Risk Checker 与 Critic 检查预算、计划完整性等问题；最多进行一次定向修订，只重跑被判定有问题的 Agent。
- SQLite 保存用户画像、任务历史和 trace；FastAPI 通过 SSE 输出节点与 Agent 级进度。
- React 前端展示 Supervisor 来源、Agent 委派、工具、耗时、降级警告和 Critic 结果。

## Multi-Agent 流程

```text
User Input
  -> Constraint Extractor
  -> Date Resolver
  -> Memory Resolver
  -> Clarification Gate
  -> Supervisor
  -> Travel / Meal / Errand / Todo Specialist Graphs
  -> Composer
  -> Risk Checker
  -> Critic
      -> Final
      -> Targeted Revision (最多一次，只重跑目标 Agent)
```

`LIFEOPS_AGENT_MODE=multi_agent` 为默认模式；设置为 `legacy` 可切回原单图流程，便于回滚和对照测试。

## 为什么使用 LangGraph

LangGraph 的意义不取决于是否使用多个 Agent。单 Agent 系统同样可以利用它管理：

- 可持久化、可检查的共享状态；
- 澄清、工具路由、人工确认和失败恢复等条件分支；
- 有上限的重试与重规划，避免无限循环；
- 节点级 trace、SSE 进度和确定性测试；
- 将副作用放入明确节点，控制执行边界。

本项目进一步把这些能力用于受控 Multi-Agent：根图负责状态和生命周期，Specialist 子图负责领域执行，Critic 只触发目标 Agent 的一次修订。相比自由对话式 Agent，这种设计更容易验证、回滚和展示。

## 工程亮点

### 1. 结构化 Agent Contract

`AgentTask`、`SupervisorDecision`、`AgentProposal`、`AgentRunRecord` 和 `CriticDecision` 均由 Pydantic 校验，防止 Agent 之间使用不稳定的自然语言协议。

### 2. 受控委派与安全回退

Supervisor 决策会检查任务 ID、主任务类型、缺失 Agent、依赖合法性和循环依赖。LLM 输出失败时回退规则决策，保证主流程仍可用。

### 3. 状态隔离与工具白名单

每个 Specialist 深拷贝根状态，只处理自己的任务类型；工具集合固定在代码中，避免跨领域 Agent 随意调用无关工具或污染共享状态。

### 4. 定向 Critic 修订

Critic 将问题映射到对应 Agent，并通过 `revision_targets` 只重跑目标 Specialist。修订轮次限制为 1，兼顾计划质量、延迟和可预测性。

### 5. 可观测与可评估

API 返回 `planner_meta`、`agent_tasks`、`agent_runs`、`memory_resolution` 和 `critic`。仓库提供 9 个确定性离线评估场景，覆盖单领域、混合任务、重规划、澄清和 Provider 回退。

## 技术栈

- Python 3.11+
- FastAPI / Pydantic
- LangGraph
- OpenAI-compatible LLM client
- SQLite
- OpenMeteo / OpenStreetMap / Web Search 工具适配层
- unittest
- React + TypeScript 前端
- Docker / docker-compose

## 项目结构

```text
LifeOps/
├── agent/
│   ├── contracts.py       # Agent 间 Pydantic Contract
│   ├── multi_agent.py     # Supervisor、Dispatcher、Composer
│   ├── specialists.py     # 4 个 Specialist LangGraph 子图
│   ├── critic.py          # Critic 与定向修订目标
│   ├── graph.py           # 根图、分支、SSE 生命周期
│   └── nodes.py           # 约束、工具、计划等领域节点
├── tools/                 # 天气、地点、路线、搜索、预算、记忆工具
├── services/              # LLM、日期、风险、trace 等服务
├── storage/               # SQLite schema 与读写
├── tests/                 # 单元、流程与离线评估数据
├── scripts/               # 开发脚本与离线评估入口
├── docs/                  # 架构、API、路线图和实施记录
├── api.py                 # FastAPI 入口
├── app.py                 # Streamlit 调试界面
└── config.py              # Provider 与 Agent 模式配置
```

## 快速运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload
```

前端：

```powershell
cd D:\llm\lifeops-front
npm install
$env:VITE_LIFEOPS_API_BASE="http://localhost:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

验证：

```powershell
python -m unittest discover -s tests
python scripts/evaluate_agent.py
```

## 环境变量

复制 `.env.example` 为 `.env`。未配置模型 Key 时 Supervisor 自动使用规则回退；工具 Provider 也保留 mock/无 Key 降级路径。

```env
LIFEOPS_AGENT_MODE=multi_agent
LIFEOPS_LLM_MODE=deepseek
DEEPSEEK_API_KEY=

WEATHER_PROVIDER=openmeteo
PLACE_PROVIDER=osm
SEARCH_PROVIDER=auto
```

配套前端仓库位于 `D:\llm\lifeops-front`。
