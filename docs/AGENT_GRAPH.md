# LifeOps Agent Graph

LifeOps now uses LangGraph to orchestrate the planning flow. The public entry point is still `run_lifeops(...)`; FastAPI and the React frontend do not need to know whether the internals are a hand-written loop or a graph.

## Current Graph

```text
__start__
  ↓
constraint_extractor
  ↓
date_resolver
  ↓
load_memory
  ↓
need_clarification
  ├─ end → __end__
  └─ continue
       ↓
planner
  ↓
task_router
  ├─ travel → travel_tool_router → travel_candidate_scorer → travel_plan_generator
  ├─ errand → errand_tool_router → errand_candidate_scorer → errand_plan_generator
  ├─ meal   → meal_tool_router   → meal_candidate_scorer   → meal_plan_generator
  └─ todo   → todo_decomposer → todo_plan_generator
  ↓
risk_checker
  ↓
reflection
  ├─ final → __end__
  └─ replan → task branch start
```

## Nodes

- `constraint_extractor`: extracts goal, city, date, budget, preferences, avoid rules, pace, origin, and destination hints.
- `date_resolver`: normalizes relative dates such as `周六`, `明天`, and `下周六`.
- `load_memory`: reads long-term user profile and merges useful preferences.
- `need_clarification`: stops early when key information is missing.
- `planner`: records the steps the agent intends to execute.
- `task_router`: routes by `constraints.task_type`.
- `travel_tool_router`: calls weather, web search, place, route, and budget helpers for travel/local outing plans.
- `travel_candidate_scorer`: ranks candidate places against preferences, budget, weather, pace, and source quality.
- `travel_plan_generator`: builds route, budget, final itinerary, alternatives, and assistant-facing travel plan data.
- `errand_tool_router`: prepares lightweight place candidates for errand tasks without relying on weather or web search.
- `errand_candidate_scorer`: keeps errand candidates available for route ordering.
- `errand_plan_generator`: builds a route-aware errand timeline and `confirm_actions`.
- `meal_tool_router`: prepares food place candidates for meal planning without relying on weather or web search.
- `meal_candidate_scorer`: normalizes meal candidates.
- `meal_plan_generator`: builds meal candidates, timeline, budget, and `confirm_actions`.
- `todo_decomposer`: decomposes goals into todo items without map/weather calls.
- `todo_plan_generator`: builds todo items, time blocks, acceptance criteria, and `confirm_actions`.
- `risk_checker`: checks budget, weather, pace, and fallback risks.
- `reflection`: reviews whether the plan can be returned or should be replanned once.

## Shared State

The graph state wraps the existing `AgentState` object:

```python
{"state": AgentState(...)}
```

This keeps existing node functions unchanged. Important `AgentState` fields:

- `user_input`: original user request.
- `constraints`: extracted and normalized requirements.
- `user_profile`: learned preferences.
- `plan_steps`: planned execution steps.
- `tool_results`: weather/search/place/route/budget outputs.
- `candidates`: scored candidate places.
- `final_plan`: structured plan for frontend rendering.
- `risks` and `fallbacks`: risk checker outputs.
- `reflection`: plan review result.
- `replan_context` and `replan_count`: automatic replan control.
- `execution_log`: human-readable node summaries for UI/debugging.
- `trace_id`: stable id for traces and SSE events.

## Branch Rules

`need_clarification`:

- If `state.clarification_question` is set, the graph ends immediately.
- This prevents weather/search/place tools from running when user input is too vague.

`reflection`:

- If `state.reflection.next_action == "replan"` and `state.replan_count < 1`, the graph loops back to the start of the active task branch.
- The automatic replan round runs through that branch's tool/decompose, scoring when applicable, plan generation, risk checking, and reflection.
- Automatic replan is limited to one round to avoid infinite loops and long-running frontend requests.

## Progress And Trace

Each LangGraph node is wrapped by the same progress and trace behavior previously used by the hand-written loop:

- `services.trace_logger.traced(...)` records node input/output snapshots.
- `progress_callback` emits run/node/result events for `/runs/{trace_id}/events`.
- Replan events include `round: "auto_replan"` so the frontend can distinguish the second pass.

## Extension Notes

Future LifeOps scenarios should add task branches without breaking the public `run_lifeops(...)` response contract.

Recommended direction:

- Keep travel/local outing flow as the default branch.
- Add specialized tool/decomposer/scorer/generator branches for weekly/monthly planning.
- Calendar writes, reminders, messages, purchases, or destructive memory changes must route through an explicit human confirmation node.
