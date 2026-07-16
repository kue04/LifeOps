from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 离线评估必须可重复，不依赖本机密钥或外部服务状态。
os.environ["LIFEOPS_AGENT_MODE"] = "multi_agent"
os.environ["LIFEOPS_LLM_MODE"] = "mock"
os.environ["WEATHER_PROVIDER"] = "mock"
os.environ["PLACE_PROVIDER"] = "mock"
os.environ["SEARCH_PROVIDER"] = "mock"

from agent.graph import run_lifeops


DEFAULT_CASES = ROOT / "tests" / "eval_cases.json"


def _contains_all(actual: list[Any], expected: list[Any]) -> bool:
    return all(item in actual for item in expected)


def _validate(result: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    constraints = result.get("constraints") or {}
    planner_meta = result.get("planner_meta") or {}
    critic = result.get("critic") or {}
    agent_runs = result.get("agent_runs") or []
    actual_agents = sorted({str(item.get("agent")) for item in agent_runs if item.get("agent")})

    scalar_checks = {
        "status": result.get("status"),
        "task_type": constraints.get("task_type"),
        "planner_source": planner_meta.get("source"),
        "planner_fallback_reason": planner_meta.get("fallback_reason"),
        "critic_passed": critic.get("passed"),
    }
    for key, actual in scalar_checks.items():
        if key in expected and actual != expected[key]:
            errors.append(f"{key}: expected={expected[key]!r}, actual={actual!r}")

    if "agents" in expected and actual_agents != sorted(expected["agents"]):
        errors.append(f"agents: expected={sorted(expected['agents'])!r}, actual={actual_agents!r}")

    preferences = list(constraints.get("preferences") or [])
    avoid = list(constraints.get("avoid") or [])
    if not _contains_all(preferences, expected.get("preferences_contains", [])):
        errors.append(f"preferences missing: {expected['preferences_contains']!r}; actual={preferences!r}")
    excluded_preferences = expected.get("preferences_excludes", [])
    if any(item in preferences for item in excluded_preferences):
        errors.append(f"preferences should exclude: {excluded_preferences!r}; actual={preferences!r}")
    if not _contains_all(avoid, expected.get("avoid_contains", [])):
        errors.append(f"avoid missing: {expected['avoid_contains']!r}; actual={avoid!r}")

    if "budget_max" in expected:
        total = (result.get("final_plan") or {}).get("budget", {}).get("total")
        if not isinstance(total, (int, float)) or total > expected["budget_max"]:
            errors.append(f"budget total must be <= {expected['budget_max']}; actual={total!r}")

    question = str(result.get("question") or "")
    missing_question_parts = [item for item in expected.get("question_contains", []) if item not in question]
    if missing_question_parts:
        errors.append(f"question missing: {missing_question_parts!r}; actual={question!r}")

    warnings = [str(warning) for run in agent_runs for warning in run.get("warnings") or []]
    for fragment in expected.get("warnings_contain", []):
        if not any(fragment in warning for warning in warnings):
            errors.append(f"warnings missing fragment={fragment!r}; actual={warnings!r}")
    return errors


def evaluate(cases_path: Path) -> int:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    failures = 0
    category_totals: dict[str, list[int]] = {}

    for case in cases:
        previous_result = None
        for turn in case["turns"]:
            previous_result = run_lifeops(
                turn,
                previous_result=previous_result,
                user_id=f"eval_{case['id']}",
            )
        errors = _validate(previous_result or {}, case["expected"])
        category = case["category"]
        category_totals.setdefault(category, [0, 0])[0] += 1
        if errors:
            failures += 1
            print(f"[FAIL] {case['id']} ({category})")
            for error in errors:
                print(f"  - {error}")
        else:
            category_totals[category][1] += 1
            print(f"[PASS] {case['id']} ({category})")

    print("\nCategory summary")
    for category, (total, passed) in sorted(category_totals.items()):
        print(f"- {category}: {passed}/{total}")
    print(f"Total: {len(cases) - failures}/{len(cases)}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic offline LifeOps Agent evaluations.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = parser.parse_args()
    return evaluate(args.cases.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
