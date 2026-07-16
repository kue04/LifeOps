# LifeOps Agent 项目展示

## 一句话项目简介

设计并实现面向个人生活管理的受控 Multi-Agent 规划系统，将自然语言目标拆解为 Travel、Meal、Errand、Todo 专项任务，通过工具调用、结构化合并、风险检查和定向修订生成可执行计划。

## 项目定位

LifeOps 不是只生成文本的 Chatbot。它使用 LangGraph 管理任务生命周期，使用 Pydantic 定义 Agent 间协议，使用 SQLite 保存画像和 trace，并通过 FastAPI SSE 与 React 前端展示实际执行过程。

## 已实现能力

- Supervisor 根据意图合同委派 1 至 4 个 Specialist，并校验依赖、主任务类型和任务完整性。
- Travel / Meal / Errand / Todo Agent 在隔离状态中运行领域工具链。
- Composer 合并混合任务的时间线、地点、路线、预算和确认动作。
- Critic 识别问题归属，只重跑目标 Agent，且最多修订一次。
- 支持预算调整、追加任务、明确任务切换和偏好删除等多轮重规划。
- 支持 LLM/Provider 降级、规则回退、trace、SSE、审计和 Legacy 模式回滚。

## 可写进简历的版本

- 设计并实现面向个人生活管理的 Multi-Agent 系统，使用 LangGraph 编排 Supervisor、4 类 Specialist、Composer 与 Critic，支持出行、餐饮、跑腿、待办及混合任务规划。
- 基于 Pydantic 构建结构化 Agent Contract，校验任务依赖、输出类型与主任务一致性；在 LLM 决策非法或不可用时自动回退规则 Planner，提升系统可用性与可测试性。
- 为 Specialist 实现状态隔离和严格工具白名单，将天气、地点、搜索、路线、预算与确认动作封装为领域工具链，避免跨 Agent 状态污染和任意工具调用。
- 实现多轮意图继承与 `memory_overrides`，支持预算重排、任务追加、任务切换和偏好删除，解决长期画像覆盖本轮明确要求的问题。
- 建立 Risk Checker + Critic 定向修订机制，只重跑问题所属 Agent，并通过 74 条 unittest、9 个离线场景和前端执行轨迹验证关键链路。

## 面试重点

### 为什么不用自由对话式 Multi-Agent

自由对话难以保证任务终止、工具边界、状态一致性和输出 Schema。本项目采用 Supervisor 受控委派、Specialist 固定职责、Composer 单点合并、Critic 有限修订，使每一步都能记录和测试。

### 如果不做 Multi-Agent，LangGraph 还有意义吗

有。LangGraph 首先解决的是有状态工作流问题：条件分支、恢复、重试、人工确认、trace 和长流程控制。Multi-Agent 只是当前项目在混合生活任务上的进一步拆分，不是使用 LangGraph 的前提。

### 为什么只允许一次修订

Agent 反思循环会放大延迟、成本和不确定性。一次定向修订能修复明显问题，同时给请求时延设置确定上界；无法自动修复的问题转为询问用户。

### 为什么 Agent 之间不用自然语言传递结果

自然语言协议难以验证且容易漂移。项目使用 `AgentTask`、`AgentProposal`、`AgentRunRecord` 和 `CriticDecision`，让错误可以在边界处被发现并回退。

## 演示顺序

1. 输入“周六去杭州看展，再安排一顿火锅”。
2. 展示 Supervisor 同时委派 Meal 与 Travel Agent。
3. 展示每个 Agent 的工具、状态、耗时和 Provider 警告。
4. 展示 Composer 合并后的时间线与预算。
5. 追问“太贵了，控制在 300”，展示上下文继承和重新规划。
6. 追问“不要咖啡店”，展示偏好删除不会被长期画像重新注入。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload
python scripts/evaluate_agent.py
```

前端项目：`D:\llm\lifeops-front`。
