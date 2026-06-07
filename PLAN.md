# LifeOps Agent：高度自主的生活任务规划智能体设计文档

## 1. 项目概述

**LifeOps Agent** 是一个面向真实生活场景的高度自主智能体，帮助用户完成周末安排、日常跑腿、轻旅行、餐饮计划、提醒安排等多步骤生活任务。

它不是简单推荐系统，而是一个能：

- 理解模糊目标
- 抽取约束条件
- 自主拆解任务
- 调用外部工具
- 多约束决策
- 动态重规划
- 记录执行轨迹
- 在关键风险点请求用户确认

的生活任务执行 Agent。

### 一句话定位

> 一个能根据用户偏好、时间、地点、预算、天气和任务优先级，自主规划并动态调整生活安排的 AI 生活运营智能体。

---

## 2. 典型使用场景

### 场景 A：周末计划

用户输入：

```text
这周六我想在杭州轻松玩一天，预算 500，喜欢咖啡、展览和夜景，不想太累。
```

Agent 输出：

- 一日路线
- 时间安排
- 交通建议
- 预算估算
- 天气风险
- 雨天备选
- 可确认事项

---

### 场景 B：日常跑腿

用户输入：

```text
明天下午我要取快递、买生日礼物、顺便吃个晚饭，帮我安排最省时间的路线。
```

Agent 自动处理：

- 任务拆解
- 地点排序
- 营业时间检查
- 路线优化
- 时间冲突判断
- 生成行动清单

---

### 场景 C：动态重规划

用户继续输入：

```text
太赶了，帮我改轻松一点。
```

Agent 应该基于已有计划调整，而不是重新生成一份无关计划。

---

## 3. 高度自主智能体应具备的能力

### 3.1 目标理解能力

Agent 需要从自然语言中识别：

- 用户想完成什么
- 时间范围
- 地点范围
- 预算
- 偏好
- 禁忌
- 强约束和软约束

示例结构化结果：

```json
{
  "goal": "规划杭州周六一日游",
  "city": "杭州",
  "date": "本周六",
  "budget": 500,
  "pace": "轻松",
  "preferences": ["咖啡", "展览", "夜景"],
  "avoid": ["太累", "路线太赶"]
}
```

---

### 3.2 自主规划能力

Agent 不直接回答，而是先生成任务计划：

```text
1. 补全必要信息
2. 查询天气
3. 搜索候选地点
4. 筛选营业时间和预算
5. 计算路线顺序
6. 生成主计划
7. 生成备选计划
8. 检查风险
9. 输出结果
```

---

### 3.3 工具调用能力

MVP 阶段建议支持以下工具：

| 工具 | 作用 | MVP 实现 |
|---|---|---|
| `weather_tool` | 查询天气 | Mock 数据或 OpenWeather |
| `place_search_tool` | 查询地点 | Mock 数据或高德 API |
| `route_tool` | 估算路程 | Mock 距离或地图 API |
| `budget_tool` | 估算费用 | 规则函数 |
| `memory_tool` | 读取用户偏好 | SQLite |
| `calendar_tool` | 生成日程 | 本地 JSON / ICS 文件 |

---

### 3.4 多约束决策能力

候选地点不应随机选择，而应根据评分函数排序。

评分维度：

```text
总分 = 偏好匹配 + 距离便利 + 预算适配 + 时间适配 + 天气适配 - 体力消耗 - 风险惩罚
```

示例：

```json
{
  "place": "浙江美术馆",
  "score": 87,
  "reasons": [
    "符合展览偏好",
    "室内活动，天气风险低",
    "预算可控",
    "适合轻松节奏"
  ]
}
```

---

### 3.5 记忆能力

记忆分三类：

| 类型 | 内容 | 存储 |
|---|---|---|
| 短期记忆 | 当前对话、当前计划、用户刚刚修改的要求 | Agent State |
| 长期偏好 | 喜欢咖啡、讨厌排队、预算偏好 | SQLite |
| 历史任务 | 曾经生成过的计划、反馈、失败原因 | SQLite / Chroma |

