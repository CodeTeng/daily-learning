# Tool Calling（工具调用）【必学】

> 对应代码：[`src/learning_py/tool_calling/`](../src/learning_py/tool_calling/)
>
> 运行演示：
> ```bash
> uv run python -m learning_py.tool_calling.demo
> ```
>
> 上游笔记：[`ai-agent.md`](./ai-agent.md) —— 工具调用是 Agent "执行" 能力的技术地基。

---

## 0. 为什么 Tool Calling 是 Agent 的必经之路

LLM 本身**只能产出文本**，既摸不到数据库也点不了网页。要让它真的做点什么，必须把能力以"工具"的形式暴露出去，让它决定**调哪个、怎么调**。

一句话：**Tool Calling = 把"写代码调 API"的决策权交给 LLM，但控制权还在你手里。**

Tool Calling 要跑通，必然包含四个环节（图中的四个要点）：

```
① Function Calling 协议        LLM 如何告诉你"我想调工具"
② 工具定义和描述             你如何告诉 LLM "我有哪些工具"
③ 工具参数解析               LLM 吐出 JSON，你怎么安全变成 Python 值
④ 工具执行和结果返回         你怎么执行、出错怎么办、结果怎么喂回去
```

---

## 1. Function Calling —— 整个机制的协议骨架

### 1.1 它是一套"模型输出结构化意图"的约定

普通聊天，模型返回文本；启用 Function Calling 后，模型可能返回**结构化的调用意图**：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_abc",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"city\": \"北京\"}"
      }
    }
  ]
}
```

注意：
- `content` 可能为 `null`（模型就是想调工具，没文字要说）
- `arguments` 是**字符串**而非对象 —— 这是历史原因，也是后面参数解析环节要小心的根源
- 可能一次返回**多个 tool_calls**（并行调用）

### 1.2 完整回合的消息流

```
[user]            帮我查北京天气
[assistant]       tool_calls=[get_weather(city="北京")]
[tool]            {"temperature": 22, "desc": "晴"}     # 你执行完回传
[assistant]       北京今天 22°C，天晴。
```

**关键点**：`role=tool` 的消息必须带 `tool_call_id`，和 assistant 那条里的 id 对上。否则下一次请求 OpenAI 会直接 400。

对应代码：[`loop.py`](../src/learning_py/tool_calling/loop.py) 的 `_assistant_tool_calls_message` 和 [`registry.py`](../src/learning_py/tool_calling/registry.py) 的 `ToolResult.to_openai_message`。

### 1.3 各家差异

| 供应商 | 字段名 | 参数字段 |
| --- | --- | --- |
| OpenAI / 兼容 OpenAI 协议 | `tools`，`tool_calls` | `arguments`（字符串） |
| Anthropic | `tools`，`content` 里的 `tool_use` block | `input`（对象） |
| Google Gemini | `tools`，`functionCall` | `args`（对象） |

业务代码别去直接 handle 这些差异 —— 抽一层统一抽象（本项目用 `ToolCall` / `ToolResult`），在边界处做适配。

---

## 2. 工具定义和描述 —— 给 LLM 看的说明书

### 2.1 本质是一段 JSON Schema

LLM 没法"看到"你的 Python 函数，它只能读这段 JSON：

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "查询指定城市的当前天气。",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {"type": "string", "description": "城市中文名，如 '北京'。"},
        "unit": {"type": "string", "default": "c"}
      },
      "required": ["city"]
    }
  }
}
```

### 2.2 写好工具描述的 5 条经验

LLM 选工具、填参数**完全依赖描述文字**。描述随便写，效果就随便。

| 条目 | 为什么 |
| --- | --- |
| 1. **name 简洁+谓语+宾语**（`get_weather` / `search_docs` / `create_issue`） | 一眼知道能干啥 |
| 2. **description 写清"什么时候该用它"** | LLM 在多个工具间选择时，比的就是这句 |
| 3. **每个参数都要有 description** | 否则 LLM 只能靠参数名猜 |
| 4. **枚举值用 `enum` 锁死** | `"unit": {"enum": ["c", "f"]}`，防止 LLM 自由发挥吐出 `"celsius"` |
| 5. **举反例**：在 description 里写"不要用于 X"，避免被乱用 | 比如 "本接口不适用于历史天气，只查当前" |

### 2.3 从 Python 函数自动生成 Schema

