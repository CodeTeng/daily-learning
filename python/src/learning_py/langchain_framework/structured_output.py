"""
LangChain structured output demos.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from learning_py.langchain_framework.config import create_chat_model


def _model(temp: float = 0) -> ChatOpenAI:
    return create_chat_model(temperature=temp)


class Person(BaseModel):
    name: str = Field(description="person name")
    age: int = Field(description="person age")
    city: str = Field(description="city")


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned


def demo_structured() -> None:
    print("=" * 60)
    print("Demo: Structured Output")
    print("=" * 60)
    messages = [
        SystemMessage(content="Return the result as valid JSON."),
        HumanMessage(content="Extract: Tom is 29 years old and lives in Beijing."),
    ]

    structured_model = _model().with_structured_output(Person)

    try:
        result = structured_model.invoke(messages)
    except Exception as exc:
        print(f"[提示] structured output 解析失败，改用 JSON 兜底：{exc.__class__.__name__}")
        raw_response = _model().invoke(messages)
        cleaned = _strip_code_fence(raw_response.content)
        fallback = Person.model_validate_json(cleaned)
        print(fallback.model_dump())
        return

    print(result.model_dump())


if __name__ == "__main__":
    demo_structured()