长期记忆示例：

```json
{
  "user_id": "default",
  "likes": ["咖啡", "展览", "夜景"],
  "dislikes": ["爬山", "排队", "太赶"],
  "pace": "轻松",
  "budget_style": "中等"
}
```

---

### 3.6 动态重规划能力

Agent 必须支持用户追问：

```text
太贵了
太远了
不要室外
我只有半天
我想加一个朋友
下雨怎么办
```

系统行为：

- 保留原计划上下文
- 更新约束条件
- 只重新计算受影响部分
- 输出变化说明

示例：

```text
已将预算从 500 调整到 300。
主要变化：
- 删除高消费晚餐
- 替换为附近简餐
- 保留咖啡和展览
- 夜景活动改为免费地点
```

---

### 3.7 人类确认能力

高度自主不是完全自动。以下情况必须请求确认：

| 情况 | 是否自动执行 |
|---|---|
| 查询天气、地点 | 自动 |
| 生成计划 | 自动 |
| 写入本地日程 | 需确认 |
| 发送通知给他人 | 需确认 |
| 产生付费预订 | 必须确认 |
| 删除历史记忆 | 必须确认 |

---

## 4. 系统架构

```text
User Input
  ↓
Intent Parser
  ↓
Constraint Extractor
  ↓
Agent State
  ↓
Planner
  ↓
Tool Router
  ↓
Tools: Weather / Place / Route / Budget / Memory
  ↓
Candidate Scorer
  ↓
Plan Generator
  ↓
Risk Checker
  ↓
Reflection / Replan
  ↓
Final Response
```

---

## 5. 推荐技术栈

### 后端

```text
Python
FastAPI
LangGraph
OpenAI API
Pydantic
SQLite
```

### 可选工具

```text
高德地图 API
OpenWeather API
Tavily Search API
Chroma / FAISS
Streamlit
```

### MVP 建议

第一版不要接太多真实 API。

优先做：

```text
LangGraph + SQLite + Mock Tools + Streamlit
```

这样更容易完成，也能清楚展示 Agent 架构。

---

## 6. 核心模块设计

### 6.1 Agent State

```python
class AgentState(BaseModel):
    user_input: str
    goal: str | None = None
    constraints: dict = {}
    user_profile: dict = {}
    plan_steps: list[dict] = []
    tool_results: list[dict] = []
    candidates: list[dict] = []
    final_plan: dict | None = None
    risks: list[str] = []
    need_human_confirm: bool = False
    trace_id: str
```

---

### 6.2 Constraint Extractor

职责：

- 从用户输入中抽取结构化约束
- 判断是否缺少关键信息
- 缺失信息少时使用默认值
- 缺失信息关键时请求用户补充

关键字段：

```json
{
  "city": "杭州",
  "date": "周六",
  "time_window": "全天",
  "budget": 500,
  "pace": "轻松",
  "preferences": ["咖啡", "展览", "夜景"],
  "companions": "未指定"
}
```

---

### 6.3 Planner

职责：

- 根据目标生成执行步骤
- 决定需要调用哪些工具
- 判断是否进入重规划流程

计划示例：

```json
[
  {"step": "读取用户偏好", "tool": "memory_tool"},
  {"step": "查询天气", "tool": "weather_tool"},
  {"step": "搜索候选地点", "tool": "place_search_tool"},
  {"step": "估算路线", "tool": "route_tool"},
  {"step": "计算预算", "tool": "budget_tool"},
  {"step": "生成计划", "tool": "llm"}
]
```

---

### 6.4 Tool Router

职责：

- 接收 Planner 的步骤
- 调用对应工具
- 将结果写回 Agent State
- 捕获工具失败

工具返回统一格式：

```json
{
  "tool_name": "weather_tool",
  "status": "success",
  "data": {},
  "error": null,
  "latency_ms": 120
}
```

---

### 6.5 Candidate Scorer

候选地点评分维度：