手写 JSON 容易和函数签名对不上，常态是用**类型注解 + docstring**自动生成。本项目做法见 [`schema.py`](../src/learning_py/tool_calling/schema.py)：

```python
@registry.tool()
def get_weather(city: str, unit: str = "c") -> dict:
    """查询指定城市的当前天气。

    Args:
        city: 城市中文名，如 "北京"。
        unit: 温度单位，"c"=摄氏度，"f"=华氏度。
    """
    ...
```

`build_tool_definition` 会把这段信息压成 Schema：

- **函数名** → `name`
- **docstring 首段** → `description`
- **类型注解** → `properties` 里每个字段的 `type`
- **`Args:` 段** → `properties[name].description`
- **无默认值的参数** → `required`

生产级参考：`pydantic.TypeAdapter` + `pydantic.BaseModel.model_json_schema()` 更完善。本项目为了演示原理，用 `inspect` + 正则手搓；两者思路一致。

---

## 3. 工具参数解析 —— 最容易翻车的一环

### 3.1 四类典型错误（都要优雅处理）

| 错误 | 出现场景 | 处理策略 |
| --- | --- | --- |
| **非法 JSON** | 模型吐了半截就截断，或多余的 Markdown ````json` | 捕获，作为"请重试"回传给 LLM |
| **缺必填字段** | 模型忘了传 | 回传明确的 "缺少参数 X" |
| **类型不对** | 数字被吐成字符串 `"3"` | 宽松转换 + 保底失败 |
| **枚举值非法** | unit 传了 "celsius" 而不是 "c" | 保留原值让函数报错，由 LLM 下一轮改 |

### 3.2 对应实现

`ToolRegistry.parse_arguments` 的核心约定：

1. **JSON 解析失败** → 抛 `ToolArgumentError`，上层转成 `ToolResult(ok=False)` 回传
2. **缺必填** → 同上
3. **类型能修就修**（字符串数字转 int/float、字符串 bool 转 bool）
4. **Schema 里没有的字段**：悄悄丢弃，防止模型塞垃圾导致 `TypeError: unexpected keyword argument`

```python
# 错误不是 raise 给上层，而是变成一条 tool result 喂回模型：
# {"role": "tool", "content": "[ERROR] 缺少必填参数：city"}
# 模型下一轮就会看到错误，自己修
```

这条设计原则叫：**错误是给 LLM 的，不是给开发者的**。工具链路里 99% 的异常都应该让模型有"下一轮修正"的机会。

---

## 4. 工具执行和结果返回

### 4.1 执行阶段的三件套：超时 / 异常隔离 / 结果截断

一个工具调用必须用"三层防护"包起来：

```
      ┌─────────────────────────────────┐
超时 ─┤  │  异常隔离  │  结果截断  │  ─┐ │
      └─────────────────────────────────┘ │
                                          ▼
                              ToolResult(ok=?, content=..., error=...)
```

- **超时**：死循环 / 卡住的网络请求不能拖垮主循环。本项目用线程 + `join(timeout)` 做协作式兜底。**线程超时不能真正杀掉 Python 代码**，所以工具本身也要有 `requests.get(timeout=...)` 这样的客户端超时。
- **异常隔离**：所有异常都转成 `ToolResult(ok=False, error=...)`，**不允许让异常冒到主循环**。
- **结果截断**：工具可能返回一个 100MB 的 JSON，直接塞回 context 会超上限。截到 `max_result_chars`，并在末尾写明 "已截断"。

### 4.2 返回值必须字符串化

LLM 只认字符串。`dict` / `list` / 数字都要 `json.dumps`。本项目的 `_result_to_text` 负责这个：

```python
>>> _result_to_text({"temperature": 22}, max_chars=4000)
'{"temperature": 22}'
>>> _result_to_text("A" * 10000, max_chars=20)
'AAAAAAAAAAAAAAAAAAAA\n...[结果被截断，原始长度 10000 字符，当前上限 20]'
```

### 4.3 危险工具必须人工确认（线上红线）

删库、打款、发邮件、推线上…… 这些**带副作用的工具绝对不能让 LLM 自主执行**。本项目用装饰器打标：

```python
@registry.tool()
@requires_confirmation
def send_email(to: str, subject: str, body: str) -> str:
    ...
