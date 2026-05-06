# LangChain 学习总览

> 对应代码：[`src/learning_py/langchain_framework/`](../src/learning_py/langchain_framework/)
>
> 统一运行入口：[`demo.py`](../src/learning_py/langchain_framework/demo.py)
>
> 这个文档把 LangChain 的核心学习点，按“原理 + 代码 + 运行方式”串成一份可直接使用的总结。

---

## 1. 学习目标

这套示例的目标不是把 LangChain 的所有 API 都铺开，而是先把最常用、最关键的能力跑通：

- Agents 模块：理解 Agent 不是单次问答，而是“模型 + 工具 + 循环”的执行系统
- Models：理解 `ChatOpenAI` 如何接入真实模型
- Messages：理解不同消息角色如何共同组成上下文
- Tools：理解工具定义、工具调用、结果回填
- Short-term memory：理解短期记忆如何保留对话上下文
- Streaming：理解流式输出如何提升交互体验
- Structured output：理解如何让模型输出直接变成可校验的数据结构
- Prompt caching：理解隐式缓存和显式缓存如何降低延迟与成本

如果把这几个点串起来，整体链路就是：

```text
用户输入
	→ Messages
	→ Models
	→ Tools / Agent 循环
	→ Short-term memory
	→ Streaming
	→ Structured output
```

---

## 2. 运行方式

这个目录默认使用 `uv`，不使用 `pip`。

### 2.1 安装依赖

```bash
cd python
uv add langchain langchain-community langchain-openai langgraph python-dotenv
```

### 2.2 配置环境变量

`.env.example` 只是模板，真实运行时请复制为 `.env`，然后填入下面三项：

