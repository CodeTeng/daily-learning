# RAG 评测体系设计文档

> 本文档描述 KnowFlow RAG 系统的效果评测体系架构、已有实现、缺失部分及补全方案。

---

## 1. 评测体系总体架构

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
│  Stage 5: report  → 生成 Markdown 测评报告                   │
└─────────────────────────────────────────────────────────────┘
```

设计解耦的核心好处：Python 侧所有评分、报告都基于 `runs/*.jsonl` 文件，**不需要二次请求 Ragent 后端**，可以离线反复计算不同指标。

---

## 2. Java 侧旁路接口

### 2.1 `/rag/eval` 接口

`EvalController` 复用主管道的前半段（改写 → 意图识别 → 检索），但**跳过 LLM 生成**，只返回中间态数据：

```java
@GetMapping("/rag/eval")
public Result<EvalResponse> chat(@RequestParam String question) {
    RewriteResult rewriteResult = queryRewriteService.rewriteWithSplit(question, List.of());
    List<SubQuestionIntent> subIntents = intentResolver.resolve(rewriteResult);
    RetrievalContext rc = retrievalEngine.retrieve(subIntents, searchProperties.getDefaultTopK());
    return Results.success(buildResponse(rc, subIntents, latencyMs));
}
```

接口通过 `@ConditionalOnProperty(prefix = "app.eval", name = "enabled", havingValue = "true")` 控制开关，生产环境不暴露。

### 2.2 EvalResponse 字段说明

| 字段 | 含义 | 评测用途 |
|---|---|---|
| `intentLeafIds` | 每个子问题 top-1 意图节点 ID | 与标注的 `intent_l2` 比对算 Top-1 准确率 |
| `retrievedDocIds` | 召回的业务文档 ID（去重） | 与标注的 `expected_doc_ids` 比对算 Hit@K / Recall@K |
| `retrievedChunkIds` | 召回的 chunk 主键列表 | 调试用 |
| `retrievedContexts` | 召回的 chunk 文本列表 | 送入 RAGAS 算 Faithfulness / Context Precision |
| `retrievedContextDocIds` | 每个 chunk 对应的业务文档 ID | 计算 chunk 级指标 |
| `mcpContext` | MCP 工具调用结果文本 | MCP 场景评测 |
| `hasMcp` / `hasKb` | 是否走了 MCP / KB 分支 | 计算误拒率 / 过召回率 |
| `subIntents` | 子问题列表 | 改写评测 |
| `latencyMs` | 检索总耗时 | 性能指标 |

### 2.3 DocId 反查链路

评测集使用业务码（如 `FAQ_VAC_001`），而系统内部使用雪花 ID。`EvalController` 实现了一条反查链路对齐两者：

```
chunkId → t_knowledge_chunk.docId（雪花 ID）
       → t_knowledge_document.doc_name
       → 剥文件后缀 → 业务码
```

---

## 3. 评估集设计

### 3.1 格式

评估集为 JSONL，一行一个样本，位于 `eval/rag/data/eval_set_v1.jsonl`。

### 3.2 核心字段

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

### 3.3 示例

```json
{
  "id": "S1-01",
  "query": "预算 3000 元左右，想买一台拍照还不错的手机，推荐哪款？",
  "intent_l1": "SUPPORT",
  "intent_l2": "S1_选购推荐",
  "difficulty": "medium",
  "requires_rag": true,
  "expected_doc_ids": ["GUIDE_PHONE_002", "GUIDE_PHONE_003"],
  "expected_doc_ids_nice": ["PROD_PHONE_006"],
  "trap_type": "budget_scene",
  "ground_truth": "3000 元内可优先推荐 Redmi K70，并说明拍照、性能和价格优势。",
  "eval_metrics": ["intent_accuracy", "hit@5", "recall@5"]
}
```

### 3.4 覆盖度要求

评估集需覆盖系统所有路径，建议按以下维度分层设计：

| 分层 | 样本数建议 | 说明 |
|---|---|---|
| KB 单意图 | 60-80 条 | 每个叶子意图至少 3-5 条，覆盖不同表述 |
| KB 多意图 | 10-15 条 | 一个问题涉及多个知识库 |
| MCP 工具 | 15-20 条 | 每个工具 3-5 条，覆盖不同参数组合 |
| MCP + KB 混合 | 10 条 | 既要查数据又要查文档 |
| SYSTEM（系统对话） | 10 条 | 打招呼、自我介绍、越界提问 |
| 歧义场景 | 10 条 | 应触发歧义引导的问题 |
| 否定场景 | 10 条 | `requires_rag=false`，用于测误拒率/过召回率 |
| 复杂/多子问题 | 10-15 条 | 需要拆分子问题的复合问题 |
| **总计** | **约 150 条** | |

### 3.5 MCP 场景扩展字段

MCP 评测需要在评估集中额外标注：

```json
{
  "id": "MCP-01",
  "query": "华东地区本季度销售排名前5",
  "intent_l2": "MCP_销售数据",
  "requires_rag": false,
  "expected_mcp_tool": "sales_query",
  "expected_mcp_params": {
    "region": "华东",
    "period": "本季度",
    "queryType": "ranking",
    "limit": 5
  },
  "ground_truth": "应返回华东地区本季度销售排名前5的结果"
}
```

### 3.6 歧义场景扩展字段

```json
{
  "id": "AMB-01",
  "query": "数据安全相关规定有哪些？",
  "intent_l2": null,
  "requires_guidance": true,
  "ambiguous_intents": ["OA_数据安全", "保险_数据安全"],
  "ground_truth": "应引导用户明确是 OA 系统还是保险系统的数据安全"
}
```

---

## 4. 录制阶段（Runner）

### 4.1 工作流程

`runner.py` 逐条读取评估集，**同时调两个接口**聚合数据：

```python
def run_sample(sample, client, *, chat=True):
    eval_payload = client.get_eval(sample.query)      # /rag/eval → 检索证据链
    if chat:
        chat_result = client.get_chat(sample.query)    # /rag/v3/chat (SSE) → LLM 回答
```

聚合成 `EvalRecord`（标注 + 检索结果 + LLM 回答 + 耗时），写入 `runs/*.jsonl`。

### 4.2 EvalRecord 数据结构

`EvalRecord` 是评测体系的核心数据结构，分为三部分：

| 来源 | 字段 | 说明 |
|---|---|---|
| 评估集（静态标注） | `id`, `query`, `intent_l1`, `intent_l2`, `difficulty`, `requires_rag`, `reference_doc_ids`, `reference_doc_ids_nice`, `trap_type`, `ground_truth`, `eval_metrics` | 人工标注的 ground truth |
| `/rag/v3/chat`（动态） | `answer`, `ttft_ms`, `chat_latency_ms` | LLM 生成的回答和性能数据 |
| `/rag/eval`（动态） | `retrieved_doc_ids`, `retrieved_chunk_ids`, `retrieved_contexts`, `retrieved_context_doc_ids`, `mcp_context`, `has_mcp`, `has_kb`, `sub_intents`, `intent_leaf_ids`, `intent_pred`, `eval_latency_ms` | 检索中间态数据 |

### 4.3 运行命令

```bash
# 仅跑 /rag/eval（适合先验证检索证据链路）
python -m eval rag run --limit 5 --no-chat

# 跑完整双接口聚合
python -m eval rag run --limit 150

# 支持按意图筛选
python -m eval rag run --filter-intent S1_选购推荐

# 支持并发
python -m eval rag run --workers 4
```

---

## 5. 指标体系

### 5.1 已实现的自建指标

#### 意图识别

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `intent_top1_accuracy` | `intent_pred == intent_l2` | ≥ 92% |

#### 检索召回

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `hit@3` | top-3 中是否命中任一 expected_doc_id | — |
| `hit@5` | top-5 中是否命中任一 expected_doc_id | ≥ 90% |
| `recall@3` | top-3 中命中的 expected_doc_id 比例 | — |
| `recall@5` | top-5 中命中的 expected_doc_id 比例 | ≥ 95% |
| `recall@5_inclusive` | 含 expected_doc_ids_nice 的 recall@5 | — |
| `mrr@10` | 第一个命中文档的倒数排名 | — |

#### 鲁棒性

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `false_reject_rate` | `requires_rag=true` 但没返回 KB 证据 | ≤ 3% |
| `over_retrieval_rate` | `requires_rag=false` 但返回了 KB 证据 | — |

#### 性能

| 指标 | 计算方式 | 目标值 |
|---|---|---|
| `avg_ttft_ms` | 首 Token 延迟均值 | ≤ 6000ms |
| `avg_chat_latency_ms` | 完整对话延迟均值 | — |
| `avg_eval_latency_ms` | 检索侧延迟均值 | — |
| `avg_total_latency_ms` | 总延迟均值 | — |

#### 分层指标

按 `difficulty` / `intent_l1` / `intent_l2` / `trap_type` 四个维度分组，分别计算 `intent_top1_accuracy` 和 `hit@5`。

### 5.2 RAGAS 语义指标（可选）

需要 OpenAI 兼容 LLM 作为 judge，通过 `.env` 配置：

| 指标 | 评估维度 | 目标值 |
|---|---|---|
| `faithfulness` | 回答是否忠实于检索到的上下文（不幻觉） | ≥ 0.90 |
| `answer_relevancy` | 回答与问题的相关性 | ≥ 0.85 |
| `context_precision` | 检索到的上下文中有多少是相关的 | — |
| `context_recall` | 相关上下文被检索到的比例 | — |
| `answer_correctness` | 回答与参考答案的一致性 | — |

### 5.3 待补充指标

#### 意图识别（补充）

| 指标 | 计算方式 |
|---|---|
| `intent_top3_accuracy` | 标注意图出现在前 3 个预测意图中 |
| `intent_confidence_calibration` | 预测分数与实际正确率的相关性 |

#### MCP 工具调用（新增）

| 指标 | 计算方式 |
|---|---|
| `mcp_tool_accuracy` | `mcpToolIdUsed == expected_mcp_tool` |
| `mcp_param_exact_match` | 提取的参数与标注参数完全一致 |
| `mcp_param_key_recall` | 标注参数中有多少 key 被正确提取 |
| `mcp_param_value_accuracy` | 已提取的 key 中有多少 value 正确 |
| `mcp_execution_success_rate` | MCP 工具调用是否成功（`isError=false`） |

实现示例：

```python
def mcp_tool_accuracy(records):
    def score(record):
        if not record.expected_mcp_tool:
            return None
        return 1.0 if record.mcp_tool_id_used == record.expected_mcp_tool else 0.0
    value, count, _ = aggregate(records, score)
    return MetricResult("mcp_tool_accuracy", value, count, "Correct MCP tool selected")

def mcp_param_key_recall(records):
    def score(record):
        if not record.expected_mcp_params:
            return None
        expected_keys = set(record.expected_mcp_params.keys())
        extracted_keys = set((record.mcp_extracted_params or {}).keys())
        return len(expected_keys & extracted_keys) / len(expected_keys) if expected_keys else None
    value, count, _ = aggregate(records, score)
    return MetricResult("mcp_param_key_recall", value, count, "Expected param keys correctly extracted")
```

#### 歧义引导（新增）

| 指标 | 计算方式 |
|---|---|
| `guidance_precision` | 触发引导的 case 中，确实标注为歧义的比例 |
| `guidance_recall` | 标注为歧义的 case 中，成功触发引导的比例 |

#### 查询改写（新增）

| 指标 | 计算方式 |
|---|---|
| `rewrite_semantic_similarity` | 改写前后的语义相似度（用 embedding 计算） |
| `sub_question_coverage` | 改写拆分后的子问题是否覆盖了原始问题的所有意图 |

#### 综合指标（新增）

| 指标 | 计算方式 |
|---|---|
| `end_to_end_score` | 加权综合分：0.3×intent_accuracy + 0.3×hit@5 + 0.2×faithfulness + 0.2×answer_relevancy |

### 5.4 分层分析增强

除了现有的 4 个分层维度（difficulty / intent_l1 / intent_l2 / trap_type），建议增加：

```python
# 按检索路径分层
groups = {
    "kb_only": [r for r in records if r.has_kb and not r.has_mcp],
    "mcp_only": [r for r in records if r.has_mcp and not r.has_kb],
    "mixed": [r for r in records if r.has_kb and r.has_mcp],
    "none": [r for r in records if not r.has_kb and not r.has_mcp],
}

# 按子问题数量分层
groups = {
    "single": [r for r in records if len(r.sub_intents) <= 1],
    "multi": [r for r in records if len(r.sub_intents) > 1],
}

# 按意图置信度分层
groups = {
    "high_conf (≥0.8)": ...,
    "medium_conf (0.5-0.8)": ...,
    "low_conf (<0.5)": ...,
}
```

---

## 6. `/rag/eval` 接口待扩展字段

当前 `EvalResponse` 缺少部分中间态数据，需要补充以支持新增指标：

| 新增字段 | 类型 | 说明 |
|---|---|---|
| `rewrittenQuestion` | String | 改写后的问题 |
| `subQuestions` | List\<String\> | 拆分出的子问题列表 |
| `allIntentScores` | List\<NodeScoreDTO\> | 所有意图的完整评分（不只是 top-1） |
| `guidanceTriggered` | boolean | 是否触发了歧义引导 |
| `guidancePrompt` | String | 歧义引导文本 |
| `mcpToolIdUsed` | String | 实际调用的 MCP 工具 ID |
| `mcpExtractedParams` | Map\<String, Object\> | MCP 参数提取结果 |

对应 `EvalController` 需要跑完歧义检测阶段，并把改写结果、意图评分、MCP 参数等中间数据一并返回。

---

## 7. 回归对比机制

每次评测产出 `runs/v1_xxx.jsonl` 作为基线快照，后续评测自动与上一轮对比。

### 7.1 对比逻辑

```python
def compare_runs(baseline_file, current_file):
    baseline_metrics = {m.name: m for m in compute_all(load_records(baseline_file))}
    current_metrics = {m.name: m for m in compute_all(load_records(current_file))}

    for name, current in current_metrics.items():
        baseline = baseline_metrics.get(name)
        if baseline and baseline.value is not None and current.value is not None:
            delta = current.value - baseline.value
            direction = "↑" if delta > 0 else "↓" if delta < 0 else "="
            print(f"{name}: {baseline.value:.4f} → {current.value:.4f} ({direction} {abs(delta):.4f})")
```

### 7.2 输出示例

```
intent_top1_accuracy: 0.8800 → 0.9200 (↑ 0.0400)
hit@5:                0.8500 → 0.9000 (↑ 0.0500)
faithfulness:         0.8800 → 0.8600 (↓ 0.0200)  ← 回归！
avg_ttft_ms:          5200   → 4800   (↑ 400)
```

### 7.3 命令入口

```bash
python -m eval rag compare \
    --baseline eval/rag/runs/v1_baseline.jsonl \
    --current eval/rag/runs/v1_latest.jsonl
```

---

## 8. 完整评测流水线

### Phase 1: 准备

```bash
# 1. 确保知识库、意图树已初始化
python -m eval rag init --output-dir eval/rag/init_out

# 2. 确保评估集已准备（150+ 条）
cat eval/rag/data/eval_set_v1.jsonl | wc -l

# 3. 启动 Ragent 后端（开启评测开关）
APP_EVAL_ENABLED=true ./mvnw -pl bootstrap -am spring-boot:run
```

### Phase 2: 录制

```bash
python -m eval rag run --limit 150
# 产出：eval/rag/runs/v1_20260726T143000.jsonl
```

### Phase 3: 自建指标评分

```bash
python -m eval rag score --run-file eval/rag/runs/v1_20260726T143000.jsonl
```

计算全部自建指标：意图准确率、检索 Hit@K / Recall@K / MRR、误拒率、过召回率、MCP 指标、性能指标、分层指标。

### Phase 4: RAGAS 语义指标（可选）

```bash
# 配置 .env
cp eval/.env.example .env
# 填入 RAGAS_JUDGE_BASE_URL / RAGAS_JUDGE_API_KEY 等

python -m eval rag ragas --run-file eval/rag/runs/v1_20260726T143000.jsonl
```

### Phase 5: 报告 + 回归对比

```bash
# 生成 Markdown 报告
python -m eval rag report --run-file eval/rag/runs/v1_20260726T143000.jsonl

# 与基线对比（可选）
python -m eval rag compare \
    --baseline eval/rag/runs/v1_baseline.jsonl \
    --current eval/rag/runs/v1_20260726T143000.jsonl
```

---

## 9. 指标目标值与优先级

| 优先级 | 指标 | 目标值 | 原因 |
|---|---|---|---|
| P0 | 评估集覆盖度 | 150+ 条 | 没有足够样本，其他一切无意义 |
| P0 | `intent_top1_accuracy` | ≥ 92% | 意图错 = 后面全错，是整个链路的根基 |
| P0 | `hit@5` | ≥ 90% | 检索不到文档 = 无法回答 |
| P1 | `recall@5` | ≥ 95% | 多文档场景下不能漏召回 |
| P1 | `faithfulness` | ≥ 0.90 | 不能幻觉，企业场景下致命 |
| P1 | `false_reject_rate` | ≤ 3% | 该检索的不检索 = 用户体验很差 |
| P2 | `mcp_tool_accuracy` | ≥ 95% | MCP 选错工具 = 数据错误 |
| P2 | `mcp_param_key_recall` | ≥ 90% | 参数漏提 = 查询结果不完整 |
| P2 | `avg_ttft_ms` | ≤ 6000ms | 首包延迟直接影响用户感知 |
| P3 | `guidance_recall` | ≥ 85% | 歧义不引导 = 答非所问 |
| P3 | `answer_relevancy` | ≥ 0.85 | 答案与问题的相关性 |

---

## 10. 项目结构

```
eval/
├── pyproject.toml              # Python 项目元数据
├── README.md                   # 使用说明
├── __main__.py                 # python -m eval 入口
├── rag/
│   ├── data/
│   │   └── eval_set_v1.jsonl   # 评估集样例
│   ├── runs/                   # runner 录制产物
│   ├── reports/                # Markdown 测评报告
│   ├── cli.py                  # 命令行路由
│   ├── client.py               # Ragent HTTP/SSE 客户端
│   ├── config.py               # 客户端配置
│   ├── env.py                  # .env 加载与 RAGAS 客户端创建
│   ├── schema.py               # EvalSample / EvalRecord / MetricResult
│   ├── runner.py               # run 阶段：双接口聚合
│   ├── metrics.py              # score 阶段：自建指标
│   ├── ragas_eval.py           # ragas 阶段：RAGAS 五指标
│   ├── report.py               # report 阶段：Markdown 报告
│   └── init.py                 # init 阶段：初始化蓝图
└── tests/                      # 单元测试

bootstrap/src/main/java/.../rag/eval/
├── EvalController.java         # /rag/eval 旁路接口
├── EvalResponse.java           # 评测响应数据结构
└── EvalProperties.java         # 评测配置开关
```

---

## 11. 当前缺失部分总结

| 缺失项 | 影响 | 优先级 |
|---|---|---|
| 评估集只有 2 条，远未达到 150 条 | 所有指标无统计意义 | P0 |
| 缺少 MCP 场景评测指标 | 工具选择/参数提取质量不可量化 | P1 |
| 缺少歧义引导评测指标 | 歧义检测效果不可量化 | P2 |
| `/rag/eval` 未暴露改写结果、完整意图评分、MCP 参数等中间态 | 新指标无数据支撑 | P1 |
| 缺少查询改写质量评测 | 改写是否变好无法判断 | P3 |
| 缺少回归对比机制 | 无法自动判断代码改动对效果的影响 | P2 |
| 缺少 CI 自动化集成 | 依赖手动执行，容易遗漏 | P3 |
