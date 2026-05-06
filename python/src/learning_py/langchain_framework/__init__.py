"""
LangChain Framework - 核心组件学习模块

本包包含LangChain框架的核心组件演示和学习资料：

子模块:
- demo: 统一运行入口
- models_and_messages: 模型和消息处理
- tools_and_agents: 工具定义和Agent开发  
- short_term_memory: 短期记忆和对话历史
- streaming_demo: 流式输出处理
- structured_output: 结构化输出解析
- prompt_caching: Prompt Caching 演示

使用方式:
    python -m learning_py.langchain_framework.demo
    python -m learning_py.langchain_framework.models_and_messages
    python -m learning_py.langchain_framework.tools_and_agents
    python -m learning_py.langchain_framework.short_term_memory
    python -m learning_py.langchain_framework.streaming_demo
    python -m learning_py.langchain_framework.structured_output
    python -m learning_py.langchain_framework.prompt_caching
"""

__version__ = "1.0.0"
__all__ = [
    "demo",
    "models_and_messages",
    "tools_and_agents",
    "short_term_memory",
    "streaming_demo",
    "structured_output",
    "prompt_caching",
]
