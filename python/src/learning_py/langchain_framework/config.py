"""
Shared environment and model helpers for LangChain demos.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


@dataclass(frozen=True)
class ChatConfig:
    model: str
    api_key: str
    base_url: str


def load_chat_config() -> ChatConfig:
    model = (os.getenv("LLM_MODEL") or "").strip()
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    base_url = (os.getenv("LLM_BASE_URL") or "").strip()

    missing = [
        name
        for name, value in (
            ("LLM_MODEL", model),
            ("LLM_API_KEY", api_key),
            ("LLM_BASE_URL", base_url),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Configure them in python/.env based on python/.env.example."
        )

    return ChatConfig(model=model, api_key=api_key, base_url=base_url)


def create_chat_model(temperature: float = 0.7) -> ChatOpenAI:
    chat_config = load_chat_config()
    return ChatOpenAI(
        model=chat_config.model,
        temperature=temperature,
        api_key=chat_config.api_key,
        base_url=chat_config.base_url,
    )