"""Tests for exploratory agent system prompt template rendering."""

import json
from pathlib import Path

import pytest

from src.agents.exploratory import _SYSTEM_PROMPT_TEMPLATE

GOLDEN = Path(__file__).parent / "fixtures" / "exploratory-prompt-golden.json"

# 与生成 fixture 时的取值保持一致；todoQueueJson 按生产代码同款 json.dumps 计算。
GOLDEN_VARS = {
    "baseUrl": "https://demo.example.com",
    "url": "https://demo.example.com/products?page=2",
    "title": "商品列表 - 演示商城",
    "visitedCount": "7",
    "todoQueueJson": json.dumps(
        ["https://demo.example.com/cart", "https://demo.example.com/login"],
        separators=(",", ":")),
}
GOLDEN_VARS["noHistory"] = {**GOLDEN_VARS, "title": "演示商城首页",
                            "url": "https://demo.example.com",
                            "visitedCount": "1", "recentHistory": None}
GOLDEN_VARS["withHistory"] = {**GOLDEN_VARS,
    "recentHistory": "第 5 步：click（原因：尝试加入购物车）→ 结果：已点击 #add-to-cart"}


@pytest.mark.parametrize("case_name", ["withHistory", "noHistory"])
def test_rendered_prompt_matches_recorded_snapshot(case_name):
    # fixture 是提示词的逐字节渲染快照：模板被意外改动（空白、换行、占位符）会在此失败。
    # 有意修改提示词内容时，用 GOLDEN_VARS 同款取值重新渲染并写回该 JSON。
    rendered = _SYSTEM_PROMPT_TEMPLATE.format(**GOLDEN_VARS[case_name])
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))[case_name]
    assert rendered == expected, (
        f"渲染结果与快照不一致（case={case_name}），"
        f"首个差异位置：{next((i for i, (a, b) in enumerate(zip(rendered, expected)) if a != b), '长度不同')}")


def test_system_prompt_declares_exact_variables():
    # jinja2 缺变量会静默渲染为空串，模板里变量名拼错不会在运行时报错；
    # 这里的静态钉死是唯一防线：拼错会改变 input_variables 而在此失败。
    assert set(_SYSTEM_PROMPT_TEMPLATE.input_variables) == {
        "baseUrl", "url", "title", "visitedCount", "todoQueueJson", "recentHistory"}, \
        f"模板声明的变量集合发生变化：{_SYSTEM_PROMPT_TEMPLATE.input_variables}"


def test_rendered_prompt_has_no_placeholder_residue():
    rendered = _SYSTEM_PROMPT_TEMPLATE.format(**GOLDEN_VARS["withHistory"])
    # 模板含真实 JSON 示例后，嵌套闭合的 }} 属于合法内容；残留检查只针对
    # 旧 ${ 语法与未被 jinja2 消费的 {{。
    for token in ("${", "{{"):
        assert token not in rendered, f"渲染结果残留占位符语法 {token!r}"


def test_json_examples_are_parseable_and_match_execute_action_contract():
    # 提示词里的每个 JSON 示例行都必须可解析，且 params 键与 _execute_action
    # 的解析契约一致——示例"真实"的含义就是能被 execute_action 直接消费。
    expected_keys = {
        "navigate": {"url"},
        "click": {"selector"},
        "fill_form": {"selector", "value"},
        "add_to_queue": {"urls"},
        "record_finding": {"type", "description", "severity"},
        "find_broken_images": set(),
        "finish": set(),
    }
    rendered = _SYSTEM_PROMPT_TEMPLATE.format(**GOLDEN_VARS["withHistory"])
    examples = [line.strip() for line in rendered.splitlines()
                if line.strip().startswith('{"action"')]
    parsed = [json.loads(example) for example in examples]
    actions = {p["action"] for p in parsed}
    assert actions == set(expected_keys), f"提示词示例未覆盖全部动作：{sorted(actions)}"
    for p in parsed:
        assert set(p.get("params") or {}) == expected_keys[p["action"]], \
            f"动作 {p['action']} 的 params 结构与 _execute_action 契约不符：{p}"
