# LifeOps 完整化路线：本地演示优先

## Summary
下一阶段目标不是继续堆旅行规划细节，而是把 LifeOps 从“可运行 Agent MVP”推进成“可演示、可继续扩展、工程上站得住”的项目。默认交付形态为本地演示优先：一键启动前后端、Docker Compose、CI、API 文档、稳定配置和基础可观测性先落地；随后做 LangGraph 原生化、工具稳定性，再扩展日程/跑腿/餐饮/周计划等 LifeOps 场景。

当前事实：
- 后端 `D:\llm\LifeOps` 已有 FastAPI、SSE `/runs/plan`、历史、画像、反馈、SQLite trace。
- 前端 `D:\llm\lifeops-front` 已是 React/Vite 多页应用，包含规划页、运行页、详情页、历史页、画像页、反馈入口。
- 后端 LangGraph 仍是手写 pipeline，`agent/langgraph_app.py` 只是包了一层 `run_lifeops`。
- 缺 Docker、compose、启动脚本、CI、docs、日志/配置规范、数据库路径配置和工具健康检查。

## Key Changes
### 1. 工程化第一阶段
- 后端新增 `Dockerfile`，启动命令固定为 `uvicorn api:app --host 0.0.0.0 --port 8000`。
- 前端新增 `Dockerfile`，使用 Vite build 后以静态服务方式暴露 `5173` 或 `8080`，构建期读取 `VITE_LIFEOPS_API_BASE`。
- 根级或 `D:\llm` 级新增 `docker-compose.yml`，包含：
  - `lifeops-api`
  - `lifeops-front`
  - SQLite 数据卷挂载到后端 `/app/data/lifeops.sqlite3`
- 后端 `storage/db.py` 将数据库路径改为环境变量：
  - `LIFEOPS_DB_PATH`
  - 默认仍兼容当前 `lifeops.sqlite3`
- 新增本地启动脚本：
  - Windows: `scripts/dev.ps1`
  - 可选 Unix: `scripts/dev.sh`
  - 行为：检查后端依赖、启动 FastAPI、启动 Vite、打印两个 URL。
- 新增 `.env.example` 对齐：
  - 后端保留 LLM/weather/place/search 配置。
  - 新增 `LIFEOPS_DB_PATH`、`LOG_LEVEL`。
  - 前端保留 `VITE_LIFEOPS_API_BASE=http://localhost:8000`。
- `.gitignore` 保持并补齐：
  - `.env`
  - `lifeops.sqlite3`
  - `data/geocode_cache.json`
  - `__pycache__/`
  - `dist/`
  - `node_modules/`
  - `*.tsbuildinfo`

### 2. CI 与文档
- 新增 GitHub Actions workflow：
  - 后端：安装 Python 依赖，运行 `python -m py_compile api.py agent/graph.py agent/nodes.py`，再跑轻量单测 `python -m unittest tests.test_api_imports tests.test_geocoder_weather`。
  - 前端：`npm ci`，`npm run build`。
- 新增 `docs/API.md`，记录当前稳定接口：
  - `POST /runs/plan`
  - `GET /runs/{trace_id}`
  - `GET /runs/{trace_id}/events`
  - `GET /history`
  - `GET /history/{task_id}`
  - `GET /profile`
  - `POST /feedback`
- 新增 `docs/DEVELOPMENT.md`：
  - 本地 Python 启动
  - 本地 Vite 启动
  - Docker Compose 启动
  - `.env` 配置说明
  - 常见问题：搜索慢、Bocha 403、DuckDuckGo 超时、SQLite 文件位置。
- 新增 `docs/ROADMAP.md`：
  - 前端产品化已完成的部分
  - LangGraph 原生化待办
  - 工具稳定性待办
  - LifeOps 场景扩展顺序。

### 3. LangGraph 原生化第二阶段
- 保留现有 `run_lifeops(...)` 外部调用签名，避免破坏 FastAPI 和前端。
- 新增真正的 StateGraph 构建：
  - `extract_constraints`
  - `normalize_dates`
  - `load_memory`
  - `check_clarification`
  - `plan_steps`
  - `call_tools`
  - `score_candidates`
  - `generate_plan`
  - `check_risks`
  - `reflect`
  - `final_response`
