# LifeOps Roadmap

## Now

The project is strongest at travel and local outing planning:

- constraint extraction
- weather/search/place/route/budget tools
- scoring
- risk checking
- reflection and replan
- confirmation-gated calendar export
- React frontend with planning, history, profile, audit, and feedback

## Engineering First

Current priority:

- release checklist
- Docker and compose verification
- CI checks
- production environment documentation
- provider health and timeout hardening
- evaluation samples and Bad Case workflow

## Done: LangGraph MVP Flow

The backend now uses a LangGraph-backed flow while preserving `run_lifeops(...)` output compatibility.

Core nodes:

- extract constraints
- date resolver
- memory
- clarification check
- planner
- dynamic tool execution
- plan synthesis
- risk checker
- reflection
- final response

## Later: Full LifeOps Scope

Expand after engineering and LangGraph are stable:

1. Errand routing
2. Todo decomposition
3. Meal planning
4. Reminders
5. Multi-turn task status tracking
6. Weekly and monthly planning

Calendar writes, reminders, and external side effects must require user confirmation.
