# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUntypedBaseClass=false, reportUnannotatedClassAttribute=false, reportUnusedCallResult=false, reportMissingTypeStubs=false
"""OpenAI 兼容协议的 LLMClient 实现。

读取环境变量：
- `LLM_API_KEY`   必填
- `LLM_MODEL`     必填，如 "gpt-4o-mini" / "deepseek-chat" / "qwen-plus"
- `LLM_BASE_URL`  可选，用于接第三方兼容网关（不填则走官方 OpenAI）
- `LLM_TEMPERATURE` / `LLM_MAX_TOKENS`  可选，覆盖默认采样参数

如果同目录或上级目录有 `.env`，会自动加载。
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from learning_py.llm_api.params import SamplingParams
from learning_py.tool_calling.loop import LLMResponse
from learning_py.tool_calling.registry import ToolCall


# --------------------------------------------------------------------------- #
# 环境变量加载
# --------------------------------------------------------------------------- #

def load_env(path: str | None = None) -> None:
    """尽量安静地加载 .env。失败不报错（兼容 CI 没装 dotenv 的场景）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(path, override=False)


# --------------------------------------------------------------------------- #
# 配置模型（Pydantic）
# --------------------------------------------------------------------------- #

class LLMConfig(BaseModel):
    """LLM 客户端配置。用 Pydantic 做字段校验 + 不可变。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    api_key: str = Field(..., min_length=1, description="LLM API Key")
    model: str = Field(..., min_length=1, description="模型名")
    base_url: str | None = Field(
        default=None,
        description="兼容网关 base URL，不填走官方 OpenAI",
    )
    sampling: SamplingParams = Field(
        default_factory=lambda: SamplingParams(temperature=0.2, max_tokens=1024)
    )

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        # 简单校验下 URL 合法性，不做严格处理
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError(f"base_url 必须以 http:// 或 https:// 开头，收到：{v}")
        return v.rstrip("/")

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从 `.env` / 系统环境变量构造。缺必需字段抛 `RuntimeError`。"""
        load_env()
        api_key = os.environ.get("LLM_API_KEY")
        model = os.environ.get("LLM_MODEL")
        if not api_key or not model:
            raise RuntimeError(
                "缺少环境变量：需要 LLM_API_KEY 和 LLM_MODEL。"
                "请在 python/.env 或系统环境里配置。"
            )
        base_url = os.environ.get("LLM_BASE_URL") or None

        temperature = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
        max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
        sampling = SamplingParams(temperature=temperature, max_tokens=max_tokens)

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            sampling=sampling,
        )


# --------------------------------------------------------------------------- #
# OpenAI 兼容客户端
# --------------------------------------------------------------------------- #

class OpenAILLMClient:
    """实现 `learning_py.tool_calling.loop.LLMClient` 协议。

    核心职责：
    1. 把 `messages` + `tools` 发到 OpenAI 兼容端点
    2. 把返回的 `tool_calls` 转成我们自己的 `ToolCall` 列表
    3. 把 `content` + `tool_calls` 合起来塞回 `LLMResponse`
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        # 延迟 import，模块 import 时不强依赖 openai
        from openai import OpenAI

        self.config = config or LLMConfig.from_env()
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    # ---- LLMClient 协议 ------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            **self.config.sampling.to_openai_kwargs(),
        }
        # 只有真的有工具时才传 tools，否则某些网关会报参数非法
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            # OpenAI SDK 返回 pydantic 对象，抽字段即可
            fn = tc.function
            tool_calls.append(ToolCall(
                id=tc.id,
                name=fn.name,
                # arguments 保持 **字符串** 形式，registry.parse_arguments 负责解析
                arguments=fn.arguments or "{}",
            ))

        # 有些模型（DeepSeek V3 / Claude Extended Thinking / o1 系列）会返回
        # reasoning_content 或类似字段，下一轮请求必须把它原样带回去，否则 400。
        # OpenAI SDK 会把未知字段塞进 model_extra 里。
        extras: dict[str, Any] = {}
        raw_extra = getattr(msg, "model_extra", None) or {}
        for key in ("reasoning_content", "thinking"):
            value = raw_extra.get(key)
            if value is not None:
                extras[key] = value

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            extra_assistant_fields=extras,
        )


# --------------------------------------------------------------------------- #
# 便捷入口
# --------------------------------------------------------------------------- #

def make_client_from_env() -> OpenAILLMClient:
    """从环境变量构建客户端，失败会给出清晰错误。"""
    return OpenAILLMClient(LLMConfig.from_env())
