"""把 prompt 模板接到真实 LLM API（OpenAI 协议兼容，DeepSeek / OpenAI 任选）。

为什么单独放一个文件？
- `demo.py` 只演示模板**渲染结构**，零依赖、随时能跑。
- 真实调用涉及密钥、网络、计费，单独隔离。

前置：
    1. `uv sync`（pyproject 已经声明了 openai + python-dotenv）
    2. 在 `python/.env` 里配置（参考 `python/.env.example`）：
        LLM_BASE_URL=https://api.deepseek.com
        LLM_API_KEY=sk-xxx
        LLM_MODEL=deepseek-chat

运行：
    uv run python -m learning_py.prompt.real_call
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from learning_py.prompt.templates import json_output_prompt, role_system_prompt


def _load_env_once() -> None:
    """启动时尝试加载 `python/.env`。"""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - 软依赖
        return
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


def call_llm_structured(article: str) -> dict:
    """用 OpenAI Chat Completions 调用 JSON 抽取 Prompt。

    - temperature=0：抽取任务关掉随机性
    - response_format=json_object：强制吐 JSON，解析失败率大幅下降
    """
    _load_env_once()

    from openai import OpenAI  # 延迟 import，让 demo.py 即便没装 openai 也能跑

    base_url = os.environ["LLM_BASE_URL"]
    api_key = os.environ["LLM_API_KEY"]
    model = os.environ["LLM_MODEL"]

    client = OpenAI(api_key=api_key, base_url=base_url)
    system = role_system_prompt(
        role="严谨的信息抽取器，输出必须是合法 JSON",
        audience="下游自动化程序",
    )
    user = json_output_prompt(article)

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


if __name__ == "__main__":
    sample = (
        "近日，某开源社区发布了新版 LLM 推理框架，相比上一版推理速度提升 40%，"
        "显存占用下降 25%。"
    )
    result = call_llm_structured(sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
