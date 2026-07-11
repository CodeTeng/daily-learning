# 企业落地 Agent 项目：实践指南与解决方案

> 配套代码：[`src/learning_py/agent/observability.py`](../src/learning_py/agent/observability.py) |
> [`otel_tracing.py`](../src/learning_py/agent/otel_tracing.py) |
> [`langsmith_tracing.py`](../src/learning_py/agent/langsmith_tracing.py)
>
> 从"Agent 怎么写"到"Agent 怎么在公司里活下来"——本文聚焦的是**工程化落地**：
> 场景怎么选、安全怎么守、成本怎么控、出了问题怎么查。

---

## 0. 全局视角：六个必须回答的问题

在动手之前，先对齐这张清单。任何一个没回答好，项目都可能在某个阶段翻车：

| # | 问题 | 翻车后果 |
|---|------|---------|
| 1 | **做什么场景、边界在哪** | 功能越做越散，用户信任崩塌 |
| 2 | **怎么保证可靠和安全** | 幻觉、越权、数据泄露 |
| 3 | **工程架构怎么搭** | 出了问题没法查，迭代全靠猜 |
| 4 | **成本怎么控** | Token 账单爆炸，项目被砍 |
| 5 | **用户体验怎么做** | 黑盒等待、不可纠正、期望落空 |
| 6 | **团队怎么协作、流程怎么转** | Prompt 散落各处，Bad Case 没人管 |

下面逐个给出解决方案。

---

## 1. 明确业务场景与边界

### 1.1 场景筛选：频率 × 价值 × 可自动化

不是所有场景都适合 Agent。用三维矩阵打分，优先做**高频高价值**的：

| 维度 | 评估标准 | 示例 |
|------|---------|------|
| 高频高价值 | 每天上百次、人工耗时长 | 客服工单分类、代码 Review |
| 高频低价值 | 频次高但单次价值低 | 格式转换、模板填充 |
| 低频高价值 | 偶发但影响大 | 安全审计、合同审查 |

**实操建议**：

- 先做 **2 周的人工流程录像/日志分析**，找出重复性最高的 3~5 个动作
- 用 **"如果 Agent 做错了，最坏结果是什么"** 来划定边界——后果不可接受的，必须 Human-in-the-loop
- MVP 阶段用 **Copilot 模式**（Agent 建议 + 人确认），不要一上来就全自动

### 1.2 边界定义模板

把 Agent 的能力边界写成可审计的配置，而不是散在代码里的隐式假设：

```yaml
agent_scope:
  name: "客服工单处理 Agent"
  can_do:
    - 工单分类和优先级判断
    - 标准问题自动回复（知识库匹配度 > 0.85）
    - 生成工单摘要
  cannot_do:
    - 退款操作（金额 > 100 元）
    - 修改用户账户信息
    - 承诺 SLA 时间
  escalation_rules:
    - condition: "用户情绪激动（情感分数 < -0.6）"
      action: "转人工 + 标记紧急"
    - condition: "知识库匹配度 < 0.7"
      action: "转人工 + 附上 Agent 初步分析"
```

---

## 2. 可靠性与安全性

### 2.1 幻觉控制：多层校验架构

单靠 Prompt 说"不要编造"是不够的。需要在架构层面堆叠多层防线：

```
用户输入 → Agent 推理 → 初步回答
                            │
                    [Layer 1] RAG 事实校验
                        → 从知识库检索，比对回答与源文档一致性
                            │
                    [Layer 2] 结构化输出约束
                        → JSON Schema / Pydantic 强制格式
                        → 关键字段必须有出处引用
                            │
                    [Layer 3] 规则引擎兜底
                        → 数字/日期/金额硬性校验
                        → 黑名单词汇过滤
                            │
                        最终输出
```

结构化输出的代码实现：

```python
from pydantic import BaseModel, Field

class AgentResponse(BaseModel):
    """强制 Agent 输出带引用的结构化回答"""
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[str] = Field(min_length=1, description="必须至少引用一个来源")
    needs_human_review: bool

    def should_escalate(self) -> bool:
        return self.confidence < 0.7 or self.needs_human_review
```

### 2.2 权限最小化：白名单 + 参数约束 + 审批流

Agent 能调用的工具必须严格收敛，不能给一把万能钥匙：

