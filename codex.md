# LifeOps Codex Notes

> 新对话开始执行任何修改前，请先阅读本文件。它是项目交接记录，用来快速理解当前实现、设计取舍、最近更新和下一步优先级。

## 项目定位

LifeOps 是一个生活任务规划 Agent。当前重点在旅行/本地出行计划：用户输入自然语言需求后，系统抽取城市、日期、预算、偏好、禁忌和节奏，调用天气、网页搜索、地图地点、路线和预算工具，生成可执行计划，并在 Streamlit 调试台展示中间过程。

目标不是“凭内置 mock 地点拼时间表”，而是：
- 先搜索目的地攻略、路线、票价/预约、近期活动和注意事项。
- 再结合天气、地图地点和用户偏好生成路线。
- 输出自然、完整、有依据，像一份真正可用的轻攻略。

## 当前执行流程

```text
user input
-> extract_constraints
-> normalize_dates
-> load_memory
-> check_clarification
-> plan_steps
-> call_tools: weather / web_search / place_search
-> score_candidates
-> generate_plan: route / budget / rule plan / optional LLM plan
-> check_risks
-> reflect
-> final_response
-> SQLite trace
```

## 关键实现位置

- `agent/nodes.py`
  - 主流程节点、搜索 query 构造、地点证据/票价补全、地点选择、最终回答渲染。
  - 最终回答由 `_build_assistant_message_from_plan` 统一生成，避免 LLM 输出旧模板。
- `tools/web_search.py`
  - 搜索后端：`auto`、`bocha`、`duckduckgo`、`wikimedia`。
  - `auto` 优先 Bocha，失败后尝试 DuckDuckGo，再尝试 MediaWiki。
- `tools/places.py`
  - 地点搜索，支持 Amap / OSM / mock。
  - Amap 地点会生成高德地图可跳转链接。
  - 额外搜索特色餐厅和酒店；用户指定“汉庭”时应优先搜索汉庭。
- `tools/weather.py`
  - 天气工具，支持 Amap / OpenMeteo / OpenWeather / mock。
- `tools/budget.py`
  - 预算拆分：活动费、餐饮、交通、总计、未确认票价项。
- `services/date_resolver.py`
  - 相对日期解析。
  - 注意：“下周六”必须解析为下一周周六，不是最近的周六。
- `services/scorer.py`
  - 候选地点评分，考虑偏好、运动量、预算、停留时长、天气和节奏。
- `app.py`
  - Streamlit 调试界面，包含网页搜索等调试信息。

## 最近更新记录

### 2026-05-27

1. 搜索工具改造
   - 增加 Bocha 搜索。
   - 增加 DuckDuckGo 免费搜索。
   - 增加 MediaWiki / Wikipedia / Wikivoyage 兜底搜索。
   - 增加 `SEARCH_PROVIDER=auto` 自动回退。
   - Bocha 403 可能是 key 格式、套餐余额或配额问题；如果返回 `You do not have enough money or package quota`，说明鉴权通过但余额/配额不足。

2. 旅行回答改造
   - 输出从干燥时间表改为自然攻略结构。
   - 增加执行摘要、天气节奏、搜索结论、主线方案、替换玩法、预算拆分、衣食住行、提醒、参考来源。
   - 地点名称使用地图链接，方便用户点击确认位置。
   - 不再让 LLM 随意编地点，路线只用工具返回的候选地点。

3. 用户偏好和禁忌
   - “不喝咖啡/不想喝咖啡”会进入 avoid，避免继续推荐咖啡。
   - “喜欢爬山/运动量多”会优先选择山、登山道、森林公园、步道等。
   - “不想太轻松”应识别为中等节奏，而不是轻松。

4. 预算和费用
   - 删除按地点类型猜费用的逻辑。
   - 仅当 Amap `biz_ext.cost` 或网页搜索摘要能确认票价时，才计入活动费。
   - 未确认票价时展示“未确认票价，暂不计入活动费”。
   - 如果搜索明确显示免费/免门票，要标记为已确认 0 元，而不是未确认。
   - 预算 500 不是只要低于 500 就行，应尽量把方案价值做足，餐饮/交通/可能门票预留要更贴近预算。

