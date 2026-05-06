"""
LangChain Prompt Caching - 演示

什么是 Prompt Caching（提示缓存）？
====================================

每次调用 LLM 都要把完整的输入（system prompt + 历史对话 + 用户消息）通过网络
传给模型。如果多个请求包含大量重复内容（尤其是长 system prompt 或长文档），
每次重传不仅慢，而且浪费钱。

Prompt Caching 的核心思路是：

  让模型提供商记住你最近发过的某段内容，下次再发同样的内容时直接复用，
  不再重复计算，从而降低延迟（Latency）和成本（Cost）。

两种缓存模式
============

1. 隐式缓存（Implicit Caching）
   - 提供商自动检测重复 token，命中缓存后自动降价。
   - 你不需要在代码里做任何标记。
   - 代表：OpenAI、Google Gemini。
   - 查看 response.usage 里的 cache 相关字段确认是否命中。

2. 显式缓存（Explicit Caching）
   - 你在代码里手动指定 "从这里开始的内容请缓存"。
   - 控制权在你手里，可以确保长内容一定被缓存。
   - 代表：Anthropic（Claude）的 cache_control 标记、
          某些 ChatOpenAI 实现。
   - 只有超过最低 token 阈值才会生效（Anthropic 是 1024 token）。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from learning_py.langchain_framework.config import create_chat_model, load_chat_config


def _title(text: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n{text}\n{line}")


# ---------------------------------------------------------------------------
# 场景 1：隐式缓存 —— 不写任何缓存标记，观察 usage_metadata
# ---------------------------------------------------------------------------

def demo_implicit_caching() -> None:
    """
    隐式缓存演示。

    OpenAI / Gemini 等服务会在服务端自动判断哪些 token 可以缓存。
    你不需要写任何代码——只需要在两次请求间保持相同的前缀内容，
    第二次请求就可能命中缓存。

    命中缓存后，response.usage_metadata 里会出现：
      - input_token_details: {"cached_tokens": 1234}
      - 计费会按更低的缓存价目表走（对用户透明）。
    """

    model = create_chat_model()

    # 构造一个长的 system prompt（接近缓存阈值）
    doc_text = "\n".join(
        f"Rule {i}: Some important instruction number {i}." for i in range(200)
    )
    long_system = SystemMessage(
        content=f"You are a document analysis assistant.\n\n{doc_text}"
    )

    # 第一次调用 —— 不命中缓存（cold start）
    print("第一次调用（cold start）:")
    resp1 = model.invoke(
        [long_system, HumanMessage(content="Summarize the rules in one line.")]
    )
    usage1 = resp1.usage_metadata
    print(f"  output_tokens: {usage1.get('output_tokens', 'N/A')}")
    print(f"  input_tokens: {usage1.get('input_tokens', 'N/A')}")
    # OpenAI / DashScope 兼容接口可能不暴露 cache 细节，但计费侧已自动处理。
    if "input_token_details" in usage1:
        print(f"  input_token_details: {usage1['input_token_details']}")
    print()

    # 第二次调用 —— 相同的前缀内容，可能命中缓存
    print("第二次调用（相同前缀，期望命中缓存）:")
    resp2 = model.invoke(
        [long_system, HumanMessage(content="Give me a different summary.")]
    )
    usage2 = resp2.usage_metadata
    print(f"  output_tokens: {usage2.get('output_tokens', 'N/A')}")
    print(f"  input_tokens: {usage2.get('input_tokens', 'N/A')}")
    if "input_token_details" in usage2:
        print(f"  input_token_details: {usage2['input_token_details']}")
    print()


# ---------------------------------------------------------------------------
# 场景 2：显式缓存（Anthropic 风格）—— 手动标记缓存点
# ---------------------------------------------------------------------------

def demo_explicit_caching() -> None:
    """
    显式缓存演示（以 Anthropic Claude 为例）。

    Anthropic 允许你在 SystemMessage 的 content 列表里，用
    {"cache_control": {"type": "ephemeral"}} 标记某个 block 需要缓存。

    原理：
      - SystemMessage 可以包含多个 content blocks（文本块）。
      - 在某个 block 上标记 cache_control，表示 "从这个 block 开始往前的
        所有内容都要被我标记为缓存"。
      - 只有总 token 数超过阈值（Anthropic 是 1024 token）才会真正缓存。
      - 标记位置越靠前，缓存的数据越多，但也越容易被后续内容重置。

    注意：你的 DashScope 兼容接口可能不支持 Anthropic 的 cache_control，
    以下代码仅为展示 "显式缓存" 的设计思路。实际要在 Anthropic 上跑才有效。
    """

    print("[说明] 以下代码展示 Anthropic 风格的显式缓存写法。")
    print("       当前你的模型是 DashScope 兼容接口，不支持 cache_control。")
    print("       这部分仅供学习参考。\n")

    long_document = "\n".join(
        f"Chapter {i}: Some very long analysis content that will be reused "
        f"across multiple queries." for i in range(100)
    )

    # SystemMessage 的 content 可以传一个 block 列表
    system_with_cache = SystemMessage(
        content=[
            {
                "type": "text",
                "text": "You are a helpful assistant with deep knowledge of documents.",
            },
            {
                "type": "text",
                "text": long_document,
                # Anthropic 会在 cache_control 标记处缓存此前所有内容
                "cache_control": {"type": "ephemeral"},
            },
        ]
    )

    print("SystemMessage 结构:")
    print(f"  block 1: 系统角色指令（不会被缓存）")
    print(f"  block 2: 超长文档（标记了 cache_control，从此 block 开始缓存）")
    print()
    print(f"  block 2 的字符数: {len(long_document)}")
    print(f"  （Anthropic 要求至少 1024 token 才能触发缓存）")

    # 实际运行时，需要 langchain_anthropic.ChatAnthropic
    print(
        "\n用户: 'Summarize the document.'\n"
        "AI:   首次调用——写缓存，下次复用相同 system prompt 时命中。"
    )


# ---------------------------------------------------------------------------
# 场景 3：查看缓存生效情况（通过 response 元数据）
# ---------------------------------------------------------------------------

def demo_check_cache_metadata() -> None:
    """
    如何检查请求是否命中了缓存。

    不同提供商的字段名不同：

    | 提供商     | 字段路径                                    |
    |------------|---------------------------------------------|
    | OpenAI     | response.usage.prompt_tokens_details.cached_tokens |
    | Anthropic  | response.usage.cache_read_input_tokens       |
    | Gemini     | response.usage.cached_content_token_count    |

    如果你用的接口兼容 OpenAI 协议，可以试：
      response.usage_metadata.get("input_token_details")
    """
    model = create_chat_model()
    msg = [HumanMessage(content="Hello, say hi back.")]
    resp = model.invoke(msg)
    meta = resp.usage_metadata

    print("usage_metadata 原始内容:")
    for k, v in meta.items():
        print(f"  {k}: {v}")

    # 尝试读缓存相关字段（供应商如果不暴露就是空）
    details = meta.get("input_token_details") or {}
    cached = details.get("cached_tokens", "N/A（该供应商未透传此字段）")
    print(f"\n缓存的 token 数: {cached}")


# ---------------------------------------------------------------------------
# 总结
# ---------------------------------------------------------------------------

def demo_summary() -> None:
    _title("Prompt Caching 总结")

    print("""
┌─────────────────────────────────────────────────────────────┐
│                    Prompt Caching                           │
├─────────────────────────────────────────────────────────────┤
│                                                            │
│  目的：降低延迟 + 降低成本                                  │
│                                                            │
│  两种模式：                                                 │
│                                                            │
│  1. 隐式缓存（Implicit）                                    │
│     提供商：OpenAI / Gemini                                │
│     做法：自动检测重复 token，客户端无需额外代码             │
│     确认：看 response.usage_metadata 里的 cache 字段        │
│                                                            │
│  2. 显式缓存（Explicit）                                    │
│     提供商：Anthropic / AWS Bedrock                        │
│     做法：在代码里标记 cache_control                        │
│     控制：你可以精确指定哪段内容需要缓存                     │
│                                                            │
│  最佳实践：                                                 │
│  - 把稳定不变的内容（role prompt、上下文文档）放在前面       │
│  - 把每次变化的内容（具体问题）放在后面                     │
│  - 监控 usage_metadata，确认缓存是否生效                    │
│                                                            │
└─────────────────────────────────────────────────────────────┘""")


if __name__ == "__main__":
    demo_summary()
    print()
    demo_check_cache_metadata()
    print()
    demo_implicit_caching()