- 条件边：
  - `check_clarification` 为真时直接进入 `final_response`
  - `reflect.next_action == "replan"` 时进入一次 replan 子流程
  - replan 子流程复用 `call_tools -> score_candidates -> generate_plan -> check_risks -> reflect`
- 保留现有 progress callback 和 trace 记录；LangGraph 节点执行前后仍发同样 SSE 事件，前端无需改接口。
- 新增测试验证：
  - 完整规划成功
  - 信息不足进入澄清
  - 反思触发一次重规划
  - 旧 `run_lifeops` 返回结构不变。

### 4. 工具稳定性第三阶段
- 为真实工具统一增加超时、错误结构和 provider 健康状态：
  - weather
  - web_search
  - places
  - route
- 新增 `GET /health/providers`：
  - 返回每个 provider 的配置状态、最近错误、是否可用。
- 搜索质量增强：
  - 保留当前 fallback：SearchFree/DuckDuckGo/Wikimedia/Bocha。
  - 增加结果质量字段：`results_count`、`usable_sources_count`、`provider_attempts`。
  - 搜索失败时最终计划必须展示“来源不足”提示，而不是静默降级。
- 票价/营业时间增强：
  - 只从地图字段或搜索摘要中抽取明确数字/免费信息。
  - 未确认继续保持 `cost_known=false`。
  - 不做编造式营业时间。

### 5. LifeOps 场景扩展第四阶段
在旅行/本地出行稳定后，按最小闭环逐步扩展：
- 跑腿任务：地点角色、任务顺序、路线优先。
- 待办拆解：目标拆分、优先级、预计时长。
- 餐饮计划：预算、口味、距离、禁忌。
- 周计划/月计划：多日任务分配、节奏控制。
- 日程提醒/日历写入：先生成 ICS，本地下载；写入系统日历必须用户确认。
- 多轮任务状态追踪：保存上轮计划、变更说明、重规划理由。
- 用户长期偏好管理：继续使用 feedback/profile，后续再做显式编辑页。

## Test Plan
- 后端轻量验证：
  - `python -m py_compile api.py agent/graph.py agent/langgraph_app.py agent/nodes.py storage/db.py`
  - `python -m unittest tests.test_api_imports tests.test_geocoder_weather`
- 前端验证：
  - `npm run build`
  - 浏览器打开 `/`
  - 提交一次规划，确认进入 `/runs/:traceId`
  - 确认 SSE/轮询能显示执行过程
  - 完成后进入 `/plans/:id`
  - 历史页能打开计划
  - 反馈能提交并在画像页体现
- Docker 验证：
  - `docker compose up --build`
  - 访问 `http://localhost:5173`
  - API 健康检查 `http://localhost:8000/health`
  - 生成一次计划后 SQLite 数据卷中存在历史记录。
- LangGraph 验证：
  - 与旧 pipeline 返回字段保持兼容。
  - 至少覆盖 success、need_clarification、auto_replan 三条路径。
- 工具稳定性验证：
  - 模拟搜索失败时仍返回可解释的降级结果。
  - provider health 能显示未配置 key、超时、最近错误。

## Assumptions
- 下一阶段按“本地演示优先”推进，不做云端部署、账号系统、权限系统和正式监控平台。
- 前后端继续保持两个兄弟目录：`D:\llm\LifeOps` 和 `D:\llm\lifeops-front`。
- FastAPI 继续作为唯一后端入口；Streamlit `app.py` 保留为调试台，不作为正式产品 UI。
- SQLite 继续作为本地持久化方案；只增加路径配置和容器卷，不引入 PostgreSQL。
- 现有前端能力保留，不重写 UI，只修补接口、运行稳定性和移动端细节。
- LangGraph 原生化必须保持现有 API 响应结构，避免前端二次重接。