# Agent 架构模式

> 配套代码：[`src/learning_py/agent/`](../src/learning_py/agent/)
>
> 把"Agent 怎么搭"这一层从"模型怎么思考"里剥出来：本文聚焦的是**控制流**——
> 谁先调谁、状态怎么传、什么时候停。

---

## 0. 先建立坐标系

学习这 4 种架构前，先记住一组对照变量：

| 维度 | 含义 |
| --- | --- |
| **思考粒度** | 一次 LLM 调用涉及多少决策 |
| **LLM 调用次数** | 直接决定成本和延迟 |
| **可控性 / 可审计性** | 中间结果是否可被人审核、缓存 |
| **遇到意外的适应力** | 计划赶不上变化时能否调整方向 |
| **角色分工** | 是一个模型扛全部，还是多个角色配合 |

带着这 5 个维度去看下面 4 种架构，差异立刻清晰。

---

## 1. ReAct（Reasoning + Acting）

**核心思想**：模型每一步都同时输出**一个想法 + 一个动作**，框架执行动作、把
观察结果喂回去，循环直到模型输出 `FINAL`。

**LLM 输出格式**：
```
THOUGHT: ...                  # 想法
ACTION: tool_name(arg)        # 或者
FINAL: ...                    # 最终答案
```

**执行循环**：
```
loop:
    output = LLM(task + history)
    if FINAL in output: break
    obs = run_tool(parse(output))
    history += output + obs
```

**优点**：
- 控制流极简，**对意外极其鲁棒**：一步走错了下一步还能纠正。
- 任何能"想-做-看"的任务都能套，最像通用 Agent。

**缺点**：
- LLM 调用次数 = 步数，**贵且慢**。
- 长任务里 history 越滚越大，容易触上下文上限。

**典型代表**：原始 ReAct 论文、LangChain `AgentExecutor`、Cursor / Claude Code 的核心循环。

**代码**：[`react_agent.py`](../src/learning_py/agent/react_agent.py)
**单跑**：`uv run python -m learning_py.agent.demo react`

---

## 2. Plan-and-Execute（先计划，后执行）

**核心思想**：把"思考"和"执行"分成两个阶段。
**Planner** 一次 LLM 调用就把整张计划列出来；**Executor** 只是机械地按计划调工具，**不再调用 LLM**。

**两阶段流水线**：
```
plan = LLM("把任务拆成步骤")    # 只调一次
for step in plan:
    run_tool(step)              # 不调 LLM
```

**优点**：
- **LLM 调用次数最少**，成本和延迟最低。
- **计划可被人工审核 / 缓存 / 重放**——非常适合数据流水线、ETL 类场景。
- 每一步独立，天然可并行。

**缺点**：
- **遇到意外不会自己改方向**——除非加 Re-Plan 机制（执行一段时间后回头让 LLM 重审计划）。
- Planner 一次性想清楚很难，复杂任务的初版计划往往不靠谱。

**典型代表**：LangChain `PlanAndExecute`、BabyAGI、企业里把 LLM 用作"自然语言转 SOP"的方案。

**代码**：[`plan_and_execute.py`](../src/learning_py/agent/plan_and_execute.py)
**单跑**：`uv run python -m learning_py.agent.demo plan`

---

## 3. Reflection（自我反思）

**核心思想**：**生成 → 自我批改 → 重写**，循环直到满意或达上限。
是把上一篇 `prompt-engineering.md` 里讲过的 Self-Reflection 提到 Agent 层面。

**循环**：
```
draft = LLM.draft(task)
for _ in range(max_rounds):
    feedback = LLM.reflect(draft)
    if "OK" in feedback: break
    draft = LLM.draft(task, feedback)
```

**优点**：
- 对**写作 / 代码 / 翻译**这类"一次写不到位但每轮能改进"的任务效果显著。
- 不需要工具，纯 LLM 自洽。

**缺点**：
- LLM 调用次数 ≈ 2 × 轮数，成本翻倍。
- "自己写自己批"容易护短——这就是 Multi-Agent 出现的动机。
- 简单任务里**反思反而把对的改错**，要谨慎使用。

**典型代表**：Self-Refine、Reflexion 论文，以及绝大多数 Coding Agent 跑测试不通过后的"自动修复"循环。

**代码**：[`reflection_agent.py`](../src/learning_py/agent/reflection_agent.py)
**单跑**：`uv run python -m learning_py.agent.demo reflection`

---

## 4. Multi-Agent（多智能体协作）

**核心思想**：把任务分给**多个角色化 Agent**，各司其职，由 Coordinator 调度。
本质是 **Reflection 的多模型版**：让"写"和"批"是不同的 Agent，避免自我洗脑。

**经典三角色**：
```
Researcher（资料员）→  Writer（写作者）→  Critic（评审）
                          ↑                ↓
                          └──── 不通过则回写 ────┘
```

**调度伪码**：
```
research = Researcher.run(topic)
loop:
    article = Writer.run(topic, research, last_feedback)
    feedback = Critic.run(article)
    if APPROVE in feedback: break
```

**优点**：
- **角色分工 → 关注点分离**，每个 Agent 的 Prompt 都更短更专注。
- 可以让不同 Agent 用**不同模型**（Critic 用便宜模型、Writer 用强模型）。
- 天然可并行（多个 Researcher 同时搜不同方向）。

