# LifeOps Agent 项目展示

## 项目定位

LifeOps 是一个面向普通用户出行与生活路线的 AI Agent 规划系统。用户输入一句自然语言需求，系统会抽取时间、地点、预算、偏好和限制，再按场景调用天气、地点、网页搜索、路线和预算工具，最终生成可执行、可追踪、可确认的生活计划。

这个项目重点展示的是大模型应用工程能力：不是把问题直接丢给模型，而是把 LLM 放进一个可追踪、可复盘、可迭代的 Agent 闭环。

## 核心能力

- 约束抽取：从模糊需求中识别日期、城市、预算、偏好、避雷项和任务类型。
- 工具路由：按出行、餐饮、待办、路线等场景选择不同工具链。
- 计划生成：输出时间线、地点依据、路线建议、预算估算和风险提醒。
- 反思修正：对候选方案进行评分、风险检查和二次整理。
- 确认边界：日历导出等写入型动作必须先由用户确认。
- 可观测性：通过 SQLite trace 记录中间状态，便于定位 Agent 决策过程。

## 技术栈

- Python 3.11+
- FastAPI
- LangGraph Agent workflow
- Pydantic
- SQLite
- OpenMeteo / OSM / Web Search 工具
- React 前端工作台
- Streamlit 调试界面

## 面试亮点

1. 展示了 Agent 从“能回答”到“能规划、能调用工具、能留下证据”的工程化路径。
2. 通过 trace 和历史记录解决黑盒 Agent 难调试的问题。
3. 通过确认机制控制日历导出等副作用，避免 Agent 自动执行写操作。
4. 支持无 Key 兜底工具，降低本地演示成本，同时保留可扩展的在线工具配置。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload
```

前端项目位于 `D:\llm\lifeops-front`，运行后可访问前端的“展示”页面查看面试版介绍。
