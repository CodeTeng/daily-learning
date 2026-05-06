"""
LangChain Models and Messages - 核心组件演示

本模块展示了如何使用LangChain的Models和Messages来构建基础的LLM应用：
- ChatOpenAI: 使用OpenAI的聊天模型
- 消息类型: HumanMessage, AIMessage, SystemMessage, ToolMessage
- 消息历史管理: 维护对话上下文
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)

from learning_py.langchain_framework.config import create_chat_model


def _create_model(temperature: float = 0.7) -> ChatOpenAI:
    """创建统一配置的ChatOpenAI实例。"""
    return create_chat_model(temperature=temperature)


def demo_basic_chat_model():
    """演示1: 基础聊天模型使用"""
    print("=" * 60)
    print("演示1: 基础聊天模型")
    print("=" * 60)
    
    # 初始化ChatOpenAI模型
    model = _create_model(temperature=0.7)
    
    # 简单的消息调用
    message = HumanMessage(content="你好！请介绍一下自己")
    response = model.invoke([message])
    
    print(f"用户: 你好！请介绍一下自己")
    print(f"AI: {response.content}")
    print()


def demo_message_types():
    """演示2: 不同的消息类型"""
    print("=" * 60)
    print("演示2: 消息类型演示")
    print("=" * 60)
    
    model = _create_model(temperature=0.7)
    
    # 创建不同类型的消息
    system_message = SystemMessage(
        content="你是一个专业的Python开发者，擅长解答编程问题"
    )
    human_message = HumanMessage(content="如何在Python中使用装饰器？")
    
    messages = [system_message, human_message]
    
    print("System: 你是一个专业的Python开发者，擅长解答编程问题")
    print(f"User: {human_message.content}")
    
    response = model.invoke(messages)
    print(f"AI: {response.content[:200]}...")  # 截断输出
    print()


def demo_conversation_history():
    """演示3: 对话历史管理"""
    print("=" * 60)
    print("演示3: 对话历史管理")
    print("=" * 60)
    
    model = _create_model(temperature=0.7)
    
    # 构建对话历史
    conversation = [
        SystemMessage(content="你是一个友好的AI助手"),
        HumanMessage(content="我叫Alice，很高兴认识你"),
        AIMessage(content="你好Alice！我很高兴认识你。我是Claude，一个AI助手。有什么我可以帮助你的吗？"),
        HumanMessage(content="你记得我的名字吗？"),
    ]
    
    print("对话历史:")
    for msg in conversation:
        role = "系统" if isinstance(msg, SystemMessage) else \
               "用户" if isinstance(msg, HumanMessage) else \
               "AI" if isinstance(msg, AIMessage) else "其他"
        print(f"{role}: {msg.content}")
    
    # 调用模型，利用对话历史
    response = model.invoke(conversation)
    print(f"\nAI的新回复: {response.content}")
    print()


def demo_tool_message():
    """演示4: 工具消息处理"""
    print("=" * 60)
    print("演示4: 工具消息处理")
    print("=" * 60)
    
    model = _create_model(temperature=0.7)
    
    # 模拟一个Agent调用工具的过程
    messages = [
        HumanMessage(content="旧金山的天气如何？"),
        AIMessage(
            content="让我查一下旧金山的天气信息",
            tool_calls=[
                {
                    "id": "call_12345",
                    "name": "get_weather",
                    "args": {"city": "San Francisco"},
                }
            ],
        ),
        ToolMessage(
            content="旧金山的天气是晴朗的，温度约为22°C",
            tool_call_id="call_12345",
            name="get_weather",
        ),
        AIMessage(content="旧金山今天的天气很好！天晴，温度约22°C。"),
    ]
    
    print("消息流程:")
    for msg in messages:
        msg_type = type(msg).__name__
        content = msg.content[:80] if len(msg.content) > 80 else msg.content
        print(f"{msg_type}: {content}")
    print()


def demo_model_parameters():
    """演示5: 模型参数配置"""
    print("=" * 60)
    print("演示5: 模型参数配置")
    print("=" * 60)
    
    # 不同temperature的模型 - 控制创意度
    creative_model = _create_model(temperature=0.9)  # 高创意度
    
    precise_model = _create_model(temperature=0.1)  # 低创意度，更精确
    
    prompt = "生成一个有创意的产品名称"
    message = HumanMessage(content=prompt)
    
    print(f"提示: {prompt}\n")
    
    print("高创意度模型 (temperature=0.9):")
    creative_response = creative_model.invoke([message])
    print(f"  {creative_response.content[:100]}")
    
    print("\n精确模型 (temperature=0.1):")
    precise_response = precise_model.invoke([message])
    print(f"  {precise_response.content[:100]}")
    print()


def demo_batch_messages():
    """演示6: 批量处理多个消息"""
    print("=" * 60)
    print("演示6: 批量处理消息")
    print("=" * 60)
    
    model = _create_model(temperature=0.7)
    
    # 创建多个对话
    conversations = [
        [HumanMessage(content="Python中什么是GIL？")],
        [HumanMessage(content="什么是异步编程？")],
        [HumanMessage(content="如何优化数据库查询？")],
    ]
    
    print("批量处理多个问题:")
    results = model.batch(conversations)
    
    for i, result in enumerate(results, 1):
        print(f"\n问题{i}的回答: {result.content[:100]}...")


def demo_chat_with_history_loop():
    """演示7: 交互式对话循环"""
    print("=" * 60)
    print("演示7: 交互式对话循环")
    print("=" * 60)
    
    model = _create_model(temperature=0.7)
    
    # 初始化消息历史
    messages = [
        SystemMessage(content="你是一个有知识的助手，帮助用户回答问题。")
    ]
    
    # 模拟多轮对话
    user_inputs = [
        "什么是装饰器？",
        "请给一个具体例子",
        "这有什么好处？",
    ]
    
    print("模拟多轮对话:\n")
    for user_input in user_inputs:
        # 添加用户消息
        messages.append(HumanMessage(content=user_input))
        print(f"用户: {user_input}")
        
        # 获取AI回复
        response = model.invoke(messages)
        print(f"AI: {response.content[:150]}...\n")
        
        # 添加AI消息到历史
        messages.append(AIMessage(content=response.content))


if __name__ == "__main__":
    """运行所有演示"""
    demo_basic_chat_model()
    demo_message_types()
    demo_conversation_history()
    demo_tool_message()
    demo_model_parameters()
    demo_batch_messages()
    demo_chat_with_history_loop()
    
    print("\n" + "=" * 60)
    print("所有演示完成！")
    print("=" * 60)
