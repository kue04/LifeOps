# LifeOps Roadmap

## Now

The project is strongest at travel and local outing planning:

- constraint extraction
- weather/search/place/route/budget tools
- scoring
- risk checking
- reflection and replan
- React frontend with run streaming, history, profile, and feedback

## Engineering First

Current priority:

- local startup scripts
- Docker and compose
- CI
- environment documentation
- stable SQLite path configuration
- API documentation

## Next: LangGraph Native Flow

Move from the hand-written node sequence in `agent/graph.py` to a real `StateGraph` while preserving `run_lifeops(...)` output compatibility.

Required nodes:

- extract constraints
- date resolver
- memory
- clarification check
- planner
- tool router
- candidate scorer
- plan generator
- risk checker
- reflection
- final response

The replan path should loop through tool routing, scoring, plan generation, risk checking, and reflection at most once by default.

## Later: Full LifeOps Scope

Expand after engineering and LangGraph are stable:

1. Errand routing
2. Todo decomposition
3. Meal planning
4. Calendar export and reminders
5. Multi-turn task status tracking
6. Weekly and monthly planning

Calendar writes, reminders, and external side effects must require user confirmation.