**缺点**：
- 协调开销大，调用次数最多。
- 角色之间的**消息协议**容易失控，多 Agent "聊飞了"是常见踩坑。
- 调试比单 Agent 难得多，问题复现成本高。

**典型代表**：AutoGen、CrewAI、MetaGPT；以及 Devin 这类把"PM / Coder / Tester"分开的产品。

**代码**：[`multi_agent.py`](../src/learning_py/agent/multi_agent.py)
**单跑**：`uv run python -m learning_py.agent.demo multi`

---

## 5. 横向对比

| 架构 | LLM 调用次数 | 适应意外 | 可审计性 | 角色 | 适合场景 |
| --- | --- | --- | --- | --- | --- |
| **ReAct** | 高（每步 1 次） | ★★★★★ | ★★★ | 单 | 通用 Agent、需要工具调用的对话 |
| **Plan-and-Execute** | **极低（≈1 次）** | ★ | ★★★★★ | 单 | SOP / 数据流水线 / 可预定义的任务 |
| **Reflection** | 中（2× 轮数） | ★★ | ★★ | 单 | 写作、代码生成、翻译 |
| **Multi-Agent** | 高 | ★★★★ | ★★★★ | 多 | 复杂协作、跨领域、产品级 Agent |

> 跑一次 `uv run python -m learning_py.agent.demo` 对比同一任务在 4 种架构下的轨迹，
> 直观感受 ReAct 多步循环 vs Plan-and-Execute 一次出计划的差距。

---

## 6. 选型口诀

- **任务能预先列出步骤** → Plan-and-Execute
- **任务需要边走边看** → ReAct
- **任务输出本身需要打磨** → Reflection
- **任务大到一个 Agent 装不下** → Multi-Agent
- **不知道选哪个** → 先用 ReAct 跑通，再针对性优化

---

## 7. 实战中的常见组合

架构不是互斥的，真实系统经常混用：

- **ReAct 内嵌 Reflection**：每步 ACTION 后让 Critic 检查一次再继续。
- **Plan-and-Execute + Re-Plan**：执行 N 步后回头让 Planner 重审，兼顾稳定与灵活。
- **Multi-Agent 内每个角色用 ReAct**：写作 Agent 自己也会查资料、调工具。
- **Hierarchical**：最外层一个 Coordinator Multi-Agent，里面每个 Worker 用 Plan-and-Execute。

---

## 8. 怎么跑

### 8.1 准备 LLM 配置

仓库**只通过 OpenAI 协议接真实 LLM**（DeepSeek / OpenAI / 月之暗面 / 智谱 / 自建 vLLM 网关都行），
没有内置任何模拟实现——这是有意的取舍：让你看到真实模型的真实输出。

```bash
cd python
cp .env.example .env
# 编辑 .env，填入你的 LLM 配置
```

`.env` 字段（已被 `.gitignore` 排除，不会误提交）：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=deepseek-chat
# 可选：覆盖默认采样参数
# LLM_TEMPERATURE=0.2
# LLM_MAX_TOKENS=1024
```

### 8.2 安装依赖

```bash
cd python
uv sync   # 自动装 openai + python-dotenv 等
```

### 8.3 跑 Demo

```bash
cd python

# 跑全部 4 种架构
uv run python -m learning_py.agent.demo

# 单跑某一种
uv run python -m learning_py.agent.demo react
uv run python -m learning_py.agent.demo plan
uv run python -m learning_py.agent.demo reflection
uv run python -m learning_py.agent.demo multi

# 任意组合
uv run python -m learning_py.agent.demo react plan

# 出错时打印 traceback
uv run python -m learning_py.agent.demo --debug react
```

> 注意：每次跑都会真实调用 LLM，**会产生费用**（4 个 demo 全跑约几千 token，几分钱量级）。

### 8.4 跑测试

```bash
cd python
uv run pytest tests/test_agent_architectures.py -q
```

测试只覆盖**与 LLM 无关的纯逻辑**——工具实现、ACTION / FINAL / PLAN 输出解析器。
端到端 Agent 行为依赖真实 LLM，由 demo 脚本人工验证。

### 8.5 关键设计：LLM 是可替换零件

[`llm_client.py`](../src/learning_py/agent/llm_client.py) 里的 `OpenAICompatLLM` 暴露的接口很简单：

```python
class OpenAICompatLLM:
    def complete(self, prompt: str) -> str: ...
    call_count: int
```

4 种架构（`ReActAgent` / `PlanAndExecuteAgent` / `ReflectionAgent` / `MultiAgentSystem`）
通过 `Protocol` 类型签名只依赖这两个成员。要换成别的厂商 SDK、或为单测做 mock，
**只要写一个同样有 `complete` 方法的类**，把它传给构造函数即可。

这正是「Agent 架构是壳，LLM 是可替换零件」的最直接落地。

---

## 9. 配套阅读

- [`ai-agent.md`](./ai-agent.md) — Agent 的四大核心能力（感知/推理/决策/执行），是本文的上游概念
- [`prompt-engineering.md`](./prompt-engineering.md) — Agent 内每一步使用的 Prompt 技巧