```python
TOOL_PERMISSIONS = {
    "query_database": {
        "allowed_tables": ["faq", "products"],       # 只能查这两张表
        "forbidden_operations": ["DELETE", "UPDATE"], # 禁止写操作
        "max_rows": 100,
        "require_approval": False,
    },
    "send_email": {
        "allowed_recipients": ["*@internal.com"],     # 只能发内部邮件
        "max_per_hour": 10,                           # 限流
        "require_approval": True,                     # 需要人工审批
    },
    "execute_refund": {
        "max_amount": 100,
        "require_approval": True,
        "approval_timeout": 300,                      # 5 分钟超时
    },
}
```

### 2.3 数据安全分层

```
┌──────────────────────────────────────────────────┐
│                数据安全分层架构                     │
├──────────────────────────────────────────────────┤
│                                                  │
│  [输入层] PII 脱敏网关                             │
│    → 手机号/身份证/银行卡 → 掩码替换                │
│    → 脱敏映射表本地存储，不发送给模型                │
│                                                  │
│  [传输层] 模型调用选择                              │
│    → 敏感场景 → 私有化部署模型                      │
│    → 非敏感场景 → API 调用（数据不留存协议）         │
│                                                  │
│  [存储层] 对话日志管理                              │
│    → 日志保留策略（30 天自动清理）                   │
│    → 审计日志与业务日志分离                          │
│                                                  │
│  [输出层] 输出内容审查                              │
│    → 防止模型输出泄露训练数据中的隐私                │
│    → 敏感词过滤 + 正则校验                          │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 2.4 异常兜底：每一步都有降级方案

```python
class AgentExecutor:
    async def run_with_fallback(self, task):
        try:
            result = await self.agent.execute(task, timeout=30)
            if result.confidence < self.threshold:
                return await self.fallback_to_human(task, result)
            return result
        except ToolCallError as e:
            logger.error(f"工具调用失败: {e}")
            return await self.retry_with_alternative_tool(task)
        except TokenLimitError:
            return await self.summarize_and_retry(task)
        except Exception as e:
            await self.alert_oncall(task, e)
            return FallbackResponse(
                message="当前无法处理您的请求，已转交人工处理",
                ticket_id=await self.create_ticket(task, e),
            )
```

---

## 3. 工程架构

### 3.1 Tool / Function Calling 设计

工具描述的质量直接决定 Agent 的行为准确度。好的工具定义 vs 差的工具定义：

```python
# ❌ 差：描述模糊，参数宽泛
bad_tool = {
    "name": "search",
    "description": "搜索东西",
    "parameters": {"query": {"type": "string"}}
}

# ✅ 好：描述精确，参数有约束和示例
good_tool = {
    "name": "search_product_catalog",
    "description": (
        "在产品目录中按名称或 SKU 搜索商品。返回匹配商品的名称、价格和库存状态。"
        "不支持模糊搜索，需要提供至少 3 个字符的关键词。"
    ),
    "parameters": {
        "keyword": {
            "type": "string",
            "minLength": 3,
            "description": "产品名称或 SKU 编号，如 'iPhone 15' 或 'SKU-20240101'",
        },
        "category": {
            "type": "string",
            "enum": ["electronics", "clothing", "food"],
        },
        "max_results": {
            "type": "integer",
            "default": 5,
            "maximum": 20,
        },
    },
}
```

**工具粒度原则**：

```
太粗：manage_order(action, ...) → 一个工具干所有事，模型容易选错参数
太细：get_order_id() → get_order_status() → get_order_items() → 调用链太长

合适：每个工具对应一个明确的业务意图
  - query_order(order_id)                  → 查询订单详情
  - cancel_order(order_id, reason)         → 取消订单
  - update_order_address(order_id, addr)   → 修改地址
