# 技术点三：RAG 评测体系闭环 —— 面试复习

> 简历描述：搭建业务自建指标与 RAGAS 通用指标结合的评测体系，覆盖意图准确率、检索 Hit@K、生成忠实性、答案相关性和响应延迟等指标，经评测 Hit@5 ≥ 90%、Recall@5 ≥ 95%、Faithfulness ≥ 0.90、TTFT ≤ 6s

---

## 一、做什么

建立一套**可量化、可复现、可回归对比**的评测体系，覆盖 RAG 系统从意图识别到最终生成的每个环节。核心目标：用数据驱动质量优化，而不是靠"感觉回答还行"。

为什么要专门做评测？RAG 系统的痛点是**效果不可观测**——你不知道回答不好是因为检索没召回到、还是 LLM 没用好、还是意图判断错了。没有评测体系，优化就是盲人摸象。

---

## 二、怎么实现的（核心技术）

### 2.1 整体架构：Java + Python 解耦

采用 **Java 被评系统 + Python 评测客户端** 的解耦设计，分 5 个阶段：

```
┌─────────────────────────────────────────────────────────────┐
│                   Java 侧（被评系统）                        │
│                                                             │
│  /rag/v3/chat (SSE)  ← 完整对话管道，返回 LLM 生成的答案    │
│  /rag/eval   (JSON)  ← 旁路评测接口，只跑检索不跑生成        │
│                        返回：意图识别结果、检索到的文档/chunk、│
│                              MCP 上下文、耗时等中间态数据     │
└─────────────────────────────────────────────────────────────┘
                         ↑ HTTP
┌─────────────────────────────────────────────────────────────┐
│                  Python 侧（ragenteval）                     │
│                                                             │
│  Stage 1: init    → 生成知识库/意图树初始化蓝图               │
│  Stage 2: run     → 逐条读取评估集，双接口聚合，产出 JSONL    │
│  Stage 3: score   → 基于 JSONL 计算自建指标                  │
│  Stage 4: ragas   → 可选，调 RAGAS 跑 LLM-as-judge 语义指标  │
│  Stage 5: report  → 生成 Markdown 测评报告 + 回归对比         │
└─────────────────────────────────────────────────────────────┘
```

**核心设计理念**：Python 侧所有评分、报告都基于 `runs/*.jsonl` 文件，**不需要二次请求 Ragent 后端**，可以离线反复计算不同指标。

### 2.2 Java 侧：旁路评测接口 `/rag/eval`

核心类：`EvalController`、`EvalResponse`、`EvalProperties`。

`EvalController` 复用主管道的前半段（改写 → 意图识别 → 检索），但**跳过 LLM 生成**（最慢最贵的一步），只返回中间态数据：

```java
@GetMapping("/rag/eval")
public Result<EvalResponse> chat(@RequestParam String question) {
    RewriteResult rewriteResult = queryRewriteService.rewriteWithSplit(question, List.of());
    List<SubQuestionIntent> subIntents = intentResolver.resolve(rewriteResult);
    RetrievalContext rc = retrievalEngine.retrieve(subIntents, searchProperties.getDefaultTopK());
    return Results.success(buildResponse(rc, subIntents, latencyMs));
}
```

通过 `@ConditionalOnProperty(prefix = "app.eval", name = "enabled", havingValue = "true")` 控制开关，生产环境不暴露。

**EvalResponse 关键字段**：

| 字段 | 含义 | 评测用途 |
|---|---|---|
| `intentLeafIds` | 每个子问题 top-1 意图节点 ID | 与标注的 `intent_l2` 比对算 Top-1 准确率 |
| `retrievedDocIds` | 召回的业务文档 ID（去重） | 与标注的 `expected_doc_ids` 比对算 Hit@K / Recall@K |
| `retrievedChunkIds` | 召回的 chunk 主键列表 | 调试用 |
| `retrievedContexts` | 召回的 chunk 文本列表 | 送入 RAGAS 算 Faithfulness / Context Precision |
| `mcpContext` | MCP 工具调用结果文本 | MCP 场景评测 |
| `hasMcp` / `hasKb` | 是否走了 MCP / KB 分支 | 计算误拒率 / 过召回率 |
| `latencyMs` | 检索总耗时 | 性能指标 |

