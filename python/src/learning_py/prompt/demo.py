"""把各类 Prompt 模板渲染出来，直观看看"好 Prompt 长什么样"。

运行：
    uv run python -m learning_py.prompt.demo
"""

from __future__ import annotations

from learning_py.prompt.templates import (  # pyright: ignore[reportImplicitRelativeImport]
    BasicPrompt,
    FewShotExample,
    FewShotPrompt,
    chain_of_thought_prompt,
    json_output_prompt,
    role_system_prompt,
)


def _section(title: str, body: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{title}\n{line}\n{body}")


def demo_basic() -> None:
    prompt = BasicPrompt(
        instruction="将下面的英文翻译成简体中文，保持专业术语不变。",
        context="你是一名资深技术翻译，面向中国大陆的后端工程师读者。",
        user_input=(
            "A context window is the maximum number of tokens a language model "
            "can process in a single request, including both the prompt and the response."
        ),
        output_format="只输出译文，不要输出原文、注释或前后缀。",
    )
    _section("1. 四要素基础 Prompt", prompt.render())


def demo_few_shot() -> None:
    prompt = FewShotPrompt(
        instruction="判断一条用户评论的情感倾向，输出 positive / neutral / negative 之一。",
        examples=[
            FewShotExample(input="物流超快，东西也很好用，五星好评！", output="positive"),
            FewShotExample(input="还行吧，跟描述差不多，没有惊喜也没有失望。", output="neutral"),
            FewShotExample(input="收到就是坏的，客服爱答不理，再也不买了。", output="negative"),
        ],
        user_input="包装破损，但产品本身没问题，商家补发了新的。",
    )
    _section("2. Few-shot Learning", prompt.render())


def demo_cot() -> None:
    question = (
        "小明有 5 支铅笔，他的姐姐数量是小明的 2 倍，"
        "哥哥比姐姐少 3 支，请问三人加起来一共多少支？"
    )
    _section("3. Chain-of-Thought（零样本）", chain_of_thought_prompt(question))


def demo_json_output() -> None:
    article = (
        "近日，某开源社区发布了新版 LLM 推理框架，相比上一版推理速度提升 40%，"
        "显存占用下降 25%。开发者表示，新版本在消费级显卡上也能跑起 70B 模型，"
        "社区反响热烈。"
    )
    _section("4. 结构化输出（JSON）", json_output_prompt(article))


def demo_role_system() -> None:
    system = role_system_prompt(
        role="资深 Python 后端导师，擅长用类比讲清楚底层原理",
        audience="刚工作 1~2 年的 Python 后端工程师",
    )
    _section("5. 角色扮演 + 防注入 System Prompt", system)


def main() -> None:
    demo_basic()
    demo_few_shot()
    demo_cot()
    demo_json_output()
    demo_role_system()


if __name__ == "__main__":
    main()