```env
LLM_MODEL=glm-5
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

当前代码统一读取：

- `LLM_MODEL`：模型名
- `LLM_API_KEY`：API Key
- `LLM_BASE_URL`：OpenAI 兼容接口地址

### 2.3 一键运行

```bash
uv run python -m learning_py.langchain_framework.demo check
uv run python -m learning_py.langchain_framework.demo models
uv run python -m learning_py.langchain_framework.demo agents
uv run python -m learning_py.langchain_framework.demo memory
uv run python -m learning_py.langchain_framework.demo streaming
uv run python -m learning_py.langchain_framework.demo structured
uv run python -m learning_py.langchain_framework.demo caching
uv run python -m learning_py.langchain_framework.demo all
```

如果你想单独跑某个模块，也可以直接执行对应文件：

```bash
uv run python src/learning_py/langchain_framework/models_and_messages.py
uv run python src/learning_py/langchain_framework/tools_and_agents.py
uv run python src/learning_py/langchain_framework/short_term_memory.py
uv run python src/learning_py/langchain_framework/streaming_demo.py
uv run python src/learning_py/langchain_framework/structured_output.py
```

---

## 3. 代码地图

| 主题              | 代码文件                                                                                | 关注点                                    |
| ----------------- | --------------------------------------------------------------------------------------- | ----------------------------------------- |
| 统一环境配置      | [config.py](../src/learning_py/langchain_framework/config.py)                           | 读取 `.env`，创建统一的 `ChatOpenAI`      |
| 一键入口          | [demo.py](../src/learning_py/langchain_framework/demo.py)                               | 按模块运行各段示例                        |
| Models / Messages | [models_and_messages.py](../src/learning_py/langchain_framework/models_and_messages.py) | 模型调用、消息历史、消息角色              |
| Tools / Agents    | [tools_and_agents.py](../src/learning_py/langchain_framework/tools_and_agents.py)       | `@tool`、`bind_tools()`、Agent 循环       |
| Short-term memory | [short_term_memory.py](../src/learning_py/langchain_framework/short_term_memory.py)     | 窗口记忆、上下文保留                      |
| Streaming         | [streaming_demo.py](../src/learning_py/langchain_framework/streaming_demo.py)           | `stream()` 增量输出                       |
| Structured output | [structured_output.py](../src/learning_py/langchain_framework/structured_output.py)     | `with_structured_output()`、Pydantic 校验 |
| Prompt caching    | [prompt_caching.py](../src/learning_py/langchain_framework/prompt_caching.py)           | 隐式/显式缓存、延迟与成本优化             |

---

## 4. 原理说明

### 4.1 Models

模型层的核心是 `ChatOpenAI`。

在这套示例里，模型初始化不是写死在代码里，而是统一通过 `config.py` 从环境变量读取：

- `model=LLM_MODEL`
- `api_key=LLM_API_KEY`
- `base_url=LLM_BASE_URL`

这意味着它既能接 OpenAI，也能接 OpenAI 兼容接口，比如你现在用的 DashScope compatible endpoint。

代码对应：[`config.py`](../src/learning_py/langchain_framework/config.py)

### 4.2 Messages

消息是模型上下文的基本单位。这里主要用到四种：

- `SystemMessage`：系统规则
- `HumanMessage`：用户输入
- `AIMessage`：模型输出
- `ToolMessage`：工具结果

理解 Messages 的关键是：**模型不是在看单条字符串，而是在看一串角色化消息。**

代码对应：[`models_and_messages.py`](../src/learning_py/langchain_framework/models_and_messages.py)

### 4.3 Tools

工具调用的本质是把 Python 函数暴露成模型可理解的 schema。

这里的核心流程是：

1. 用 `@tool` 标记一个函数
2. 让模型通过 `bind_tools()` 看到这个工具
3. 模型输出 `tool_calls`
4. 你执行工具
5. 用 `ToolMessage` 把结果回填给模型

这套链路是 Agent 能“做事”的前提。

代码对应：[`tools_and_agents.py`](../src/learning_py/langchain_framework/tools_and_agents.py)

### 4.4 Agents

当前代码里的 Agent 不是复杂的 LangGraph 状态图，而是一个最小可运行循环：

```text
用户输入 → 模型判断是否要调工具 → 执行工具 → 回填结果 → 再让模型继续推理
```

这就是理解 Agent 的最小骨架。

在当前示例里，Agent 模块重点演示的是：

- 工具绑定
- Tool calling 循环
- 最大迭代次数控制

代码对应：[`tools_and_agents.py`](../src/learning_py/langchain_framework/tools_and_agents.py)

### 4.5 Short-term memory

短期记忆本质上就是“把历史对话保留下来”。

当前示例用 `deque(maxlen=...)` 模拟固定窗口记忆：

- 新消息进来时追加
- 达到上限后自动丢掉最早的消息
- 每次调用模型时把窗口中的消息一起传入

这个方式简单、直观，也最适合学习“上下文为什么会变长、为什么会忘记最早内容”。

代码对应：[`short_term_memory.py`](../src/learning_py/langchain_framework/short_term_memory.py)

### 4.6 Streaming

流式输出的重点不是“能不能分块”，而是“能不能立刻把模型的 chunk 展现给用户”。

当前示例直接使用：

```python
for chunk in model.stream(messages):
		print(chunk.content, end="", flush=True)
