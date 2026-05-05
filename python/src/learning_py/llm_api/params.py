"""LLM 采样参数封装。

为什么要单独抽一层而不是每次调用直接传字典？

1. **类型校验**：`temperature=2.5` 这种超范围值在运行时就拦掉，不到线上才报错。
2. **语义绑定**：不同任务有固定的参数组合（抽取用 0.0、写作用 0.9），用
   Profile 统一管理，避免散落在各处的魔法数字。
3. **供应商差异**：OpenAI / Anthropic / 本地 vLLM 对参数名略有不同（比如
   `max_tokens` vs `max_output_tokens`），集中一处转换比散落各处改省事。

下面的参数含义：

- `temperature` (0.0 ~ 2.0)：采样温度。越低越确定性，越高越发散。
- `top_p` (0.0 ~ 1.0)：核采样。只从累积概率 top_p 的 token 里挑。
    **temperature 与 top_p 一般只调一个**，另一个保持默认（1.0）。
- `max_tokens`：单次响应最多生成的 token 数。**必须设**，否则模型可能
    一路写到上下文上限，费用失控。
- `frequency_penalty` (-2.0 ~ 2.0)：抑制重复 token 出现频率（正值抑制）。
- `presence_penalty` (-2.0 ~ 2.0)：鼓励谈论新话题（正值鼓励）。
- `stop`：遇到这些字符串就停止生成，常用于"只要第一行"、"只要 JSON 到 `}` 为止"。
- `seed`：OpenAI 等支持的"尽量可复现"种子。相同输入 + 相同 seed 尽量给相同输出。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# --------------------------------------------------------------------------- #
# 1. 参数对象：不可变 + 校验
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SamplingParams:
    """LLM 采样参数。冻结 dataclass，避免被下游偷偷改掉。"""

    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 1024
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stop: tuple[str, ...] = ()
    seed: int | None = None

    def __post_init__(self) -> None:
        # 用 object.__setattr__ 之前就校验，避免暴露无效对象
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"temperature 必须在 [0, 2] 内，收到 {self.temperature}")
        if not 0.0 <= self.top_p <= 1.0:
            raise ValueError(f"top_p 必须在 [0, 1] 内，收到 {self.top_p}")
        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens 必须 > 0，收到 {self.max_tokens}")
        if not -2.0 <= self.frequency_penalty <= 2.0:
            raise ValueError("frequency_penalty 必须在 [-2, 2] 内")
        if not -2.0 <= self.presence_penalty <= 2.0:
            raise ValueError("presence_penalty 必须在 [-2, 2] 内")
        # 软警告：两个随机性参数同时调是常见坑
        if self.temperature != 0.7 and self.top_p != 1.0:  # pragma: no cover - 经验性提示
            import warnings
            warnings.warn(
                "temperature 和 top_p 一般只调一个，同时调会让行为难以预测。",
                stacklevel=2,
            )

    # --- 供应商适配：转成不同家的 kwargs ------------------------------------

    def to_openai_kwargs(self) -> dict[str, Any]:
        """转成 OpenAI Chat Completions 风格的 kwargs。"""
        kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
        }
        if self.stop:
            kwargs["stop"] = list(self.stop)
        if self.seed is not None:
            kwargs["seed"] = self.seed
        return kwargs

    def to_anthropic_kwargs(self) -> dict[str, Any]:
        """Anthropic Messages API 的字段名有差异。"""
        kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,  # 注意：Anthropic 是必填
        }
        if self.stop:
            kwargs["stop_sequences"] = list(self.stop)
        # Anthropic 目前不支持 frequency/presence/seed
        return kwargs

    def as_dict(self) -> dict[str, Any]:
        """用于日志打印 / 观测。"""
        return asdict(self)


# --------------------------------------------------------------------------- #
# 2. 任务类型 → 推荐参数 Profile
# --------------------------------------------------------------------------- #

class TaskType(str, Enum):
    """常见任务类型，决定默认采样参数。"""

    EXTRACTION = "extraction"          # 信息抽取、实体识别
    CLASSIFICATION = "classification"  # 分类、意图识别
    TRANSLATION = "translation"        # 翻译
    SUMMARIZATION = "summarization"    # 摘要
    QA = "qa"                          # 通用问答、解释
    CODE = "code"                      # 代码生成/修 bug
    CREATIVE = "creative"              # 写作、头脑风暴、营销文案


# 经验值：温度 / max_tokens / seed 是否建议固定
_PROFILES: dict[TaskType, SamplingParams] = {
    # 抽取/分类：确定性优先，开 seed
    TaskType.EXTRACTION: SamplingParams(
        temperature=0.0, top_p=1.0, max_tokens=1024, seed=42
    ),
    TaskType.CLASSIFICATION: SamplingParams(
        temperature=0.0, top_p=1.0, max_tokens=64, seed=42
    ),
    # 翻译/摘要：低温度，有一点灵活度
    TaskType.TRANSLATION: SamplingParams(
        temperature=0.2, top_p=1.0, max_tokens=2048
    ),
    TaskType.SUMMARIZATION: SamplingParams(
        temperature=0.3, top_p=1.0, max_tokens=1024
    ),
    # 通用 QA：中等温度
    TaskType.QA: SamplingParams(temperature=0.5, top_p=1.0, max_tokens=2048),
    # 代码：低温度，但要给够 max_tokens，且遇到 ``` 结束
    TaskType.CODE: SamplingParams(
        temperature=0.2, top_p=1.0, max_tokens=4096,
        stop=("\n```\n",),
    ),
    # 创作：高温度 + 频率惩罚压制啰嗦重复
    TaskType.CREATIVE: SamplingParams(
        temperature=0.9, top_p=1.0, max_tokens=2048,
        frequency_penalty=0.3, presence_penalty=0.2,
    ),
}


def params_for(task: TaskType, **overrides: Any) -> SamplingParams:
    """按任务类型取一份默认参数，允许局部覆盖。

    >>> params_for(TaskType.CODE, max_tokens=8192).max_tokens
    8192
    """
    base = _PROFILES[task]
    if not overrides:
        return base
    merged = {**asdict(base), **overrides}
    # asdict 会把 tuple 转成 list，这里还原
    if isinstance(merged.get("stop"), list):
        merged["stop"] = tuple(merged["stop"])
    return SamplingParams(**merged)


# --------------------------------------------------------------------------- #
# 3. Budget：限制单次调用的成本上限
# --------------------------------------------------------------------------- #

@dataclass
class TokenBudget:
    """给一次调用设 token 预算，超了就截断或拒绝。

    真实场景：上游传进来一段很长的用户输入 + 一段系统提示词 + few-shot 示例。
    加起来可能已经接近模型上下文上限，再让模型生成 max_tokens 会直接 400。
    所以一定要算「prompt_tokens + max_tokens <= context_window」。
    """

    context_window: int      # 模型上下文总窗口，如 128_000
    reserved_output: int     # 给输出留的最少 token 数
    hard_input_limit: int = field(init=False)

    def __post_init__(self) -> None:
        if self.reserved_output >= self.context_window:
            raise ValueError("reserved_output 不能 >= context_window")
        self.hard_input_limit = self.context_window - self.reserved_output

    def fit_max_tokens(self, prompt_tokens: int, requested: int) -> int:
        """根据已用 prompt_tokens，推算安全的 max_tokens。"""
        remaining = self.context_window - prompt_tokens
        if remaining <= 0:
            raise ValueError(
                f"prompt_tokens={prompt_tokens} 已超过上下文窗口 {self.context_window}"
            )
        return max(1, min(requested, remaining))