### 2.3 DocId 反查链路（对齐业务码和雪花 ID）

评估集使用人类可读的业务码（如 `FAQ_VAC_001`），而系统内部使用雪花 ID。`EvalController` 实现了一条反查链路对齐两者：

```
chunkId → t_knowledge_chunk.docId（雪花 ID）
       → t_knowledge_document.doc_name
       → 剥文件后缀 → 业务码
```

这是评测能跑起来的前提——否则标注和系统输出对不上。

### 2.4 评估集设计

JSONL 格式，一行一个样本，位于 `eval/rag/data/eval_set_v1.jsonl`。核心类：`EvalSample`（schema.py）。

**核心字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 样本唯一 ID |
| `query` | string | 用户原始问题 |
| `intent_l1` | string | 一级意图标注（DOMAIN 层） |
| `intent_l2` | string | 二级意图标注（叶子节点 ID，用于计算 intent_accuracy） |
| `difficulty` | string | 难度分级：easy / medium / hard |
| `requires_rag` | bool | 是否应走 RAG 检索（false 则为系统对话/越界提问） |
| `expected_doc_ids` | string[] | 必须召回的业务文档 ID |
| `expected_doc_ids_nice` | string[] | 召回更好但不强制的扩展文档 ID |
| `trap_type` | string | 陷阱类型（用于分层分析） |
| `ground_truth` | string | 参考答案（RAGAS 使用） |
| `eval_metrics` | string[] | 该用例需要计算的指标列表 |

**覆盖度要求**（约 150 条）：

| 分层 | 样本数 | 说明 |
|---|---|---|
| KB 单意图 | 60-80 | 每个叶子意图至少 3-5 条，覆盖不同表述 |
| KB 多意图 | 10-15 | 一个问题涉及多个知识库 |
| MCP 工具 | 15-20 | 每个工具 3-5 条，覆盖不同参数组合 |
| MCP + KB 混合 | 10 | 既要查数据又要查文档 |
| SYSTEM（系统对话） | 10 | 打招呼、自我介绍、越界提问 |
| 歧义场景 | 10 | 应触发歧义引导的问题 |
| 否定场景 | 10 | `requires_rag=false`，测误拒率/过召回率 |
| 复杂/多子问题 | 10-15 | 需要拆分子问题的复合问题 |

### 2.5 录制阶段（runner.py）

`runner.py` 逐条读取评估集，**同时调两个接口**聚合数据：

```python
def run_sample(sample, client, *, chat=True):
    eval_payload = client.get_eval(sample.query)      # /rag/eval → 检索证据链
    if chat:
        chat_result = client.get_chat(sample.query)   # /rag/v3/chat (SSE) → LLM 回答
```

聚合成 `EvalRecord`（标注 + 检索结果 + LLM 回答 + 耗时），写入 `runs/*.jsonl`。

支持并发（`--workers 4`）、按意图筛选（`--filter-intent`）、限制数量（`--limit`）。

### 2.6 双层指标体系

#### 自建指标（score 阶段，metrics.py）

**意图识别**：

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `intent_top1_accuracy` | `intent_pred == intent_l2` | ≥ 92% |

**检索召回**：

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `hit@3` | top-3 中是否命中任一 expected_doc_id | — |
| `hit@5` | top-5 中是否命中任一 expected_doc_id | ≥ 90% |
| `recall@3` | top-3 中命中的 expected_doc_id 比例 | — |
| `recall@5` | top-5 中命中的 expected_doc_id 比例 | ≥ 95% |
| `recall@5_inclusive` | 含 expected_doc_ids_nice 的 recall@5 | — |
| `mrr@10` | 第一个命中文档的倒数排名 | — |

**鲁棒性**：

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `false_reject_rate` | `requires_rag=true` 但没返回 KB 证据 | ≤ 3% |
| `over_retrieval_rate` | `requires_rag=false` 但返回了 KB 证据 | — |

**性能**：

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `avg_ttft_ms` | 首 Token 延迟均值 | ≤ 6000ms |
| `avg_chat_latency_ms` | 完整对话延迟均值 | — |
| `avg_eval_latency_ms` | 检索侧延迟均值 | — |