| 维度 | 权重 |
|---|---|
| 偏好匹配 | 30% |
| 距离便利 | 20% |
| 预算适配 | 20% |
| 时间适配 | 15% |
| 天气适配 | 10% |
| 体力消耗 | 5% |

输出：

```json
{
  "name": "某美术馆",
  "score": 88,
  "tags": ["展览", "室内", "低强度"],
  "estimated_cost": 60,
  "risk": "周末可能排队"
}
```

---

### 6.6 Risk Checker

检查：

- 是否超预算
- 是否太赶
- 是否路线绕
- 是否存在天气风险
- 是否有营业时间冲突
- 是否需要用户确认

示例：

```json
{
  "risks": [
    "晚餐预算可能超出预期",
    "夜景点为室外，下雨时体验下降"
  ],
  "fallbacks": [
    "下雨时将湖边散步替换为室内书店"
  ]
}
```

---

### 6.7 Reflection

Reflection 用来判断计划质量：

```json
{
  "passed": false,
  "issues": [
    "预算超过用户限制",
    "下午路线过于分散"
  ],
  "next_action": "replan"
}
```

如果未通过，Agent 回到 Planner 重新调整。

---

## 7. 可观察性设计

高度自主 Agent 必须可观察，否则很难调试。

### 7.1 Trace 日志

每次任务生成一个 `trace_id`。

记录：

```json
{
  "trace_id": "20260527_001",
  "user_input": "周六杭州玩一天...",
  "steps": [
    {
      "node": "constraint_extractor",
      "input": "...",
      "output": {},
      "latency_ms": 300
    },
    {
      "node": "weather_tool",
      "input": {"city": "杭州"},
      "output": {"weather": "rain"},
      "latency_ms": 120
    }
  ]
}
```

---

### 7.2 指标监控

MVP 可记录到本地 SQLite。

关键指标：

| 指标 | 含义 |
|---|---|
| `task_success_rate` | 计划是否成功生成 |
| `clarification_rate` | 主动追问比例 |
| `replan_count` | 重规划次数 |
| `tool_error_rate` | 工具失败率 |
| `avg_latency` | 平均响应耗时 |
| `budget_violation_count` | 超预算次数 |
| `human_confirm_count` | 人类确认次数 |

---

### 7.3 可视化调试页

Streamlit 页面展示：

- 用户输入
- 抽取出的约束
- Agent 执行步骤
- 工具调用结果
- 候选地点评分
- 最终计划
- 风险提示
- trace 日志

这能明显体现工程能力。

---

## 8. 数据存储设计

### 8.1 SQLite 表

#### user_profile

```sql
CREATE TABLE user_profile (
  user_id TEXT PRIMARY KEY,
  likes TEXT,
  dislikes TEXT,
  pace TEXT,
  budget_style TEXT,
  updated_at TEXT
);
```

#### task_history

```sql
CREATE TABLE task_history (
  task_id TEXT PRIMARY KEY,
  user_id TEXT,
  user_input TEXT,
  final_plan TEXT,
  feedback TEXT,
  created_at TEXT
);
```

#### agent_trace

```sql
CREATE TABLE agent_trace (
  trace_id TEXT,
  step_index INTEGER,
  node_name TEXT,
  input_json TEXT,
  output_json TEXT,
  latency_ms INTEGER,
  status TEXT,
  created_at TEXT
);
```

---

## 9. MVP 范围

### 必做功能

- 自然语言输入
- 约束抽取
- 缺失信息追问
- Mock 天气工具
- Mock 地点工具
- 候选地点评分
- 一日计划生成
- 风险检查
- 动态重规划
- SQLite 记录 trace
- Streamlit 简单界面

### 暂不做

- 真实支付
- 自动下单
- 自动发消息
- 真实订票
- 多用户权限系统
- 复杂地图路径规划

---

## 10. 项目目录建议

