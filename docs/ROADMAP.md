# LifeOps Roadmap

## 已完成

- Travel / Meal / Errand / Todo 与混合任务规划。
- 多轮上下文继承、预算重规划、任务追加和偏好删除。
- LangGraph 根图与 4 个 Specialist 子图。
- Pydantic Agent Contract、Supervisor 校验和规则回退。
- Specialist 状态隔离、工具白名单和 Provider 降级标记。
- Composer 跨 Agent 合并、Risk Checker、Critic 与最多一次定向修订。
- SQLite 用户画像、历史、trace、反馈和审计。
- FastAPI SSE 进度与 React Multi-Agent 执行详情。
- 74 条后端 unittest 回归目标、9 个离线评估场景、前端 TypeScript/Vite build。
- `LIFEOPS_AGENT_MODE=legacy` 回滚开关。

## 下一阶段：工程可靠性

1. **运行状态持久化**
   - 将当前内存态的 SSE 运行状态持久化到 SQLite；
   - API 重启后仍可查询任务阶段、Agent 状态和最后事件；
   - 为中断任务增加 `failed` / `cancelled` 终态。

2. **Provider 可靠性统一层**
   - 为 LLM、天气、地点和搜索统一 timeout、retry、错误码和熔断状态；
   - 将 Provider 健康状态与 Agent `degraded` 原因关联；
   - 前端明确区分“结果不足”和“外部服务降级”。

3. **评估与 Bad Case 闭环**
   - 为每个版本保存离线评估结果；
   - 失败样例自动生成可复现 JSON；
   - 指标增加任务分类准确率、约束满足率、预算违规率、澄清准确率和平均修订次数。

## 后续产品能力

1. 每日/每周目标拆解与执行复盘。
2. 基于精力、截止日期、重要性和紧急性的任务排序。
3. 日历写入、提醒和外部待办同步，但所有副作用必须经过确认节点。
4. 计划执行状态更新：未开始、进行中、完成、跳过、延期。
5. 基于历史执行结果调整时间估算和计划强度。

## 暂不扩展

- 不继续增加没有独立状态、工具或验收标准的“角色型 Agent”。
- 不让 LLM 自由生成工具名或绕过工具白名单。
- 不开放无限反思循环。
- 不在没有用户确认时执行日历写入、消息发送或删除数据。
