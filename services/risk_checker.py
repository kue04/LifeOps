from __future__ import annotations


def check_risks(final_plan: dict, constraints: dict, weather: dict) -> dict:
    risks: list[str] = []
    fallbacks: list[str] = []
    budget = constraints.get("budget")
    total = final_plan.get("budget", {}).get("total", 0)
    if budget is not None and total > budget:
        risks.append(f"预算预计 {total} 元，超过用户限制 {budget} 元")
    if weather.get("outdoor_risk") == "medium":
        outdoor_items = [
            item["place"]
            for item in final_plan.get("itinerary", [])
            if "室外" in item.get("tags", [])
        ]
        if outdoor_items:
            risks.append("天气有小雨，室外活动体验可能下降：" + "、".join(outdoor_items))
            fallbacks.append("下雨时优先保留室内展览和咖啡，将室外夜景改为湖滨商圈室内/连廊活动")
    if constraints.get("pace") == "轻松" and len(final_plan.get("itinerary", [])) > 4:
        risks.append("行程点位偏多，可能不够轻松")
    need_human_confirm = bool(final_plan.get("calendar_write"))
    return {
        "risks": risks,
        "fallbacks": fallbacks,
        "need_human_confirm": need_human_confirm,
    }