```text
lifeops-agent/
  app.py
  requirements.txt
  README.md

  agent/
    graph.py
    state.py
    nodes.py
    prompts.py

  tools/
    weather.py
    places.py
    route.py
    budget.py
    memory.py

  services/
    scorer.py
    risk_checker.py
    trace_logger.py

  storage/
    db.py
    schema.sql

  data/
    mock_places.json

  tests/
    test_constraint_extractor.py
    test_scorer.py
    test_risk_checker.py
```

---

## 11. LangGraph 流程设计

```text
extract_constraints
  ↓
load_memory
  ↓
need_clarification?
  ├─ yes → ask_user
  └─ no
       ↓
     plan_steps
       ↓
     call_tools
       ↓
     score_candidates
       ↓
     generate_plan
       ↓
     check_risks
       ↓
     reflect
       ├─ pass → final_answer
       └─ fail → replan
```

---

## 12. Prompt 设计

### Constraint Extractor Prompt

```text
你是生活任务规划智能体的约束抽取模块。
请从用户输入中抽取目标、城市、日期、时间、预算、偏好、禁忌和节奏。
如果字段缺失，请返回 null。
只输出 JSON。
```

---

### Plan Generator Prompt

```text
你是生活计划生成模块。
请基于用户约束、天气、候选地点和预算，生成一个可执行的一日计划。
要求：
1. 时间安排合理
2. 不超过预算
3. 节奏符合用户要求
4. 给出每个安排的理由
5. 给出风险和备选方案
```

---

### Reflection Prompt

```text
你是计划质量检查模块。
请判断当前计划是否满足用户目标。
重点检查：
1. 是否超预算
2. 是否太赶
3. 是否符合偏好
4. 是否考虑天气
5. 是否需要用户确认

只输出 JSON：
{
  "passed": true,
  "issues": [],
  "next_action": "final"
}
```

---

## 13. 测试计划

### 单元测试

- 约束抽取是否正确识别城市、预算、偏好
- 评分函数是否优先选择匹配偏好的地点
- 风险检查是否能识别超预算
- 重规划是否能保留原始上下文

### 场景测试

#### 场景 1：信息完整

输入：

```text
周六杭州玩一天，预算 500，喜欢咖啡和展览，不想太累。
```

预期：

- 不追问
- 生成完整计划
- 总预算不超过 500
- 包含咖啡和展览

#### 场景 2：信息缺失

输入：

```text
帮我安排周末。
```

预期：

- 主动询问城市、时间和偏好
- 不直接生成虚假计划

#### 场景 3：用户修改预算

输入：

```text
太贵了，控制在 300。
```

预期：

- 更新预算约束
- 重新规划受影响项目
- 输出变化说明

#### 场景 4：天气风险

输入：

```text
下雨的话怎么办？
```

预期：

- 替换室外活动
- 给出室内备选方案

---

## 14. 验收标准

项目完成后应满足：

- 用户能通过自然语言提交生活任务
- Agent 能结构化理解约束
- Agent 能自主调用至少 3 个工具
- Agent 能输出可执行计划
- Agent 能识别风险
- Agent 能在信息不足时主动追问
- Agent 能支持至少一次动态重规划
- 每次执行都有 trace 记录
- Streamlit 页面能展示 Agent 执行过程

---

## 15. 面试讲解重点

可以这样介绍：

> 我做的不是一个简单的旅游推荐应用，而是一个高度自主的生活任务 Agent。  
> 它会先从用户自然语言中抽取目标和约束，再通过 LangGraph 管理状态流转，调用天气、地点、路线、预算和记忆工具，最后用评分函数和 Reflection 节点生成可执行计划。  
> 我特别设计了可观察性系统，每一步工具调用、重规划原因、风险检查结果都会写入 trace，方便调试和评估 Agent 是否真的可靠。

---

## 16. 默认假设

- 第一版面向单用户使用
- 先使用 Mock 工具保证可运行
- 地图、天气、搜索 API 作为第二阶段扩展
- 不做真实下单、订票、支付
- 重点展示 Agent 架构、自主规划、工具调用、重规划和可观察性