```

`AgentLoop` 碰到带这个标记的工具时：

- 若 `confirm(call)` 返回 `True`：放行执行
- 返回 `False`：作为"用户拒绝"的 tool result 写回，让模型换方案
- 返回 `None`：**抛出 `ConfirmationRequired`**，由外层（Web UI、审批系统）决定怎么办

### 4.4 并行工具调用

模型可能一次返回多个 `tool_calls`（查天气 + 算数 + 查股票）。如果这几个之间没有依赖，**并行执行能显著缩短总耗时**。本项目默认开并行，见 `AgentLoop.parallel_tools`。

注意：并行的前提是工具**无顺序依赖**。模型有时会把依赖的调用一起吐出来，这是它 reasoning 的缺陷 —— 工程上要监控，发现后通过 prompt 提醒它"先拿到 X 才能调 Y"。

---

## 5. 把四步串起来：完整的 Agent Loop

```
┌──────────────────┐
│  messages = [..] │
└────────┬─────────┘
         │
         ▼
┌───────────────────────────────────────────┐
│ while turn < max_iterations:              │
│   resp = llm.chat(messages, tools)        │  ← ① Function Calling
│   if not resp.tool_calls:                 │
│       return resp.content                 │
│   messages.append(assistant_tool_calls)   │
│   for call in resp.tool_calls:            │
│       args = parse_arguments(call)        │  ← ③ 参数解析
│       result = invoke(call, args)         │  ← ④ 执行 + 兜底
│       messages.append(result_message)     │
└───────────────────────────────────────────┘
```

核心细节：

- **`messages.append(assistant_tool_calls)` 不能省**。OpenAI 要求：返回 tool_calls 的 assistant 消息 + 对应的 tool 消息必须成对出现。
- **`max_iterations` 必须设**（本项目默认 8）。防止模型陷入"调工具 - 看结果 - 再调同一个工具"的死循环，线上出过真事故。
- **审计日志**：每一步的 `tool_call` / `tool_result` 都通过 `on_event` 回调流出，落审计表。Agent 出问题时，能回放出"它到底做了什么"。

---

## 6. 线上踩坑清单

| 坑 | 症状 | 对策 |
| --- | --- | --- |
| 工具描述太短 | 模型选错工具 / 不调工具 | description 写明"何时使用、何时不用" |
| arguments 忘 `json.loads` | `TypeError: string indices must be integers` | 统一解析入口 `parse_arguments` |
| 工具返回对象直接往 context 塞 | 非法消息 | `_result_to_text` 统一序列化 |
| 没截断长结果 | 一轮对话直接爆 context | `max_result_chars` 兜底 |
| 缺 `tool_call_id` 对位 | 下一轮 API 400 | `ToolResult.to_openai_message` 自动带上 |
| 没设 `max_iterations` | 死循环烧钱 | 主循环硬限制 |
| 让 LLM 直接决定删库/打款 | 生产事故 | `@requires_confirmation` + 人工审批 |
| 工具里的 `time.sleep(...)` 没超时 | 卡死 Agent | Registry 层的 timeout + 客户端层 timeout 双保险 |
| 工具异常 raise 到主循环 | Agent 直接挂 | 统一 `try/except` 转 `ToolResult(ok=False)` |

---

## 7. 一页纸 Checklist

写一个新工具前过一遍：

- [ ] 名字是"动词+宾语"吗？描述写清了**何时用 / 何时不用**吗？
- [ ] 每个参数都有 description 吗？枚举用 `enum` 锁了吗？
- [ ] 必填 / 可选分清了吗？（默认值 = 可选）
- [ ] 函数内部对坏输入能**抛异常**（而非静默错值）吗？异常信息对 LLM 友好吗？
- [ ] 有副作用？上了 `@requires_confirmation` 吗？
- [ ] I/O 操作带客户端超时了吗？
- [ ] 返回值序列化后大概多大？需要分页/摘要吗？
- [ ] 注册到 `ToolRegistry` 后，跑 `registry.as_openai_tools()` 看生成的 schema 合理吗？

---

## 10. 配套阅读

- [`ai-agent.md`](./ai-agent.md) — Agent 四大能力：感知 / 推理 / 决策 / 执行
- [`prompt-engineering.md`](./prompt-engineering.md) — 工具描述本身就是一种 Prompt
- [`llm-api-practices.md`](./llm-api-practices.md) — Tool Calling 回合里每次 LLM 请求，都得套上那一套采样参数 + 重试 + 熔断