**分层分析**：按 `difficulty` / `intent_l1` / `intent_l2` / `trap_type` 四个维度分组，分别计算 `intent_top1_accuracy` 和 `hit@5`。

#### RAGAS 语义指标（ragas 阶段，ragas_eval.py）

需要 OpenAI 兼容 LLM 作为 judge，通过 `.env` 配置：

| 指标 | 评估维度 | 目标值 |
|---|---|---|
| `faithfulness` | 回答是否忠实于检索到的上下文（不幻觉） | ≥ 0.90 |
| `answer_relevancy` | 回答与问题的相关性 | ≥ 0.85 |
| `context_precision` | 检索到的上下文中有多少是相关的 | — |
| `context_recall` | 相关上下文被检索到的比例 | — |
| `answer_correctness` | 回答与参考答案的一致性 | — |

### 2.7 回归对比机制

每次评测产出 `runs/v1_xxx.jsonl` 作为基线快照，后续评测自动与上一轮对比：

```python
def compare_runs(baseline_file, current_file):
    # 加载两轮的 metrics
    # 逐指标计算 delta 和方向标记
    # 输出: intent_top1_accuracy: 0.8800 → 0.9200 (↑ 0.0400)
```

命令：
```bash
python -m eval rag compare \
    --baseline eval/rag/runs/v1_baseline.jsonl \
    --current eval/rag/runs/v1_latest.jsonl
```

### 2.8 完整评测流水线

```bash
# Phase 1: 准备（开启评测开关启动后端）
APP_EVAL_ENABLED=true ./mvnw -pl bootstrap -am spring-boot:run

# Phase 2: 录制
python -m eval rag run --limit 150
# 产出：eval/rag/runs/v1_20260726T143000.jsonl

# Phase 3: 自建指标评分
python -m eval rag score --run-file eval/rag/runs/v1_xxx.jsonl

# Phase 4: RAGAS 语义指标（可选）
python -m eval rag ragas --run-file eval/rag/runs/v1_xxx.jsonl

# Phase 5: 报告 + 回归对比
python -m eval rag report --run-file eval/rag/runs/v1_xxx.jsonl
python -m eval rag compare --baseline ... --current ...
```

---

## 三、为什么这样做

### 为什么把评测系统做成 Java + Python 解耦？

评测的核心诉求是"可复现、可离线反复计算"。如果评分逻辑嵌在 Java 主应用里，每次调整指标算法都要重新跑一遍后端接口，非常浪费。解耦后，录制阶段产出的 JSONL 文件就是"快照"，Python 侧可以离线反复用不同指标、不同参数计算，不需要重新请求后端。同时 RAGAS 等学术界评测工具的生态在 Python 侧更成熟。

### 为什么做旁路接口而不是直接用对话接口？

对话接口只返回最终 LLM 回答，看不到中间过程（意图识别了什么、检索到了哪些文档、走了 KB 还是 MCP）。旁路接口跳过 LLM 生成（最慢最贵的一步），只暴露中间态数据，让检索链路的评测独立于生成质量。两个接口分别评测检索和生成，问题定位更精准——是检索没召回到，还是检索到了但 LLM 没用好。

### 为什么自建指标 + RAGAS 两套并行？

自建指标（intent_accuracy、hit@K、recall@K）是**确定性的**，计算快、可靠、不依赖外部 LLM，但只能衡量"检索到了没有"，无法衡量"生成的回答好不好"。RAGAS 的 faithfulness、answer_relevancy 是**语义级**的 LLM-as-judge 评估，能衡量生成质量，但依赖外部 LLM、有成本、有不确定性。两套互补：自建指标做日常快速验证（秒级出结果），RAGAS 做阶段性深度评测。

### 为什么要分层分析？

一个 92% 的整体准确率可能掩盖了"easy 题 100%、hard 题 60%"的问题。按 difficulty / intent / trap_type 分层后，能精准定位薄弱环节：是某个特定意图的分类总出错，还是某类陷阱题（如多义词、否定表述）系统性处理不好。没有分层分析，优化就是盲目调参。

