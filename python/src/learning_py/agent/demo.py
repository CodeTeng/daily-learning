"""Agent 架构 demo：用真实 LLM（DeepSeek 或任何 OpenAI 协议兼容服务）跑 4 种架构。

前置：
    1. 安装依赖（已在 pyproject 中声明）：
        uv sync
    2. 在 `python/.env` 中配置（参考 `python/.env.example`）：
        LLM_BASE_URL=https://api.deepseek.com
        LLM_API_KEY=sk-xxx
        LLM_MODEL=deepseek-chat

运行：
    uv run python -m learning_py.agent.demo                 # 跑全部 4 种
    uv run python -m learning_py.agent.demo react           # 单跑 ReAct
    uv run python -m learning_py.agent.demo react plan      # 任意组合
    uv run python -m learning_py.agent.demo --debug react   # 出错时打印 traceback

特别说明：
- 真实模型调用涉及网络与计费，4 个 demo 全跑约 10-30 秒、消耗几千 token。
- 4 种架构的代码完全相同，差异只在 LLM 客户端的换装与调用编排上，
  这正是"Agent = 控制流壳 + 可替换 LLM"的设计落地。
"""

from __future__ import annotations

import sys

from .llm_client import OpenAICompatLLM
from .multi_agent import MultiAgentSystem
from .plan_and_execute import PlanAndExecuteAgent
from .react_agent import ReActAgent
from .reflection_agent import ReflectionAgent
from .tools import TraceEntry


def _section(title: str) -> None:
    line = "=" * 60
    print(f"\n{line}\n{title}\n{line}")


def _print_trace(trace: list[TraceEntry]) -> None:
    for i, entry in enumerate(trace, 1):
        tag = {"llm": "LLM ", "tool": "TOOL", "final": "DONE"}.get(entry.kind, entry.kind)
        body = str(entry.payload).replace("\n", "\n     ")
        print(f"  [{i:02d} {tag}] {body}")


# --------------------------------------------------------------------------- #
# 1. ReAct
# --------------------------------------------------------------------------- #
def demo_react() -> None:
    _section("1. ReAct（思考-行动-观察 紧耦合循环）")
    llm = OpenAICompatLLM(name="react", temperature=0.0)
    agent = ReActAgent(llm=llm, max_steps=6)
    final, trace = agent.run("请告诉我 Python 是什么语言；并算一下 (1+2+3)*4 等于多少。")
    _print_trace(trace)
    print(f"\n  最终：{final}")
    print(f"  LLM 调用次数：{llm.call_count}")


# --------------------------------------------------------------------------- #
# 2. Plan-and-Execute
# --------------------------------------------------------------------------- #
def demo_plan_and_execute() -> None:
    _section("2. Plan-and-Execute（先一次性出计划，再顺序执行）")
    llm = OpenAICompatLLM(name="planner", temperature=0.0)
    agent = PlanAndExecuteAgent(llm=llm)
    final, trace = agent.run("请告诉我 Python 是什么语言；并算一下 (1+2+3)*4。")
    _print_trace(trace)
    print(f"\n  最终：{final}")
    print(f"  LLM 调用次数：{llm.call_count}（理论上只有 Planner 这 1 次）")


# --------------------------------------------------------------------------- #
# 3. Reflection
# --------------------------------------------------------------------------- #
def demo_reflection() -> None:
    _section("3. Reflection（自己写、自己批、改到满意）")
    llm = OpenAICompatLLM(name="reflect", temperature=0.3)
    agent = ReflectionAgent(llm=llm, max_rounds=3)
    final, trace = agent.run(
        "用一句话给一个 5 岁小孩解释什么是『递归』，要求：必须用一个生活中的比喻，不超过 30 字。"
    )
    _print_trace(trace)
    print(f"\n  最终：{final}")
    print(f"  LLM 调用次数：{llm.call_count}（每轮 = 1 次草稿 + 1 次反思）")


# --------------------------------------------------------------------------- #
# 4. Multi-Agent
# --------------------------------------------------------------------------- #
def demo_multi_agent() -> None:
    _section("4. Multi-Agent（Researcher + Writer + Critic 协作）")
    multi = MultiAgentSystem(
        researcher=OpenAICompatLLM(
            name="researcher",
            system_prompt="你是一个简洁的资料员，只给关键事实，不展开。",
            temperature=0.0,
        ),
        writer=OpenAICompatLLM(
            name="writer",
            system_prompt="你是技术写作者，写作风格清晰、面向初学者。",
            temperature=0.5,
        ),
        critic=OpenAICompatLLM(
            name="critic",
            system_prompt=(
                "你是严格的评审员。合格则只回复 `CRITIC: APPROVE`；"
                "否则用 `CRITIC: ` 开头给一条最关键的修改意见。"
            ),
            temperature=0.0,
        ),
        max_rounds=3,
    )
    final, trace = multi.run("AI Agent 是什么")
    _print_trace(trace)
    print(f"\n  最终：{final}")
    total = multi.researcher.call_count + multi.writer.call_count + multi.critic.call_count
    print(
        f"  调用次数：researcher={multi.researcher.call_count} "
        f"writer={multi.writer.call_count} critic={multi.critic.call_count} "
        f"合计={total}"
    )


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #

DEMOS = {
    "react": demo_react,
    "plan": demo_plan_and_execute,
    "reflection": demo_reflection,
    "multi": demo_multi_agent,
}


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--debug"]
    debug = "--debug" in sys.argv

    if not args:
        targets = list(DEMOS.values())
    else:
        targets = []
        for name in args:
            if name not in DEMOS:
                print(f"未知 demo：{name}，可选：{list(DEMOS)}")
                sys.exit(2)
            targets.append(DEMOS[name])

    for fn in targets:
        try:
            fn()
        except Exception as e:  # noqa: BLE001  顶层 demo，把异常打出来即可
            print(f"\n[ERROR] {fn.__name__} 失败：{type(e).__name__}: {e}")
            if debug:
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    main()
