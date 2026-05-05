"""OpenAI 协议兼容的 LLM 客户端，可直连 DeepSeek / 任何兼容 OpenAI 的网关。

关键点：
- 接口与 `FakeLLM` 完全一致：`complete(prompt) -> str` + `call_count`
  这样 ReAct / Plan-and-Execute / Reflection / Multi-Agent 4 种架构**一行代码不改**就能切到真实模型。
- 配置从 `.env` 读：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。
- 可选 `system_prompt`，用于角色化（Multi-Agent 里给 researcher / writer / critic 不同的人设）。

SECURITY:
- API Key 只从环境变量读，不允许通过参数硬编码；防止误提交。
- `.env` 已在 `.gitignore` 中。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_dotenv_once() -> None:
    """启动时尝试加载 `python/.env`。

    用 python-dotenv 而不是手写：兼容引号、转义、注释。
    没有装 dotenv 也不报错，留一条提示就行。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - 只是软依赖
        return

    # 找最近的 .env：优先 python/ 子项目根目录
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


_load_dotenv_once()


@dataclass
class OpenAICompatLLM:
    """通用 OpenAI 协议客户端。默认从环境变量读配置。

    Args:
        name: 给这个 LLM 实例起个名字，方便 Multi-Agent 区分角色。
        system_prompt: 可选的 system message，用于角色化。
        model / base_url / api_key: 不传则从 .env 读。
        temperature: 默认 0.2，推理类任务推荐低温度；调用方可覆盖。
        max_tokens: 默认 1024，避免超额计费。
        timeout: HTTP 超时（秒）。

    使用：
        llm = OpenAICompatLLM()
        text = llm.complete("你好")
    """

    name: str = "openai-compat"
    system_prompt: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout: float = 60.0

    # 运行期统计（与 FakeLLM 一致，便于断言）
    call_count: int = 0
    trace: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # 懒导入，避免运行 demo.py（用 FakeLLM）时也强依赖 openai
        from openai import OpenAI

        model = self.model or os.environ.get("LLM_MODEL")
        base_url = self.base_url or os.environ.get("LLM_BASE_URL")
        api_key = self.api_key or os.environ.get("LLM_API_KEY")

        missing = [
            name
            for name, value in {
                "LLM_MODEL": model,
                "LLM_BASE_URL": base_url,
                "LLM_API_KEY": api_key,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"缺少环境变量：{missing}。请在 python/.env 中配置（可参考 .env.example）。"
            )

        # 允许 .env 里覆盖默认采样参数
        if env_t := os.environ.get("LLM_TEMPERATURE"):
            self.temperature = float(env_t)
        if env_m := os.environ.get("LLM_MAX_TOKENS"):
            self.max_tokens = int(env_m)

        self.model = model
        self.base_url = base_url
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout)

    # ------------------------------------------------------------------ #
    # 与 FakeLLM 完全一致的接口
    # ------------------------------------------------------------------ #
    def complete(self, prompt: str) -> str:
        self.call_count += 1
        self.trace.append(prompt[:80].replace("\n", " ⏎ "))

        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": prompt})

        resp = self._client.chat.completions.create(
            model=self.model,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        content = resp.choices[0].message.content or ""
        return content.strip()