```

这对应真实项目里常见的聊天 UI、SSE 推送、边生成边展示。

代码对应：[`streaming_demo.py`](../src/learning_py/langchain_framework/streaming_demo.py)

### 4.7 Structured output

结构化输出的目标是：让模型结果不只是“可读文本”，而是能直接给程序消费的数据。

当前示例使用 `with_structured_output(Person)`，把模型输出约束成 Pydantic 模型：

- 输出字段明确
- 下游校验简单
- 出错时更容易定位是哪一个字段不对

代码对应：[`structured_output.py`](../src/learning_py/langchain_framework/structured_output.py)

### 4.8 Prompt Caching

Prompt Caching 解决的核心问题是：**每次请求都在传同样的内容，为什么不能跳过重复计算？**

分两种模式：

**隐式缓存**（Implicit Caching）：

- 提供商自动检测重复 token，命中后自动降价。
- 客户端不需要写任何标记，OpenAI / Gemini 默认支持。
- 在 `response.usage_metadata` 里查看 `cached_tokens` 字段确认是否命中。
- 代码里只需要保证稳定的 system prompt 前缀即可受益。

**显式缓存**（Explicit Caching）：

- 你手动在代码里标记缓存点，控制更精准。
- 代表：Anthropic Claude 的 `cache_control: {"type": "ephemeral"}`。
- 只有超过最低 token 阈值（Anthropic 1024 token）才会生效。
- 适合把长文档、知识库上下文等稳定内容放在缓存标记之前。

最佳实践：

- 把稳定不变的内容（角色定义、上下文文档）放在消息列表前面
- 把每次变化的内容（具体问题）放在后面
- 监控 `usage_metadata` 确认缓存是否生效

代码对应：[`prompt_caching.py`](../src/learning_py/langchain_framework/prompt_caching.py)

---

## 5. 代码总结

### 5.1 `config.py`

这是这套示例里最关键的“运行契约”文件。

它做了两件事：

- `load_chat_config()`：读取 `.env` 里的 `LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL`
- `create_chat_model()`：用统一参数创建 `ChatOpenAI`

这样做的好处是，所有示例都遵循同一套配置，不会再出现“这个文件读 key，那份文件还在写死模型名”的不一致问题。

### 5.2 `demo.py`

这是统一入口。

它的作用是把下面这些模块串起来：

- `models`
- `agents`
- `memory`
- `streaming`
- `structured`

这样你可以：

- `check`：只检查环境变量是否能读到
- `models`：跑模型与消息相关示例
- `agents`：跑工具调用和 Agent 循环
- `memory`：跑短期记忆
- `streaming`：跑流式输出
- `structured`：跑结构化输出
- `all`：一键跑完整体流程

### 5.3 `models_and_messages.py`

这个文件是入门起点。

它主要演示了：

- 基础问答
- 不同消息类型
- 对话历史
- 工具消息示意
- temperature 参数
- 批量调用
- 多轮循环对话

如果你只想先理解“LLM 是怎么接入的”，优先看这个文件。

### 5.4 `tools_and_agents.py`

这个文件负责工具和 Agent 的最小闭环。

它演示了：

- `@tool` 怎么把函数暴露给模型
- `bind_tools()` 怎么让模型知道有哪些工具
- 模型输出工具调用后，如何执行工具
- 如何把工具结果写回消息列表

如果你想理解“模型为什么能真的做事”，优先看这里。

### 5.5 `short_term_memory.py`

这个文件用固定窗口模拟短期记忆。

它让你直观看到：

- 上下文不是无限长的
- 记忆需要裁剪
- 最近的消息最重要

### 5.6 `streaming_demo.py`

这个文件只做一件事：展示 `stream()`。

学习时重点看两点：

- `chunk` 是怎么被逐块拿到的
- 为什么 `flush=True` 对交互体验很重要

### 5.7 `structured_output.py`

这个文件展示怎么把模型输出变成结构化数据。

重点是：

- 先定义 Pydantic 模型
- 再让模型按这个结构输出
- 最后直接消费 `model_dump()` 结果

### 5.8 `prompt_caching.py`

这个文件解释 Prompt Caching 的两种模式。

核心函数：

- `demo_summary()` —— 概念总览
- `demo_implicit_caching()` —— 用同一个长 system prompt 调用两次，观察 `usage_metadata`
- `demo_explicit_caching()` —— Anthropic 风格的 `cache_control` 写法（参考用）
- `demo_check_cache_metadata()` —— 从 response 里读取缓存相关字段

重点理解：

- 隐式缓存和显式缓存的区别
- 为什么把稳定内容放在消息前面有助于缓存命中
- 怎么从 `usage_metadata` 确认缓存是否生效

---

## 6. 推荐学习顺序

建议按这个顺序看：

1. [`models_and_messages.py`](../src/learning_py/langchain_framework/models_and_messages.py)
2. [`tools_and_agents.py`](../src/learning_py/langchain_framework/tools_and_agents.py)
3. [`short_term_memory.py`](../src/learning_py/langchain_framework/short_term_memory.py)
4. [`streaming_demo.py`](../src/learning_py/langchain_framework/streaming_demo.py)
5. [`structured_output.py`](../src/learning_py/langchain_framework/structured_output.py)
6. [`prompt_caching.py`](../src/learning_py/langchain_framework/prompt_caching.py)
7. [`demo.py`](../src/learning_py/langchain_framework/demo.py)

这个顺序的好处是先理解"模型怎么接入"，再理解"模型怎么做事"，最后看"如何把结果变得更稳、更快、更结构化"。

---

## 7. 常见坑

### 7.1 只配了 key，没配 base_url

如果你接的是 OpenAI 兼容服务，只配 `LLM_API_KEY` 不够，必须同时提供 `LLM_BASE_URL`。

### 7.2 `.env.example` 不会自动生效

真实运行必须有 `.env` 文件。

### 7.3 不要把运行契约写死在代码里

当前示例已经统一改成：

- `LLM_MODEL`
- `LLM_API_KEY`
- `LLM_BASE_URL`

这比在多个文件里分别写死 `gpt-4o-mini` 或默认 OpenAI endpoint 更适合学习和切换环境。

### 7.4 `all` 会跑很多真实请求

`demo.py all` 是“一键总览”，不是“零成本检查”。如果只是想确认 `.env` 没问题，先用 `check`。

### 7.5 某些兼容接口会要求提示词里出现 `json`

在结构化输出场景下，部分 OpenAI 兼容接口会要求上下文里显式出现 `json`，否则会拒绝 `response_format`。

如果遇到这类报错，优先在系统提示词里写一句：

```text
Return the result as valid JSON.
```

当前 [`structured_output.py`](../src/learning_py/langchain_framework/structured_output.py) 在结构化解析失败时会自动回退到原始 JSON 文本解析。

---

## 8. 代码速查

以下片段可以即取即用。

### 8.1 模型调用

```python
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

