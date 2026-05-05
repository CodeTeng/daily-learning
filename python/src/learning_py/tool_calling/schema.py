"""工具定义与 JSON Schema 生成（Pydantic 版本）。

**核心命题**：LLM 看不见你的 Python 函数，只能看见**字符串描述**。所以
"工具定义"的本质就是把函数名 / docstring / 参数类型 / 必填项全部翻译成
一段 JSON Schema，拼进 system prompt 或 tools 字段里。

LLM 能识别的 Schema 通常叫 **OpenAI Function Schema**：

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "查询指定城市的天气",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {"type": "string", "description": "城市名，如 '北京'"},
        "unit": {"type": "string", "enum": ["c", "f"], "default": "c"}
      },
      "required": ["city"]
    }
  }
}
```

本模块的做法：

- 用 `inspect.signature` + `get_type_hints` 读出函数签名
- 用 **Pydantic v2 的 `create_model`** 在运行时造一个模型类，让它帮我们生成
  **真正标准** 的 JSON Schema（比自己手搓 dict 准确太多：处理 `Optional` /
  `Literal` / `Enum` / `list` / `dict` / `BaseModel` 等）
- 同时为每个参数构造一个 `TypeAdapter`，供 `registry.parse_arguments` 做
  运行期校验
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from pydantic import ConfigDict, Field, TypeAdapter, create_model


# --------------------------------------------------------------------------- #
# 1. Docstring 解析（抽字段说明）
# --------------------------------------------------------------------------- #

_PARAM_PATTERN = re.compile(r"^\s*:param\s+(\w+)\s*:\s*(.+)$")
_GOOGLE_ARG_PATTERN = re.compile(r"^\s+(\w+)\s*(?:\([^)]+\))?\s*:\s*(.+)$")

_SECTION_HEAD = re.compile(
    r"^(Args|Arguments|Parameters|Returns|Yields|Raises|Example|Examples|Note|Notes)"
    r"\s*:\s*$"
)


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """把 docstring 拆成「总体描述」和「各参数描述」。

    支持两种最常见的风格：

    - **Sphinx / reStructuredText**：`:param name: desc`
    - **Google 风格**：

      ```
      Args:
          name: desc
      ```
    """
    if not doc:
        return "", {}

    cleaned = inspect.cleandoc(doc)
    raw_lines = cleaned.splitlines()

    summary_lines: list[str] = []
    current_section: str | None = None
    section_body: dict[str, list[str]] = {}
    params: dict[str, str] = {}

    for line in raw_lines:
        m_sphinx = _PARAM_PATTERN.match(line)
        if m_sphinx:
            params[m_sphinx.group(1)] = m_sphinx.group(2).strip()
            continue

        head = _SECTION_HEAD.match(line.strip())
        if head:
            section_name = head.group(1)
            current_section = section_name
            section_body[section_name] = []
            continue

        if current_section is None:
            summary_lines.append(line)
        else:
            section_body[current_section].append(line)

    for key in ("Args", "Arguments", "Parameters"):
        for line in section_body.get(key, []):
            gm = _GOOGLE_ARG_PATTERN.match(line)
            if gm:
                params[gm.group(1)] = gm.group(2).strip()

    summary = "\n".join(summary_lines).strip()
    return summary, params


# --------------------------------------------------------------------------- #
# 2. 工具定义数据结构
# --------------------------------------------------------------------------- #

@dataclass
class ToolDefinition:
    """一个工具的完整定义。

    注意：因为需要持有可调用对象 `fn`，这里仍然用 dataclass 而非 BaseModel
    （BaseModel 对 Callable 支持不友好，会想要序列化它）。
    对外暴露的数据（`parameters_schema`）是 Pydantic 生成的标准 JSON Schema。
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    fn: Callable[..., Any]
    # 每个参数的 TypeAdapter，供 ToolRegistry.parse_arguments 做运行期校验
    param_adapters: dict[str, TypeAdapter[Any]]

    def to_openai_tool(self) -> dict[str, Any]:
        """OpenAI Chat Completions `tools` 字段的单条。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Anthropic Messages `tools` 字段的单条。字段名稍有不同。"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters_schema,
        }


# --------------------------------------------------------------------------- #
# 3. 核心：从 Python 函数构造 ToolDefinition
# --------------------------------------------------------------------------- #

def build_tool_definition(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
) -> ToolDefinition:
    """从 Python 函数自动构造 ToolDefinition。

    实现思路：
    1. `inspect.signature` + `get_type_hints` 收集参数信息
    2. 用 **`pydantic.create_model`** 动态造一个模型类 `ArgsModel`
       —— 让 Pydantic 帮我们搞定所有类型到 JSON Schema 的转换
    3. 调 `ArgsModel.model_json_schema()` 拿到标准 JSON Schema
    4. 为每个字段单独造一个 `TypeAdapter`，方便 registry 逐参数校验
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    summary, param_docs = parse_docstring(fn.__doc__)

    # 1) 收集字段定义：{name: (type, Field(...))}
    field_definitions: dict[str, Any] = {}
    param_adapters: dict[str, TypeAdapter[Any]] = {}

    for pname, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        tp = hints.get(pname, str)
        desc = param_docs.get(pname)

        if param.default is inspect.Parameter.empty:
            # 必填：用 `...`
            field_definitions[pname] = (
                tp,
                Field(..., description=desc) if desc else Field(...),
            )
        else:
            field_definitions[pname] = (
                tp,
                Field(default=param.default, description=desc)
                if desc
                else Field(default=param.default),
            )

        param_adapters[pname] = TypeAdapter(tp)

    # 2) 动态生成 Pydantic 模型
    #    配置 `extra="forbid"` 可以让 schema 的 additionalProperties=false，
    #    但某些 LLM 会因此更死板，保留默认的 ignore 行为即可。
    args_model = create_model(
        f"{fn.__name__.title()}Args",
        __config__=ConfigDict(extra="ignore"),
        **field_definitions,
    )

    # 3) 生成 JSON Schema 并做一些"贴合 OpenAI"的小清理
    parameters_schema = args_model.model_json_schema()
    _strip_pydantic_noise(parameters_schema)

    return ToolDefinition(
        name=name or fn.__name__,
        description=(description or summary or fn.__name__).strip(),
        parameters_schema=parameters_schema,
        fn=fn,
        param_adapters=param_adapters,
    )