### 为什么要回归对比机制？

RAG 系统的优化是迭代式的——调一个 Prompt、改一个阈值，可能让某个指标提升但另一个回归。没有回归对比，改完不知道是好是坏，甚至悄悄引入回归。每次评测的 JSONL 作为基线快照，后续评测自动对比 delta，一眼看出哪些进步了、哪些回归了，让每次改动都有数据支撑。

---

## 四、遇到的困难与解决方案

### 困难 1：业务文档 ID 和系统内部 ID 对不上

**问题**：评估集用人类可读的业务码（如 `FAQ_VAC_001`）标注，而系统内部检索返回的是雪花 ID。两者对不上，无法计算 hit@K 和 recall@K——这是评测体系跑起来的前提。

**分析**：系统内部从向量库检索回来的是 chunkId（雪花 ID），而评估集标注的是文档级别的业务码。需要一条反查链路把两者对齐。

**解决方案**：在 `EvalController` 实现了一条 **DocId 反查链路**：
```
chunkId → t_knowledge_chunk.docId（雪花 ID）
       → t_knowledge_document.doc_name
       → 剥文件后缀 → 业务码
```
- chunk 表存 `docId`（雪花 ID），关联到文档表
- 文档表的 `doc_name` 带文件后缀（如 `FAQ_VAC_001.pdf`），剥掉后缀得到业务码
- `EvalResponse` 的 `retrievedDocIds` 字段直接返回业务码，和评估集标注同维度

**效果**：标注和系统输出在文档级别对齐，hit@K 和 recall@K 可计算。

### 困难 2：单一指标 hit@5 掩盖了多文档漏召回

**问题**：早期只看 `hit@5`，整体 90% 觉得不错。但后来发现很多需要召回多个文档的问题，用户反馈"回答不全"。

**分析**：`hit@5` 的定义是"top-5 中是否命中**任一**期望文档"，只要命中一个就算对。一个问题需要召回 3 个文档，系统只召回了 1 个，`hit@5` 仍然记 1.0（100%），完全掩盖了漏召回 2 个文档的问题。

**解决方案**：增加 `recall@5`（命中比例）指标：
```python
def recall_at_k(records, k):
    def score(record):
        refs = set(record.reference_doc_ids)
        return len(refs.intersection(record.retrieved_doc_ids[:k])) / len(refs)
```
同时增加 `recall@5_inclusive`（含 nice-to-have 文档的宽松版）和 `mrr@10`（排名质量），形成多维度指标矩阵。`recall@5` 暴露了多文档场景的漏召回问题（实际只有 80%），后续通过全局检索兜底 + 多通道互补优化到 95%+。

**效果**：多文档场景召回率从 ~80% 提升到 95%+，因为有了 recall@K 指标暴露问题。

### 困难 3：RAGAS 评分和人类判断不一致

**问题**：RAGAS 的 faithfulness 有时给了高分（0.95），但人工检查发现回答虽然"忠实于上下文"但上下文本身就是错的（检索到了错误文档，LLM 忠实地基于错误上下文生成了错误回答）。

**分析**：这揭示了 faithfulness 指标的本质局限——它只能评估"生成环节有没有幻觉"（回答是否忠实于给定上下文），**不能评估"检索环节有没有拿对"**（上下文本身对不对）。faithfulness 高不代表整体回答对。

**解决方案**：明确指标的分层责任：
- **检索质量**用自建指标（hit@K、recall@K）衡量——检索到的是不是对的文档
- **生成质量**用 RAGAS（faithfulness、answer_relevancy）衡量——基于检索结果生成得好不好
- 两者结合才能定位完整链路问题：faithfulness 高但 hit@K 低 → 检索有问题；faithfulness 低但 hit@K 高 → 生成有问题

**效果**：评测结论更准确，不再被单一指标误导。

### 困难 4：评测指标量纲陷阱 —— 只看准确率忽略难度分布

**问题**：整体准确率 92%，但某些 hard 题只有 60%，被 easy 题的 98% 拉高了。调整优化策略时不知道该针对哪类题。

**分析**：没有分层分析的话，整体数字掩盖了薄弱环节，优化方向不明确。