model = ChatOpenAI(model="glm-5", api_key="sk-...", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
resp = model.invoke([HumanMessage(content="你好")])
print(resp.content)
```

### 8.2 工具定义

```python
from langchain_core.tools import tool

@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

### 8.3 Streaming

```python
for chunk in model.stream([HumanMessage(content="解释一下 Python")]):
    print(chunk.content, end="", flush=True)
```

### 8.4 结构化输出

```python
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int

structured = model.with_structured_output(Person)
result = structured.invoke([HumanMessage(content="张三，18岁")])
```

---

## 9. 最佳实践

| 实践                           | 说明                                                                                    |
| ------------------------------ | --------------------------------------------------------------------------------------- |
| 统一封装模型创建函数           | 所有示例共用 `config.create_chat_model()`，避免模型名/密钥散落各处                      |
| 密钥缺失时给出明确报错         | `config.load_chat_config()` 会清晰指出缺了 `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` |
| Agent 循环设置最大迭代次数     | 当前设为 6 次兜底，防止模型陷入死循环                                                   |
| Structured Output 配合兜底解析 | 兼容接口可能返回 fenced JSON，代码内做了回退清洗                                        |

当前 [`structured_output.py`](../src/learning_py/langchain_framework/structured_output.py) 已经按这个方式处理，并在结构化解析失败时自动回退到原始 JSON 文本解析。

---

## 8. 一句话总结

LangChain 的核心不是“会不会调用模型”，而是：

**把消息、工具、记忆、流式、结构化输出这些能力，拆成一套可组合、可验证、可直接运行的工程模块。**

这份目录真正值得记住的，不是某个单独 API，而是这些模块如何一起协作。