5. 地点选择
   - 避免连续选择多个相似地点，比如同区域公园、跑道、沿江公园。
   - 默认无明确偏好时，应优先目的地热门/经典景点，例如杭州应优先考虑西湖相关路线，而不是只选普通公园。
   - 搜索证据命中的地点和经典地标有更高优先级。

6. 餐饮和住宿
   - 地图工具额外搜索特色餐厅和酒店。
   - 输出中应列出本地餐厅/美食候选和酒店候选，而不是泛泛说“附近吃饭/附近住宿”。
   - 用户说“要住汉庭”时，酒店搜索关键词应使用“汉庭”，不要泛泛推荐其它酒店。

7. 日期解析
   - 修复目标：`下周六` 从 2026-05-27 解析为 2026-06-06。
   - `周六` 从 2026-05-27 仍解析为 2026-05-30。

## 输出质量要求

旅行计划最终回答应尽量包含：
- 执行摘要：说明用了哪些工具和搜索到了多少可用资料。
- 天气与节奏：日期、天气、温度、户外风险和穿着建议。
- 搜索结论：把网页中的路线、景点、预约、票价、活动、美食或注意事项整合进计划。
- 主线方案：每个地点包含时间、可点击名称、地址、停留时长、费用状态、怎么玩、为什么选。
- 可替换玩法：给用户留选择空间。
- 预算拆分：活动费、餐饮、交通、总计、未确认票价。
- 衣食住行：本地美食/餐厅、用户指定酒店或合适酒店、交通建议。
- 提醒：天气、预约、证件、营业时间、路面湿滑等。
- 参考来源：网页标题和链接。

语气要求：
- 中文自然表达。
- 可适当使用少量 emoji 和粗体标题。
- 不要输出隐藏推理链，但可以展示“我搜索了什么、搜索结果如何影响计划”的可观测执行摘要。

## 重要约束

- 不要凭空编造店名、票价、营业时间、活动和预约规则。
- 搜索失败时要透明说明，改用天气/地图数据，并标注票价和营业时间待确认。
- 不要从 `data/mock_places.json` 的旧偏好标签直接凑答案，除非真实工具不可用且已明确是 fallback。
- 不要因为预算低就只给 0 元景点；预算代表用户承受范围，也应考虑体验价值。
- 不要为了一个个例硬编码过多规则；评分和筛选逻辑要尽量通用。

## 推荐验证方式

不要每次都跑完整测试，网络和 LLM 会很慢。优先做小范围验证：

```bash
python -m py_compile agent/nodes.py tools/places.py services/date_resolver.py
```

日期解析可用 Unicode 字符串快速验证，避免 PowerShell 中文编码问题：

```bash
python - <<'PY'
from datetime import date
from services.date_resolver import resolve_date_text
print(resolve_date_text('\u4e0b\u5468\u516d', today=date(2026, 5, 27)))
print(resolve_date_text('\u5468\u516d', today=date(2026, 5, 27)))
PY
```

需要完整回归时，优先跑相关单测，不要无脑跑全量：

```bash
python -m unittest tests.test_flow.LifeOpsFlowTest.test_not_too_relaxed_sets_medium_pace_and_dynamic_budget
python -m unittest tests.test_flow.LifeOpsFlowTest.test_avoid_coffee_outputs_clickable_places
python -m unittest tests.test_flow.LifeOpsFlowTest.test_fuzhou_hiking_prefers_mountain_routes
```

## 当前已知问题

- PowerShell 直接输出中文可能显示乱码，实际文件多为 UTF-8；调试中文输入时可用 Unicode escape。
- DuckDuckGo、MediaWiki 依赖外部网络，可能偶发超时。
- Bocha 如果套餐余额/配额不足会返回 403，即使请求头格式正确也无法使用。
- 网页摘要里的票价识别依赖正则，可能漏掉复杂票价，例如套票、游船另收费、淡旺季价格。
- 餐厅/酒店候选仍可能需要进一步按主线地点距离过滤，避免推荐太远。

## 下一步优先级

1. 继续提升搜索摘要利用率：从网页中抽取路线主题、预约提示、票价提示、美食和住宿区域。
2. 强化地点热度排序：结合搜索标题/摘要命中、经典地标词、评分和距离。
3. 酒店和餐厅按主线区域过滤，尤其是用户指定品牌时优先展示该品牌。
4. 优化最终文案，加入少量 emoji，并减少机械句式。
5. 票价解析继续保守增强，只使用可确认来源。
