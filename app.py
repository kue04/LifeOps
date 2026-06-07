from __future__ import annotations

import json

import streamlit as st

from agent.graph import run_lifeops


def _basis_text(basis: dict) -> str:
    answer = basis.get("answer") or "已综合候选评分和外部来源排序。"
    selected = "、".join(str(item) for item in (basis.get("selected_places") or [])[:4])
    query = basis.get("web_query") or "未记录"
    return f"{answer} 搜索词：{query}。主线地点：{selected or '待生成'}。"


def _render_lifestyle_places(lifestyle: dict) -> None:
    foods = lifestyle.get("foods") or []
    hotels = lifestyle.get("hotels") or []
    col_food, col_hotel = st.columns(2)
    with col_food:
        st.write("餐饮候选")
        _render_place_table(foods, "当前没有餐饮候选。")
    with col_hotel:
        st.write("住宿候选")
        _render_place_table(hotels, "当前没有住宿候选。")


def _render_place_table(items: list[dict], empty_text: str) -> None:
    if not items:
        st.info(empty_text)
        return
    st.dataframe(
        [
            {
                "name": item.get("name"),
                "area": item.get("area"),
                "address": item.get("address"),
                "cost_note": item.get("cost_note"),
                "map_url": item.get("map_url"),
            }
            for item in items
        ],
        use_container_width=True,
    )


st.set_page_config(page_title="LifeOps Agent", layout="wide")
st.title("LifeOps Agent 调试台")

default_input = "这周六我想在杭州轻松玩一天，预算 500，喜欢咖啡、展览和夜景，不想太累。"
user_input = st.text_area("用户输入", value=default_input, height=120)

col_run, col_replan = st.columns([1, 1])
with col_run:
    if st.button("运行 Agent", type="primary"):
        st.session_state["result"] = run_lifeops(user_input)

with col_replan:
    followup_input = st.text_input("追问/修改", value="太贵了，控制在 300。")
    if st.button("基于上一轮重规划"):
        previous = st.session_state.get("result")
        st.session_state["result"] = run_lifeops(followup_input, previous_result=previous)

result = st.session_state.get("result")
if result:
    st.subheader("结果")
    st.caption(f"status: {result['status']} · trace_id: {result['trace_id']}")

    if result["status"] == "need_clarification":
        st.warning(result["question"])
        st.json(result["constraints"])
    else:
        st.markdown(result.get("assistant_message", ""))
        final_plan = result.get("final_plan", {})
        basis = final_plan.get("recommendation_basis") or {}
        lifestyle = final_plan.get("lifestyle_places") or {}
        if basis:
            st.info(_basis_text(basis))
        metric_cols = st.columns(4)
        metric_cols[0].metric("网页结果", basis.get("web_results_count", 0))
        metric_cols[1].metric("参考来源", basis.get("web_sources_count", 0))
        metric_cols[2].metric("餐饮候选", len(lifestyle.get("foods") or []))
        metric_cols[3].metric("住宿候选", len(lifestyle.get("hotels") or []))

    st.subheader("执行链路")
    for index, item in enumerate(result.get("execution_log", []), start=1):
        with st.expander(f"{index}. {item['node']} · {item['summary']}", expanded=index <= 3):
            st.json(item.get("details", {}))

    tab_plan, tab_candidates, tab_search, tab_trace = st.tabs(["计划与约束", "候选评分", "网页搜索", "Trace"])

    with tab_plan:
        col1, col2 = st.columns(2)
        with col1:
            st.write("约束")
            st.json(result.get("constraints", {}))
            st.write("LLM 调用")
            st.json(result.get("llm_usage", []))
        with col2:
            st.write("最终计划")
            st.json(result.get("final_plan", {}))
            st.write("反思")
            st.json(result.get("reflection", {}))
        st.write("推荐依据")
        st.json(result.get("final_plan", {}).get("recommendation_basis", {}))
        _render_lifestyle_places(result.get("final_plan", {}).get("lifestyle_places", {}))

    with tab_candidates:
        candidates = result.get("candidates", [])
        if candidates:
            st.dataframe(
                [
                    {
                        "name": item["name"],
                        "score": item["score"],
                        "cost": item["estimated_cost"],
                        "tags": "、".join(item["tags"]),
                        "reasons": "；".join(item.get("score_reasons", [])),
                    }
                    for item in candidates
                ],
                use_container_width=True,
            )
        else:
            st.info("当前轮次还没有进入候选评分。")

    with tab_search:
        search_tool = next((item for item in result.get("tool_results", []) if item.get("tool_name") == "web_search_tool"), None)
        if search_tool:
            st.write("网页搜索结果")
            search_data = search_tool.get("data", {})
            sources = (result.get("final_plan", {}).get("travel_research", {}) or {}).get("sources", [])
            if sources:
                st.dataframe(
                    [
                        {
                            "title": item.get("title"),
                            "url": item.get("url"),
                            "content": item.get("content"),
                        }
                        for item in sources
                    ],
                    use_container_width=True,
                )
            st.json(search_tool.get("data", {}))
        else:
            st.info("当前轮次没有网页搜索结果。")
        st.write("旅行研究摘要")
        st.json(result.get("final_plan", {}).get("travel_research", {}))

    with tab_trace:
        st.code(json.dumps(result.get("trace", []), ensure_ascii=False, indent=2), language="json")