# --------------------------------------------------------------------------- #
# 4. 清理 Pydantic 产出的 JSON Schema
# --------------------------------------------------------------------------- #

def _strip_pydantic_noise(schema: dict[str, Any]) -> None:
    """Pydantic 生成的 schema 里有一些字段对 LLM 没用，甚至会干扰。

    典型的有：
    - `title`：每个字段都会带一个大写开头的 title，对 LLM 是噪声
    - `$defs` / `definitions`：只要没有递归引用，展平更好
    - 顶层的 `title`（如 `"GetWeatherArgs"`）
    """
    schema.pop("title", None)

    props = schema.get("properties")
    if isinstance(props, dict):
        for key, prop in list(props.items()):
            if isinstance(prop, dict):
                prop.pop("title", None)
                # 递归清理嵌套 object
                if prop.get("type") == "object":
                    _strip_pydantic_noise(prop)
                # 数组里 items 也清
                items = prop.get("items")
                if isinstance(items, dict):
                    items.pop("title", None)
            props[key] = prop

    # $defs / definitions 里的模型也同样清一下 title
    for defs_key in ("$defs", "definitions"):
        defs = schema.get(defs_key)
        if isinstance(defs, dict):
            for name, sub in list(defs.items()):
                if isinstance(sub, dict):
                    sub.pop("title", None)
                    _strip_pydantic_noise(sub)
                defs[name] = sub
