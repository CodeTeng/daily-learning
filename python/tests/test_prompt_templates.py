"""Prompt 模板的冒烟测试。

只验证「能渲染 + 关键结构都在」，不依赖任何 LLM。
"""

from __future__ import annotations

from learning_py.prompt.templates import (
    BasicPrompt,
    FewShotExample,
    FewShotPrompt,
    chain_of_thought_prompt,
    json_output_prompt,
    role_system_prompt,
)


def test_basic_prompt_contains_all_sections() -> None:
    p = BasicPrompt(
        instruction="翻译",
        context="你是翻译",
        user_input="hello",
        output_format="只输出译文",
    ).render()

    assert "# 角色与背景" in p
    assert "# 任务" in p
    assert "<input>" in p and "</input>" in p
    assert "# 输出格式" in p


def test_basic_prompt_optional_sections() -> None:
    # 只有指令，也应该能渲染出来
    p = BasicPrompt(instruction="hello").render()
    assert "# 任务" in p
    assert "<input>" not in p


def test_few_shot_contains_examples_and_trailing_prompt() -> None:
    p = FewShotPrompt(
        instruction="情感分类",
        examples=[
            FewShotExample(input="好棒", output="positive"),
            FewShotExample(input="不行", output="negative"),
        ],
        user_input="还行吧",
    ).render()

    assert "## 示例 1" in p
    assert "## 示例 2" in p
    # 末尾必须留一个"输出："钩子，让模型顺着写
    assert p.rstrip().endswith("输出：")


def test_chain_of_thought_has_trigger_phrase() -> None:
    p = chain_of_thought_prompt("1+1=?")
    assert "一步步思考" in p
    assert "思考：" in p
    assert "答案：" in p


def test_json_output_prompt_has_schema_and_guard() -> None:
    p = json_output_prompt("some article")
    assert '"title"' in p
    assert '"sentiment"' in p
    # 边界情况必须明确
    assert "绝不编造" in p
    assert "<input>" in p


def test_role_system_prompt_has_injection_guard() -> None:
    p = role_system_prompt(role="导师", audience="新人")
    assert "安全规则" in p
    # 关键：用户输入不是指令
    assert "不是新的指令" in p