**解决方案**：实现 `slice_metrics()` 分层分析，按 4 个维度分组：
```python
for field in ("difficulty", "intent_l1", "intent_l2", "trap_type"):
    groups = defaultdict(list)
    for record in records:
        groups[getattr(record, field) or "UNKNOWN"].append(record)
    # 每组分别算 intent_top1_accuracy 和 hit@5
```
发现 hard 题准确率 60% 后，针对性查看 hard 题的 LLM reason，发现是某些意图的 examples 不够，补充后 hard 题准确率提升到 80%+。

**效果**：优化从"盲目调参"变成"精准定位薄弱环节"。

### 困难 5：评估集从 2 条到 150 条的覆盖度建设

**问题**：最初评估集只有 2 条样例，所有指标无统计意义，评测体系形同虚设。

**分析**：评估集是评测的地基——没有足够样本，指标数字都是噪音。需要系统性地设计覆盖所有路径的评估集。

**解决方案**：按 8 个分层维度设计评估集（KB 单/多意图、MCP 工具、混合、SYSTEM、歧义、否定、复杂多子问题），总计约 150 条。每个叶子意图至少 3-5 条不同表述的样本，覆盖各种问法变体。同时设计陷阱类型（trap_type）标签，用于分析特定失败模式（如多义词、否定表述、越界提问）。

**效果**：评估集达到 150+ 条后，所有指标具备统计意义，优化有据可依。

---

## 五、量化指标与优化过程

| 指标 | 目标值 | 实际达成 | 优化手段 |
|---|---|---|---|
| `intent_top1_accuracy` | ≥ 92% | 92%+ | examples + fullPath + 低温度参数（详见技术点一） |
| `hit@5` | ≥ 90% | 90%+ | RRF 融合 + 多通道互补（详见技术点二） |
| `recall@5` | ≥ 95% | 95%+ | 全局检索兜底 + recall@K 指标暴露漏召回 |
| `faithfulness` | ≥ 0.90 | 0.90+ | KB 场景 temperature=0 + 证据约束 Prompt |
| `false_reject_rate` | ≤ 3% | <3% | 全局检索兜底 + 空结果短路提示 |
| `avg_ttft_ms` | ≤ 6000ms | <6000ms | 候选池截断 + 并行检索 + Redis 缓存 |

### 关键优化案例：faithfulness 从 0.82 到 0.90

- **问题**：早期 faithfulness 只有 0.82，LLM 偶尔会"脑补"检索上下文中没有的信息
- **分析**：通过 RAGAS 的 context_precision 发现检索上下文里有大量不相关 chunk，干扰了 LLM
- **优化 1**：强化 KB 场景的 `answer-chat-kb.st` Prompt，明确要求"只基于下方相关文档回答，不要添加文档中没有的信息"
- **优化 2**：KB 场景 `temperature=0`，进一步减少随机性
- **优化 3**：通过 Rerank 精排提升 context_precision，减少不相关 chunk 进入 Prompt
- **效果**：faithfulness 提升到 0.90+，同时 context_precision 也有提升

---

## 六、面试高频问题

### Q1：为什么评测要拆成两个接口（/rag/eval 和 /rag/v3/chat），不麻烦吗？

> "不麻烦，这是刻意设计。两个接口分别评测检索和生成，问题定位更精准。对话接口只返回最终回答，看不到中间过程——意图识别了什么、检索到了哪些文档、走了 KB 还是 MCP，全都看不到。旁路接口复用主管道前半段但跳过 LLM 生成（最慢最贵的一步），只暴露中间态数据。这样我能单独看'检索到对不对'，不被生成质量干扰；也能单独看'生成好不好'。如果检索没召回到正确文档，但 LLM 瞎编了一个看似合理的答案，只看最终答案是发现不了的——但拆开后，hit@K 低 + faithfulness 高，就能定位到是检索环节的问题。"

### Q2：RAGAS 的 faithfulness 你怎么理解？它有什么局限？

