# LifeOps Agent MVP

一个面向生活任务规划的最小可运行 Agent 闭环。

## 已实现流程

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

## Codex 接手说明

后续新对话或继续开发前，请先阅读 [`codex.md`](codex.md)。该文件记录了当前 Agent 的设计决策、最近更新、已知问题和推荐验证方式，用来让新上下文快速理解项目状态，避免重复踩坑。

当前旅行规划方向的核心要求：
- 先用网页搜索、天气和地图工具获取依据，再生成计划。
- 计划要结合搜索摘要和来源内容，不要只把链接贴在末尾。
- 地点必须来自地图/搜索结果，并提供可跳转地址链接。
- 门票/费用只使用搜索或地图确认到的数据；未确认时明确标注，不凭类型猜价格。
- 默认推荐应按目的地热度和用户偏好排序；用户没有明确偏好时，优先经典景点和高价值路线。
- 输出要覆盖景点、路线、天气、餐饮、住宿、交通、预算和注意事项，语气自然一点。

## 快速运行

```bash
python -m agent.graph
```

运行调试界面：

```bash
streamlit run app.py
```

运行 API 服务：

```bash
uvicorn api:app --reload
```

运行验证：

```bash
python -m unittest discover -s tests
```

## 推荐配置

复制 `.env.example` 为 `.env`，填入 DeepSeek key：

```env
LIFEOPS_LLM_MODE=deepseek
DEEPSEEK_API_KEY=你的 DeepSeek key
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
SEARCH_INCLUDE=
SEARCH_EXCLUDE=
```

说明：

- `openmeteo`：天气工具，不需要 key。
- `osm`：地点工具，使用 Nominatim / OpenStreetMap / Overpass，不需要 key。
- `amap`：高德地点/天气工具；配置 `AMAP_API_KEY` 后可设置 `PLACE_PROVIDER=amap`，也可设置 `WEATHER_PROVIDER=amap`。
- `auto`：优先尝试国内可访问的 `searchfree`，再兜底 DuckDuckGo 和 MediaWiki；不会优先使用博查。
- `searchfree`：免费网页搜索接口，不需要 key，作为国内网络环境下的优先搜索兜底。
- `duckduckgo`：免费网页搜索，不需要 key；适合基础网页检索，但部分网络环境可能超时。
- `wikimedia`：免费百科搜索，不是全网搜索，但适合旅行地点兜底资料。
- `bocha`：可选网页搜索；只有显式设置 `SEARCH_PROVIDER=bocha` 时才使用。

当前已删除腾讯地图相关代码和配置。
