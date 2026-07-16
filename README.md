# LifeOps Agent

LifeOps Agent 是一个面向真实生活任务的 AI Agent 规划系统。它把用户的一句话需求拆解成可执行计划，并通过工具调用、候选评分、风险检查和执行记录，让大模型从“聊天回答”变成“可追踪的生活任务规划器”。

项目已完成后端 Agent、FastAPI 服务、React 前端、SQLite 记录、工具链封装、自动化测试和 Docker 化配置，可作为大模型应用工程/Agent 系统方向的面试展示项目。

## 系统功能

- 自然语言任务理解：识别用户目标、时间、地点、预算、偏好、限制和任务类型。
- 多工具协同规划：封装天气、地点、路线、网页搜索、预算和用户记忆等工具。
- Agent 工作流编排：通过约束抽取、澄清判断、计划生成、候选评分、风险检查、反思修正形成闭环。
- 可追踪执行记录：每次运行保存 trace、状态、工具结果和最终计划，便于复盘和调试。
- 用户画像与反馈：保存偏好、避雷项和计划反馈，让系统具备持续优化的基础。
- API 服务：提供 `/app/*` 计划生成、运行状态、历史记录、用户画像、反馈、审计和确认后日历导出能力。
- React 前端：提供规划工作台、结果页、历史、画像、审计和展示页。
- 本地调试界面：保留 Streamlit 页面，方便快速验证 Agent 输出。
- 工程化交付：包含测试、Dockerfile、docker-compose、CI 配置和环境变量模板。

## Agent 流程

```text
user input
-> constraint extractor
-> date resolver
-> memory tool
-> clarification check
-> planner
-> tools: weather / places / web search / route / budget
-> candidate scorer
-> plan generator
-> risk checker
-> reflection
-> final response
-> SQLite trace
```

## 项目亮点

### 1. 从 Prompt Demo 到 Agent 工程闭环

项目不是单次调用大模型，而是把任务理解、工具调用、计划生成、风险控制和结果落库拆成清晰节点。每个节点都有明确输入输出，方便调试、测试和后续扩展。

### 2. 多工具路由与证据驱动规划

系统根据任务类型选择不同工具链，把天气、地点、路线、搜索、预算和用户记忆整合进统一计划生成流程，体现了大模型应用中“LLM + Tools”的工程设计能力。

### 3. 可观测、可复盘、可测试

每次运行会留下 trace 和历史记录，测试覆盖任务分类、工具分支、日期解析、偏好反馈、风险检查和 API 导入等关键路径，避免 Agent 输出完全黑盒化。

### 4. 前后端可联动展示

后端提供 FastAPI 服务，前端项目 `lifeops-front` 提供可视化操作台和项目展示页，可以在面试中同时展示系统架构、业务流程和交互体验。

## 技术栈

- Python 3.11+
- FastAPI
- Pydantic
- SQLite
- Streamlit
- LangGraph Agent workflow
- OpenAI-compatible LLM client
- OpenMeteo / OpenStreetMap / Web Search 工具封装
- unittest
- Docker / docker-compose

## 项目结构

```text
LifeOps/
├── agent/              # Agent 状态、节点、提示词和工作流编排
├── tools/              # 天气、地点、路线、搜索、预算、记忆等工具
├── services/           # LLM 客户端、评分、风险检查、日期解析、trace 记录
├── storage/            # SQLite schema 与读写逻辑
├── tests/              # 单元测试与流程测试
├── docs/               # API、开发说明和 Agent 图文档
├── api.py              # FastAPI 服务入口
├── app.py              # Streamlit 调试界面
├── config.py           # 环境配置
├── docker-compose.yml  # 本地容器编排
└── requirements.txt
```

## 快速运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

启动 API 服务：

```powershell
uvicorn api:app --reload
```

启动 React 前端：

```powershell
cd D:\llm\lifeops-front
npm install
$env:VITE_LIFEOPS_API_BASE="http://localhost:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

运行测试：

```powershell
python -m unittest discover -s tests
```

使用 Docker：

```powershell
docker compose up --build
```

## 环境变量

复制 `.env.example` 为 `.env`，按需配置模型和工具提供方。项目默认保留无 Key 工具的兜底能力，真实 Key 不应提交到仓库。

```env
LIFEOPS_LLM_MODE=deepseek
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash

WEATHER_PROVIDER=openmeteo
PLACE_PROVIDER=osm
AMAP_API_KEY=

SEARCH_PROVIDER=auto
BOCHA_API_KEY=
SEARCH_FRESHNESS=noLimit
SEARCH_SUMMARY=true
SEARCH_COUNT=8
```

## 前端展示

配套前端仓库：`D:\llm\lifeops-front`

前端提供计划输入、执行状态、计划详情、历史记录、用户画像、审计和项目展示页。面试展示时可以先从前端介绍产品体验，再切回本仓库说明 Agent 工作流和后端工程实现。