> "faithfulness 衡量的是'回答是否忠实于检索到的上下文'，本质是防幻觉——回答里的每个论断是否都能在上下文中找到依据。它的局限是**只管生成环节，不管检索环节**。如果检索到了错误文档，LLM 忠实地基于错误上下文生成了错误回答，faithfulness 依然会给高分——因为它确实'忠实于上下文'了，只是上下文本身错了。所以我用自建指标（hit@K、recall@K）衡量检索对不对，用 RAGAS（faithfulness）衡量生成好不好，两者结合才能评估完整链路。这也是为什么评测要分层——单一指标会误导。"

### Q3：评估集只有 150 条够吗？怎么保证统计显著性？

> "150 条对于企业内部场景是够用的，因为意图节点数量有限（几十到一两百个），每个意图 3-5 条样本能覆盖主要问法变体。但确实不是越多越好——评估集的质量比数量重要：一是标注准确性，ground_truth 和 expected_doc_ids 必须人工严格核对；二是覆盖度，要覆盖所有路径（KB/MCP/SYSTEM/歧义/否定）；三是难度分布，easy/medium/hard 都要有。150 条里如果 80% 是 easy 题，整体准确率会虚高。我们通过分层分析（slice_metrics）来对冲这个问题——即使整体 92%，也能看到 hard 题单独的准确率。未来如果意图节点大幅增长，评估集也要同步扩充。"

### Q4：你怎么用这套评测体系指导优化的？举个具体例子。

> "举意图分类的例子。最初整体准确率 80%，我跑分层分析发现集中在两类问题上：一是相似意图混淆（'技术支持' vs '系统介绍'），二是 hard 题（多义词、否定表述）。针对第一类，我给每个意图节点增加了 examples 字段（3-5 个示例问法）和 fullPath（完整路径提供层次上下文），让 LLM 有更具体的参考。针对第二类，我在 intent-classifier.st 的 Prompt 里增加了'注意区分名称相似但属于不同业务域的意图'的引导。改完再跑评测，整体提升到 92%，且通过回归对比确认 hard 题从 60% 提升到 80%，没有引入其他回归。整个流程是：评测发现薄弱环节 → 针对性优化 → 再评测验证 → 回归对比确认。"

### Q5：回归对比机制具体怎么用的？

> "每次评测产出 JSONL 快照存到 runs/ 目录。下次改完代码或 Prompt 后再跑一次评测，用 compare 命令对比两轮的 JSONL。它会逐指标计算 delta 和方向标记——比如 'hit@5: 0.88 → 0.90 (↑ 0.02)' 表示进步了，'faithfulness: 0.90 → 0.86 (↓ 0.04)' 表示回归了。最怕的就是悄悄引入回归——改了 Prompt 提升了意图准确率，但 faithfulness 掉了，没有回归对比根本发现不了。有了这个机制，每次改动都有数据支撑，敢改也敢回滚。"

### Q6：自建指标的 hit@K 和 recall@K 有什么区别？为什么要分开看？

> "hit@K 是'top-K 中是否命中任一期望文档'，二元判断，命中一个就算对；recall@K 是'期望文档被召回的比例'，关注命中率。区别在于多文档场景：一个问题需要召回 3 个文档，系统只召回 1 个，hit@5 仍然是 100%（命中了一个），但 recall@5 只有 33%。只看 hit@K 会掩盖漏召回。我早期就吃过这个亏——hit@5 看着不错（90%），但用户反馈'回答不全'，加了 recall@5 才发现多文档场景召回率只有 80%。所以两者都要看：hit@K 管'有没有命中'，recall@K 管'命中得全不全'。"

### Q7：评测体系怎么集成到 CI/CD？每次提交都跑吗？

> "目前是半自动的——每次有较大改动后手动跑一次完整评测，用回归对比看影响。全量集成到 CI 每次 PR 都跑，成本太高（150 条 × 几秒 = 几分钟，还要调 LLM），而且 RAGAS 阶段依赖外部 LLM、不稳定。更合理的做法是分级：单元测试和冒烟测试（10 条核心用例）每次 PR 跑，保证不回归；完整评测（150 条 + RAGAS）在迭代节点跑。这也是为什么评测做成离线 JSONL 快照——录制和评分解耦，可以先快速录制一小批验证，再离线跑全量评分，灵活控制成本。"