```

### 3.2 上下文管理

长对话的 token 管理是 Agent 工程中最容易被低估的问题：

```
┌────────────────────────────────────────────────┐
│             上下文管理架构                        │
├────────────────────────────────────────────────┤
│                                                │
│  [System Prompt]  固定角色/规则/工具描述          │
│       ↕  尽量压缩，做 Prompt Caching             │
│                                                │
│  [长期记忆]  向量数据库（用户画像 / 历史摘要）     │
│       ↕  按相关性检索 top-k                      │
│                                                │
│  [短期记忆]  滑动窗口 + 摘要                      │
│       ↕  最近 N 轮保留原文                       │
│       ↕  更早轮次用 LLM 压缩成摘要               │
│                                                │
│  [工作记忆]  当前任务的中间状态                    │
│       ↕  结构化存储（dict / JSON）               │
│                                                │
│  [当前输入]  用户最新消息                         │
│                                                │
└────────────────────────────────────────────────┘
```

```python
class ContextManager:
    def __init__(self, max_tokens=8000):
        self.max_tokens = max_tokens

    def build_context(self, current_input, conversation_history, user_id):
        context_parts = []

        # 1. 长期记忆：从向量库检索
        relevant = self.vector_store.search(
            query=current_input, user_id=user_id, top_k=3
        )
        if relevant:
            context_parts.append(f"相关历史:\n{self.format_memories(relevant)}")

        # 2. 短期记忆：最近 3 轮保留原文，更早做摘要
        recent = conversation_history[-3:]
        older = conversation_history[:-3]
        if older:
            context_parts.append(f"对话摘要:\n{self.summarize(older)}")
        context_parts.extend(self.format_messages(recent))

        # 3. Token 预算检查：超限从最远的开始丢弃
        total = self.count_tokens(context_parts)
        while total > self.max_tokens and context_parts:
            context_parts.pop(0)
            total = self.count_tokens(context_parts)

        return context_parts
```

### 3.3 可观测性

> 配套代码：[`observability.py`](../src/learning_py/agent/observability.py) |
> [`otel_tracing.py`](../src/learning_py/agent/otel_tracing.py) |
> [`langsmith_tracing.py`](../src/learning_py/agent/langsmith_tracing.py)

可观测性是 Agent 工程化的**生命线**——不可观测的系统无法调试、无法优化、无法上线。

#### 全链路 Trace 的结构

Agent 的每次执行要能还原为一棵 Span 树：

```
用户请求
  │
  ├─ trace_id: "abc-123"
  │
  ├─ [Span 1] 意图识别     latency: 200ms  tokens: 150
  │     └─ model: haiku    result: "查询订单"
  │
  ├─ [Span 2] RAG 检索     latency: 80ms
  │     └─ hits: 3 docs    relevance: [0.92, 0.87, 0.71]
  │
  ├─ [Span 3] 工具调用      latency: 150ms
  │     └─ tool: query_order  params: {order_id: "ORD-001"}
  │
  ├─ [Span 4] 回答生成      latency: 800ms  tokens: 320
  │     └─ model: sonnet     confidence: 0.91
  │
  └─ 总耗时: 1230ms  总 tokens: 470  总成本: $0.003
```

#### 三层实现方案

本仓库实现了从轻量到重型的三层方案，可根据阶段选用：

**Layer 1：零依赖轻量级 Tracer**（[`observability.py`](../src/learning_py/agent/observability.py)）

适合 MVP 阶段，用标准库实现 Span 树、Metrics 聚合、终端可视化和 JSON 导出：

```bash
uv run python -m learning_py.agent.observability
```

输出效果：

```
──────────────────────────────────────────────────────────────────
  TRACE TIMELINE  │  trace_id: c1974ab7c5b5
──────────────────────────────────────────────────────────────────
  ├─ 🤖 ReActAgent.run  [340.8ms]
  │    task: 请告诉我 Python 是什么语言，并计算 (1+2+3)*4。
    │ ├─ 🧠 llm_call_step_0  [85.0ms]
    │ ├─ 🔧 tool_search  [0.0ms]
    │ ├─ 🧠 llm_call_step_1  [110.2ms]
    │ ├─ 🔧 tool_calc  [0.3ms]
    │ ├─ 🧠 llm_call_step_2  [140.7ms]
──────────────────────────────────────────────────────────────────
```

**Layer 2：OpenTelemetry 标准化导出**（[`otel_tracing.py`](../src/learning_py/agent/otel_tracing.py)）

适合生产阶段，将 Span 桥接到 OTel 格式，可接入 Jaeger / Tempo / Datadog 等后端。
遵循 GenAI 语义约定（`gen_ai.usage.input_tokens` 等）：

```bash
uv sync --extra otel
uv run python -m learning_py.agent.otel_tracing
```

关键设计——Span 桥接而非耦合：Agent 运行时只用轻量 Tracer，运行完毕后一次性导出到 OTel：

```python
from learning_py.agent.otel_tracing import export_to_otel, setup_otel_tracer_provider

provider = setup_otel_tracer_provider("my-service", use_console=True)
# ... 运行 Agent ...
export_to_otel(agent.tracer, model_name="deepseek-chat")
provider.force_flush()
```

**Layer 3：LangSmith 专业 LLM 调试平台**（[`langsmith_tracing.py`](../src/learning_py/agent/langsmith_tracing.py)）

适合开发调试阶段，提供 Web UI 可视化、A/B 对比、数据集评估等：

```bash
uv sync --extra langsmith-extra
# 在 python/.env 中配置：
#   LANGSMITH_TRACING=true
#   LANGSMITH_API_KEY=lsv2_pt_xxxxx
uv run python -m learning_py.agent.langsmith_tracing
```

关键设计——`@traceable` 分层标记，自动建立 chain → llm → tool 的嵌套关系：

```python
class LangSmithReActAgent:
    @traceable(run_type="chain", name="ReActAgent.run")
    def run(self, task): ...

    @traceable(run_type="llm", name="llm_call")
    def _llm_step(self, prompt, step): ...

    @traceable(run_type="tool", name="tool_call")
    def _tool_step(self, tool_name, arg, step): ...
```

#### 三层方案对比

| 维度 | 轻量级 Tracer | OpenTelemetry | LangSmith |
|------|-------------|---------------|-----------|
| **依赖** | 零（标准库） | opentelemetry-sdk | langsmith |
| **适用阶段** | MVP / 本地开发 | 生产监控 | 开发调试 |
| **可视化** | 终端 ASCII | Jaeger / Tempo / Datadog | 专属 Web UI |
| **Token 计数** | 粗估（字符数 / 4） | 手动设属性 | 自动（wrap_openai） |
| **成本追踪** | 内置定价表 | 需自建 | 内置 |
| **评估能力** | 无 | 无 | 数据集 + LLM-as-Judge |
| **生产开销** | 极低 | 低（BatchProcessor） | 低（异步上报） |

### 3.4 评估体系

上线不是终点，需要持续自动化评估：

```python
class AgentEvaluator:
    def __init__(self):
        self.test_cases = self.load_golden_dataset()  # 标注好的测试集

    def evaluate(self, agent):
        results = {
            "accuracy": [],        # 回答正确性（LLM-as-Judge）
            "tool_selection": [],   # 工具选择正确率（精确匹配）
            "latency": [],         # 延迟
            "cost": [],            # 成本
            "safety": [],          # 安全性（规则 + LLM 双重检查）
        }

        for case in self.test_cases:
            response = agent.run(case.input)
            results["accuracy"].append(
                self.llm_judge(case.expected_output, response.answer)
            )
            results["tool_selection"].append(
                case.expected_tools == response.tools_used
            )
            results["safety"].append(self.safety_check(response.answer))

        return self.generate_report(results)
```

**评估频率建议**：

| 触发条件 | 动作 |
|---------|------|
| 每次 Prompt 变更 | 跑全量回归测试集 |
| 每天 | 抽样 100 条线上真实请求做自动评估 |
| 每周 | 人工审核 Bad Case，补充到测试集 |

---

## 4. 成本控制

### 4.1 Token 消耗预估模型

Agent 的多步推理和重试会显著放大 token 用量，必须提前做成本模型：

```
单次 Agent 交互成本 = Σ (每步推理 token × 单价) + 重试成本

示例（以 Claude / DeepSeek 为例）：
┌──────────────────────────────────────────────────────────┐
│  步骤          输入 token  输出 token  模型     单步成本   │
├──────────────────────────────────────────────────────────┤
│  意图识别       500        50         Haiku    $0.0006   │
│  RAG 检索       -          -          (向量库)  -        │
│  推理+工具调用  2000       500        Sonnet   $0.0135   │
│  回答生成       3000       800        Sonnet   $0.0210   │
│  重试概率 15%   × 1.15                                   │
├──────────────────────────────────────────────────────────┤
│  单次预估：$0.01 ~ $0.04                                 │
│  日均 1 万次：$100 ~ $400 / 天                            │
└──────────────────────────────────────────────────────────┘
```

### 4.2 模型分层路由

不同复杂度的任务用不同级别的模型，不要一刀切：

```python
class ModelRouter:
    def select_model(self, task) -> str:
        # 简单分类 / 提取 → 小模型
        if task.type in ("classification", "extraction", "format"):
            return "claude-haiku-4-5"
        # 标准问答 / 工具调用 → 中等模型
        if task.type in ("qa", "tool_calling", "summarization"):
            return "claude-sonnet-4-6"
        # 复杂推理 / 多步规划 → 大模型
        if task.type in ("planning", "complex_reasoning", "code_generation"):
            return "claude-opus-4-6"
        return "claude-sonnet-4-6"
```

### 4.3 三级缓存架构

```
┌────────────────────────────────────────────────────┐
│                三级缓存架构                          │
├────────────────────────────────────────────────────┤
│                                                    │
│  L1: Prompt Cache（API 层）                         │
│    → System Prompt + 工具定义做 cache_control        │
│    → 省掉 90% 重复输入 token 的成本                  │
│                                                    │
│  L2: 语义缓存（应用层）                               │
│    → 用户问题做 embedding                            │
│    → 相似度 > 0.95 直接返回缓存答案                   │
│    → TTL：根据内容时效性设置                          │
│                                                    │
│  L3: 结果缓存（工具层）                               │
│    → 工具调用结果缓存（如数据库查询）                  │
│    → 相同参数 → 直接返回                             │
│    → TTL：5 ~ 60 分钟                               │
│                                                    │
└────────────────────────────────────────────────────┘
```

语义缓存的代码实现：

```python
class SemanticCache:
    def __init__(self, similarity_threshold=0.95, ttl=3600):
        self.threshold = similarity_threshold
        self.ttl = ttl

    async def get_or_compute(self, query, compute_fn):
        query_embedding = await self.embed(query)
        cached = self.vector_store.search(query_embedding, top_k=1)

        if cached and cached[0].score > self.threshold:
            if not self.is_expired(cached[0]):
                return cached[0].response  # 命中缓存

        result = await compute_fn(query)  # 未命中，调用模型
        self.vector_store.insert(query_embedding, result)
        return result
```

---

## 5. 用户体验

### 5.1 透明度：让用户看到 Agent 在做什么

黑盒等待是 Agent 产品最大的体验杀手。用户需要看到过程：

```
用户: "帮我查一下订单 ORD-001 的状态"

Agent 回复（带过程展示）:
┌──────────────────────────────────────┐
│  🔍 正在理解您的问题...               │
│  📋 调用【订单查询】工具               │
│     → 参数: order_id = ORD-001       │
│  ✅ 查询成功                          │
│                                      │
│  您的订单 ORD-001 状态如下：           │
│  - 当前状态：已发货                    │
│  - 快递单号：SF1234567890            │
│  - 预计到达：2024-03-15              │
│                                      │
│  📎 信息来源：订单系统（实时查询）       │
└──────────────────────────────────────┘
```

### 5.2 交互设计四原则

```yaml
ux_guidelines:
  # 1. 分步确认：高风险操作前必须确认
  confirmation:
    trigger: "涉及金钱 / 权限 / 数据修改"
    pattern: "我将执行以下操作：\n{操作描述}\n请确认是否继续？"

  # 2. 主动澄清：不确定时主动问，但最多追问 2 次
  clarification:
    trigger: "意图置信度 < 0.8 或存在歧义"
    pattern: "您是想 A 还是 B？"
    max_clarifications: 2

  # 3. 进度反馈：长任务要有中间状态
  progress:
    trigger: "预计耗时 > 5 秒"
    pattern: "正在处理中...（第 2/5 步：分析数据）"

  # 4. 优雅失败：出错时给替代方案，而不是"出错了请重试"
  error_recovery:
    pattern: |
      抱歉，我暂时无法完成{任务}。您可以：
      1. 稍后重试
      2. 联系人工客服
      3. 尝试{替代方案}
```

---

## 6. 组织与流程

### 6.1 Prompt 工程化管理

Prompt 不是随便写的字符串，是正式的工程制品——需要版本管理、Code Review、自动评估：

```
prompt-repo/
├── prompts/
│   ├── customer_service/
│   │   ├── v1.0.0/
│   │   │   ├── system.md          # System Prompt
│   │   │   ├── tools.json         # 工具定义
│   │   │   ├── few_shots.json     # Few-shot 示例
│   │   │   └── eval_results.json  # 该版本的评估结果
│   │   ├── v1.1.0/
│   │   └── CHANGELOG.md
│   └── code_review/
├── evals/
│   ├── golden_dataset.jsonl       # 标注测试集
│   └── run_eval.py                # 评估脚本
└── CI/
    └── prompt_review.yml          # PR 触发自动评估
```

CI 流水线——每次 Prompt 变更自动跑评估，指标下降超过 5% 自动 block PR：

```yaml
# .github/workflows/prompt_review.yml
on:
  pull_request:
    paths: ["prompts/**"]
jobs:
  eval:
    steps:
      - name: Run Eval Suite
        run: python evals/run_eval.py --prompt-version ${{ github.head_ref }}
      - name: Compare with Baseline
        run: python evals/compare.py --baseline main --candidate ${{ github.head_ref }}
```

### 6.2 Bad Case 闭环

线上出错不可怕，可怕的是出了错没人管、同样的错反复出：

```
线上请求
    │
    ▼
自动评估（LLM Judge）
    │
 分数 < 阈值？ ──否──→ 正常归档
    │
    是
    ▼
标记为 Bad Case → 进入 Review 队列
    │
    ▼
人工标注（每周）
  - 分类原因：幻觉 / 工具错误 / 理解偏差 / ...
  - 标注正确答案
    │
    ▼
添加到 Golden Dataset
    │
    ▼
触发 Prompt 优化迭代 → CI 回归测试 → 发布新版本
```

### 6.3 团队协作分工

| 角色 | 职责 | 产出物 |
|------|------|--------|
| 业务方 | 定义场景、验收标准、提供知识库 | 需求文档、FAQ 库 |
| Prompt 工程师 | System Prompt、Few-shot、工具设计 | Prompt 仓库、评估报告 |
| 后端工程师 | API 集成、工具实现、上下文管理 | Agent 服务、工具 SDK |
| 数据工程师 | RAG 流水线、知识库更新 | 向量库、ETL 流水线 |
| 安全团队 | 权限审计、数据合规、红队测试 | 安全报告、合规文档 |
| SRE / 运维 | 监控告警、成本监控、扩缩容 | Dashboard、Runbook |

---

## 7. 落地路线图

```
Phase 1（1~2 周）     Phase 2（2~4 周）      Phase 3（4~8 周）      Phase 4（持续）
  场景调研               MVP 开发               灰度上线               全量运营
  ┌──────┐             ┌──────┐              ┌──────┐              ┌──────┐
  │ 选场景 │     →      │ 搭架构 │      →     │ 灰度  │      →      │ 迭代  │
  │ 定边界 │            │ 写Prompt│           │ 10%流量│             │ 优化  │
  │ 评成本 │            │ 接工具  │            │ 收集数据│            │ 扩场景 │
  │ 选模型 │            │ 建 Eval │           │ 修 Bad │             │ 降成本 │
  └──────┘             └──────┘    Case      └──────┘              └──────┘
```

**最关键的一条**：先想清楚"没有 Agent 时这件事怎么做"，再思考"Agent 在哪个环节能提效"。
很多项目失败不是技术问题，而是场景选错了或者边界没定好。

---

## 8. 延伸阅读

本仓库中的相关文档和代码：

| 资源 | 路径 | 说明 |
|------|------|------|
| Agent 核心概念 | [`docs/ai-agent.md`](ai-agent.md) | Agent = LLM + 工具 + 记忆 + 循环 |
| 架构模式 | [`docs/agent-architectures.md`](agent-architectures.md) | ReAct / Plan-Execute / Reflection / Multi-Agent |
| 记忆系统 | [`docs/agent-memory.md`](agent-memory.md) | 短期 / 长期记忆实现 |
| 可观测性代码 | [`src/learning_py/agent/observability.py`](../src/learning_py/agent/observability.py) | 轻量级 Tracer + Metrics |
| OTel 集成 | [`src/learning_py/agent/otel_tracing.py`](../src/learning_py/agent/otel_tracing.py) | OpenTelemetry 桥接 |
| LangSmith 集成 | [`src/learning_py/agent/langsmith_tracing.py`](../src/learning_py/agent/langsmith_tracing.py) | @traceable + wrap_openai |
