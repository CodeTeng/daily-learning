# 技术点二：多通道混合检索与 MCP 工具编排 —— 面试复习

> 简历描述：KB 路径采用意图定向、全局向量、关键词多通道并行混合召回，经去重、RRF 融合、Rerank 后处理流水线精炼结果；MCP 路径通过 LLM 从用户问题中提取工具参数后调用远端工具；两条路径并行执行、异常隔离

---

## 一、做什么

把意图识别的结果变成实际的检索动作，产出 LLM 生成回答所需的"证据"：

- **KB 路径**：对 KB 类意图，从向量数据库检索相关文档片段
- **MCP 路径**：对 MCP 类意图，从用户问题中提取参数，调用远端工具获取实时数据
- 两条路径**并行执行、异常隔离**，最终合并成统一的上下文证据

检索质量直接决定回答质量——检索不到正确证据，LLM 只能瞎编。

---

## 二、怎么实现的（核心技术）

### 2.1 总体架构

入口：`RetrievalEngine.retrieve()`，先按子问题维度并行，每个子问题内部将意图分为 KB 组和 MCP 组分别处理。

```
RetrievalEngine.retrieve()
  │
  ├── 子问题1 ─┐
  ├── 子问题2 ─┤  ragContextExecutor（子问题级并行）
  └── 子问题3 ─┘
       │
       每个子问题内部（buildSubQuestionContext）：
       │
       ├── KB 路径: MultiChannelRetrievalEngine
       │     │
       │     【阶段1：多通道并行检索】
       │     ├── IntentDirectedSearchChannel (priority=1)
       │     ├── KeywordSearchChannel (priority=2)
       │     └── VectorGlobalSearchChannel (priority=10)
       │     │
       │     【阶段2：后处理器链（串行）】
       │     ├── DeduplicationPostProcessor (order=1)   去重
       │     ├── FusionPostProcessor (order=5)           RRF 融合
       │     └── RerankPostProcessor (order=10)          Rerank 精排
       │
       └── MCP 路径（与 KB 并行）
             ├── LLM 参数提取（LLMMcpParameterExtractor）
             ├── 工具执行（McpClientToolExecutor）
             └── 结果格式化（ContextFormatter）
```

### 2.2 KB 路径 —— 多通道并行检索

由 `MultiChannelRetrievalEngine` 协调。三个检索通道均实现 `SearchChannel` 接口，通过 `ragRetrievalExecutor` 线程池并行执行：

#### 通道 1：IntentDirectedSearchChannel（意图定向检索，priority=1）

- **启用条件**：存在 KB 意图且 `score >= minIntentScore`(0.4)
- **策略**：`IntentParallelRetriever` 按意图节点的 `collectionName` 定向到特定知识库检索
- **TopK**：`baseTopK * topKMultiplier(2)`，如 topK=10 则每个意图取 20 条候选
- **特点**：精度高，只检索最相关的知识库

#### 通道 2：KeywordSearchChannel（关键词检索，priority=2）

- **启用条件**：始终启用
- **策略**：基于 Elasticsearch 全文检索（BM25）
- **特点**：擅长精确术语匹配——专有名词、编号、缩写等向量模型不擅长的场景

#### 通道 3：VectorGlobalSearchChannel（向量全局检索，priority=10）

- **启用条件**（任一满足）：
  - 意图定向通道被禁用（兜底）
  - 没有识别出任何意图
  - 最高意图分 < `confidenceThreshold`(0.6)
  - 单一意图且分数 < `singleIntentSupplementThreshold`(0.8)
- **策略**：
  - 支持跨库检索（如 PG）：单条 SQL 跨库召回
  - 不支持（如 Milvus）：`CollectionParallelRetriever` 逐库并行 fan-out
- **特点**：覆盖面广，作为召回率兜底

**通道启用关系是互补的**：

| 场景 | 意图定向 | 全局检索 | 效果 |
|---|---|---|---|
| 意图很确信（score ≥ 0.8） | ✅ | ❌ | 只走精准检索 |
| 意图中等（0.6 ≤ score < 0.8） | ✅ | ✅ | 精准 + 兜底 |
| 意图不确信（score < 0.6） | ✅ | ✅ | 精准 + 兜底 |
| 没有识别出意图 | ❌ | ✅ | 只走全覆盖 |

#### 并行检索框架（AbstractParallelRetriever）

采用**模板方法模式**封装通用并行逻辑，子类只需实现 3 个方法：

```java
public abstract class AbstractParallelRetriever<T> {
    public final List<RetrievedChunk> executeParallelRetrieval(
            String question, List<T> targets, int topK) {
        // 1. 对每个目标创建 CompletableFuture，提交到线程池并行执行
        // 2. join 收集结果
        // 3. 按 score 降序归并排序（保证通道出口的全局相关性排序不变式）
        // 4. 打印统计日志
    }
    protected abstract List<RetrievedChunk> createRetrievalTask(String question, T target, int topK);
    protected abstract String getTargetIdentifier(T target);
    protected abstract String getStatisticsName();
}
```

两个子类：`IntentParallelRetriever`（按意图节点并行）和 `CollectionParallelRetriever`（按 Collection 并行）。

### 2.3 KB 路径 —— 后处理器链

所有通道的结果合并后，按 `order` 顺序串联执行（实现 `SearchResultPostProcessor` 接口）。每个处理器异常被单独 catch，不中断整个链。

#### DeduplicationPostProcessor（order=1，始终启用）

- 按通道优先级遍历（INTENT_DIRECTED=1 > KEYWORD=2 > GLOBAL=3），高优先级通道结果优先占位
- 用 `LinkedHashMap` 保序去重，key = `chunk.id`（有 id 用 id，无 id 用 **SHA-256**(text)）
- 同 key 出现多次，保留 score 最高的

#### FusionPostProcessor（order=5，策略为 RRF 时启用）

**RRF（Reciprocal Rank Fusion，倒数名次融合）**：

```
score(chunk) = Σ_channel  1 / (k + rank_channel + 1)
```

- k 为常数（默认 60），rank 为 chunk 在该通道内的名次（从 0 开始）
- 名次取自不可变的 `SearchChannelResult` 列表（每个通道的原始召回顺序），即使上游去重已合并 chunks，也不丢失"多路命中"信息
- 多路命中的 chunk 分数累加，自然排名靠前
- 融合后按 `rerankCandidateLimit`(30) 截断候选池，只把高分前 N 个送入 Rerank
- 单通道时跳过融合，仅做截断

#### RerankPostProcessor（order=10，配置启用）

- 调用 `RerankService.rerank(question, chunks, topK)`
- 底层通过 `RoutingRerankService` 路由到具体 Rerank 模型（如百炼 Rerank）
- 按语义相关性重新打分并截断到最终 topK
- 这是最后一个处理器，输出即为送入 Prompt 的最终 Chunk 列表

### 2.4 MCP 路径 —— 参数提取 + 工具执行

#### Step 1 — 启动时工具注册

`McpClientAutoConfiguration.@PostConstruct` 在启动时连接所有配置的 MCP Server：

```java
for (ServerConfig server : servers) {
    McpSyncClient client = McpClient.sync(transport).build();
    client.initialize();
    ListToolsResult result = client.listTools();  // 发现工具
    for (Tool tool : result.tools()) {
        McpClientToolExecutor executor = new McpClientToolExecutor(client, tool);
        toolRegistry.register(executor);  // 注册到 DefaultMcpToolRegistry（内存 Map）
    }
}
```

#### Step 2 — LLM 参数提取（LLMMcpParameterExtractor）

以用户问"华东地区本季度销售排名前5"为例：

**构建工具定义文本**：把工具的 JSON Schema 翻译成中文自然语言：

```
工具ID: sales_query
功能描述: 查询软件销售数据，支持按地区、时间、产品等维度筛选
参数列表:
  - region (类型: string, 可选): 地区筛选 [可选值: 华东, 华南, 华北, 西南, 西北]
  - period (类型: string, 可选): 时间段 [可选值: 本月, 上月, 本季度, 上季度, 本年] [默认值: 本月]
  - queryType (类型: string, 可选): 查询类型 [可选值: summary, ranking, detail, trend] [默认值: summary]
  - limit (类型: integer, 可选): 返回记录数限制 [默认值: 10]
```

**LLM 调用**：`temperature=0.1, topP=0.3`，用 `mcp-parameter-extract.st`（System）+ `mcp-parameter-extract-user.st`（User，含工具定义和用户问题）模板。

**三层安全过滤**：
1. **清理格式**：`LLMResponseCleaner.stripMarkdownCodeFence()` 清理 LLM 可能包裹的 ```json ... ``` 代码块
2. **白名单过滤**：只保留 Schema 中声明的参数名，LLM 幻觉出的额外字段被丢弃
3. **类型转换**：`5.0 → 5`（int），避免 JSON 数值默认 double 的问题；中文数字"前五"→`5`（由 Prompt 规则引导）
4. **默认值回填**：LLM 未提取 + Schema 有 default → 自动补上

#### Step 3 — 工具执行（McpClientToolExecutor）

```java
public CallToolResult execute(Map<String, Object> parameters) {
    try {
        return mcpClient.callTool(new CallToolRequest(toolDefinition.name(), parameters));
    } catch (Exception e) {
        return CallToolResult.builder()
            .content(List.of(new TextContent("远程调用失败: " + e.getMessage())))
            .isError(true)
            .build();  // 包装为错误结果，不抛异常
    }
}
```

多个 MCP 工具通过 `mcpBatchExecutor` 线程池并行执行，单工具异常不阻塞其他工具。

#### Step 4 — 异常降级

参数提取失败时（JSON 解析异常等），构建只有默认值的参数集合兜底调用工具：

```java
catch (JsonSyntaxException e) {
    return buildDefaultParameters(tool);  // {"period":"本月","queryType":"summary","limit":10}
}
```

#### Step 5 — 自定义参数提取 Prompt

意图节点的 `paramPromptTemplate` 字段允许为特定工具定制参数提取逻辑。当默认 Prompt 处理不好某个工具的参数语义时（如工单状态映射："还没处理的" → `PENDING`），在意图节点上配置专用 Prompt 即可，不需改代码。

### 2.5 并行架构总览

整个检索层有 **5 个线程池、3 层并行嵌套**：

| 线程池 | 用途 | 粒度 |
|---|---|---|
| `intentClassifyExecutor` | 意图分类 | 每个子问题一个任务 |
| `ragContextExecutor` | 子问题上下文构建 | 每个 SubQuestionIntent 一个任务 |
| `ragRetrievalExecutor` | 多通道检索 | 每个 SearchChannel 一个任务 |
| `innerRetrievalExecutor` | 通道内并行 | 每个意图节点/Collection 一个任务 |
| `mcpBatchExecutor` | MCP 工具调用 | 每个工具一个任务 |

---

## 三、为什么这样做

### 为什么多通道并行而不是单一检索？

单纯依赖意图定向，意图判错就颗粒无收；单纯全局检索，噪声和延迟都高。多通道是"双重保险"：**意图定向负责精度，全局检索负责召回率兜底，关键词检索负责向量模型的盲区**（专有名词、编号等精确匹配）。三者独立运行，某一通道失败不影响其他通道。

### 为什么用置信度动态开启/关闭通道，而不是固定组合？

如果两个通道永远都跑，每次都付出全局检索的延迟和资源成本，即使意图已非常明确（score=0.95）。反过来如果只跑意图定向，一旦分类器判错就彻底漏检。用置信度动态决策是把"要不要多花一次检索成本"和意图可信度绑定：意图越确定，越不需要全局补充；意图越模糊，越需要兜底。这是**准确率、召回率与延迟/成本**的自适应权衡。

### 为什么用 RRF 融合而不是直接拼接排序？

向量检索返回余弦相似度（0~1，分布集中），关键词检索返回 BM25 分数（可能几十上百，分布发散）。直接按原始分数排序，几乎必然是高分通道把低分通道结果全部压下去——这不是真实相关性，只是分数量纲不同导致的假象。RRF **完全抛弃原始分数，只依据名次**计算融合分数，天然跨模态可比；多路命中的 chunk 分数累加自然排前，体现"多路命中=更可信"的直觉。

### 为什么先 RRF 粗排再 Rerank 精排？

Rerank 模型（交互式语义相关性模型）计算成本和延迟远高于向量检索或 RRF 排序。如果每次对几十上百个候选全部跑 Rerank，会显著拖慢首字延迟。RRF 先做低成本"粗筛"，截断到几十个高分候选，再用 Rerank 在小范围"精筛"——经典**粗排+精排**两阶段思路，兼顾效果和成本。

### 为什么拆分工具选择和参数提取为两次 LLM 调用，而不用原生 tool_use？

原生 tool_use 让模型一次推理同时决定"调哪个工具"和"传什么参数"，链路更短，但企业场景有两个短板：一是工具选择无法像意图树一样做精细化管理（分层、置信度阈值、歧义引导、按节点配置专属 Prompt）；二是参数提取和工具选择耦合，无法针对某工具单独定制提取逻辑。拆成两步后，工具选择复用意图树路由体系，参数提取可为每个工具单独设计 Prompt，出问题能快速定位。代价是牺牲多步 think→act→observe 循环能力，但企业内部工具场景对"稳定可控"要求高于"智能自主决策"。

### 为什么把 JSON Schema 翻译成中文自然语言，而不是直接扔给 LLM？

JSON Schema 是给程序解析的结构化格式，字段名常是英文缩写、嵌套不直观，LLM 直接读容易遗漏约束（如 enum 可选值、哪个必填）。翻译成"参数名 (类型, 必填/可选): 描述 [可选值: ...] [默认值: ...]"后，关键约束被显式标注，LLM 理解和遵循准确率更高，尤其在处理中文用户问题时更能对齐语义。

### 为什么对 LLM 返回参数做白名单过滤？

LLM 存在幻觉倾向，可能"好心"加上 Schema 中不存在的字段。不过滤直接传下游工具，可能引发参数校验异常，或更隐蔽地——工具端忽略未知参数，但排查时让人误以为该参数生效了。用 Schema 字段名做白名单，成本很低但能杜绝一类幻觉引发的故障。

---

## 四、遇到的困难与解决方案

### 困难 1：多通道结果分数不可比导致排序失真

**问题**：最初直接按原始分数排序多通道结果，发现向量检索（0~1）的结果总是被关键词检索（BM25 几十分）压下去，或者反过来——取决于哪个通道分数范围更大。这不是真实相关性排序，只是分数量纲不同导致的假象。

**分析**：通过评测发现 `hit@5` 只有 ~80%，且很多本应排在前面的向量检索结果被关键词检索的高分结果挤到 top-5 之外。查看具体 case，发现同一个正确文档在向量通道排第 1（score=0.85），在关键词通道排第 5（BM25=45），但直接排序后被关键词通道的高分文档压到第 6。

**解决方案**：引入 **RRF 倒数名次融合**：
- 完全基于名次而非原始分数计算融合分 `score = Σ 1/(k + rank + 1)`
- 多路命中的 chunk 分数累加自然排前
- k=60 作为平滑常数，避免 top-1 的 chunk 分数过高压制其他结果

**效果**：`hit@5` 从 ~80% 提升到 90%+，因为正确文档即使在某通道分数不高，只要在多个通道都排名靠前，RRF 累加后就能进入 top-5。

### 困难 2：去重时 String.hashCode() 碰撞导致误去重

**问题**：去重处理器最初用 `String.hashCode()` 做 chunk 去重键。上线后发现偶发性漏召回——某些本该出现的 chunk 莫名消失，且不报错、难复现。

**分析**：`String.hashCode()` 只有 32 位，在大量文本内容中存在碰撞概率（生日问题，经典反例 "Aa" 和 "BB" 的 hashCode 相同）。一旦碰撞，两个内容完全不同的 chunk 被误判为"重复"，其中一个被静默丢弃。这种 bug 极难发现——不会报错，只是偶尔漏了不该漏的内容，且难以稳定复现。

**解决方案**：改用 **SHA-256** 做去重键：
```java
private String generateChunkKey(RetrievedChunk chunk) {
    return chunk.getId() != null
            ? chunk.getId()
            : DigestUtil.sha256Hex(chunk.getText() == null ? "" : chunk.getText());
}
```
SHA-256 碰撞概率在实践中可忽略，用极小计算开销换取正确性上的确定性保证。同时 `FusionPostProcessor` 的 RRF 融合键也统一改用 SHA-256，避免分数被错误累加到同一个键。

### 困难 3：MCP 参数提取不稳定

**问题**：MCP 参数提取环节 LLM 返回结果不稳定，出现几种情况：
1. 返回非法 JSON——LLM 有时包裹 markdown 代码块（```json ... ```）
2. 幻觉出 Schema 中不存在的字段——LLM"好心"编一个 `category` 字段
3. 中文数字不转换——"前五"没有变成 `5`，而是字符串 `"前五"`
4. 偶发性 JSON 解析失败导致整个 MCP 调用中断

**分析**：LLM 输出不完全可信是一个本质性问题，不能假设它永远返回标准格式。需要多层防御。

**解决方案**（四层防御）：
1. **格式清理**：`LLMResponseCleaner.stripMarkdownCodeFence()` 自动剥离 markdown 代码块包裹
2. **白名单过滤**：解析后只保留 Schema 中声明的参数名，幻觉字段被丢弃
3. **Prompt 规则强化**：在 `mcp-parameter-extract.st` 中明确定义枚举映射规则（"本周" → `current_week`）、中文数字转换规则（"前五" → `5`）、布尔处理（"是/要" → `true`）
4. **降级兜底**：提取完全失败时用 `buildDefaultParameters(tool)` 构建默认参数集合，工具仍能以默认参数被调用，返回"能用但不够精确"的结果，好过直接报错

**效果**：参数提取成功率从 ~85% 提升到 97%+，偶发失败时也能降级返回默认结果而非中断。

### 困难 4：并行检索的异常传播与线程池隔离

**问题**：某一个通道或工具调用超时/异常时，如果没隔离好会把整个检索任务拖死——CompletableFuture 的异常在 join 时会抛出，导致整个子问题上下文构建失败。

**解决方案**：
- **独立线程池**：5 个线程池按职责隔离，避免某个慢任务占用所有线程资源
- **每层独立 try-catch**：通道级（`executeSearchChannels` 内 catch 后返回 `emptyResult`）、子问题级（`buildSubQuestionContext` 内 catch 后返回空上下文）、后处理器级（每个处理器独立 catch 不中断链）、MCP 工具级（catch 后包装为 `isError=true` 的错误结果）
- **异常隔离设计原则**：贯穿整个检索层，单点故障不扩散

```java
// 子问题级异常隔离示例
.map(si -> CompletableFuture.supplyAsync(
    () -> {
        try {
            return buildSubQuestionContext(si, resolveSubQuestionTopK(si, finalTopK));
        } catch (Exception e) {
            log.error("子问题上下文构建失败，降级为空上下文，question：{}", si.subQuestion(), e);
            return new SubQuestionContext(si.subQuestion(), "", "", Map.of());
        }
    },
    ragContextExecutor
))
```

### 困难 5：Rerank 候选池过大导致首字延迟超标

**问题**：最初把所有通道的全部候选（几十到上百个）直接送入 Rerank 模型，Rerank 调用耗时 2-3 秒，导致 TTFT（首字延迟）超过 6 秒目标。

**分析**：Rerank 是交互式语义模型，每个候选都要和问题做一次交叉注意力计算，候选数和耗时成正比。大量明显不相关的候选也在跑 Rerank，纯属浪费。

**解决方案**：在 RRF 融合后增加**候选池截断**（`truncateForRerank`）：
- 配置 `rerankCandidateLimit=30`，只把 RRF 融合后的前 30 个高分候选送入 Rerank
- RRF 已经做了一次低成本粗筛，明显不相关的被过滤
- Rerank 只需对 30 个候选精排，耗时从 2-3 秒降到 ~800ms

**效果**：TTFT 从 ~7 秒降到 ~5 秒以内，`hit@5` 基本无损失（被截断的都是 RRF 低分候选）。

---

## 五、量化指标与优化过程

| 指标 | 优化前 | 优化后 | 提升手段 |
|---|---|---|---|
| Hit@5 | ~80% | ≥ 90% | RRF 融合替代直接拼接排序 |
| Recall@5 | ~80% | ≥ 95% | 全局检索兜底 + 多通道互补 |
| MCP 参数提取成功率 | ~85% | ≥ 97% | 格式清理 + 白名单 + 降级兜底 |
| Rerank 延迟 | 2-3s | ~800ms | RRF 粗排截断候选池到 30 |
| TTFT | ~7s | ≤ 6s | 候选池截断 + 并行检索 |
| 去重误删率 | 偶发不可控 | ≈0 | SHA-256 替代 hashCode |

---

## 六、面试高频问题

### Q1：RRF 的 k 值（默认 60）是怎么定的？调大调小有什么影响？

> "k 是 RRF 公式里的平滑常数：`score = Σ 1/(k + rank + 1)`。k 越大，top-1 和 top-10 的分数差距越小，相当于'淡化名次差异'，让多路命中的累加效应更显著；k 越小，名次差异越被放大，top-1 的优势更明显。60 是学术界常用的经验值，在我们场景下调到 40 和 80 都试过——40 时多路命中优势体现得更强但 top-1 的精准度略降，80 时更偏向单通道排名。最终选 60 是在'多路命中加权'和'单通道排名尊重'之间的平衡点。这个参数也通过评测集调优过——对比不同 k 值下的 hit@5。"

### Q2：为什么不直接用向量检索，还要加关键词检索？

> "向量检索擅长语义匹配——'怎么请假'能匹配到'休假制度'。但它有盲区：一是**专有名词和编号**（如'KB-2024-001'这个文档编号、'P8'这种职级缩写），向量模型不一定能精确匹配；二是**低频术语**，embedding 训练语料里没见过的词，向量化效果差。关键词检索（BM25）正好补这个盲区——它是基于词频的精确匹配。两者互补：向量管'语义相近'，关键词管'字面一致'，RRF 融合后命中率比单一通道都高。"

### Q3：Rerank 模型选的什么？为什么不直接用向量相似度排序？

> "Rerank 用的是百炼的 Rerank 模型。向量检索的相似度是**双塔模型**——问题和文档独立编码再算余弦相似度，速度快但精度有限，因为它没让问题和文档的内容直接'交互'。Rerank 是**交互式模型**——把问题和每个候选文档拼在一起送进模型，做交叉注意力计算，能捕捉到更细粒度的语义关系，比如否定、条件、时态等。所以检索阶段用双塔（快、粗筛），精排阶段用交互式（慢、精准），是业界标准的两阶段架构。"

### Q4：MCP 工具调用如果远程服务挂了怎么办？

> "三层容错：一是 `McpClientToolExecutor.execute()` 内部 catch 所有异常，包装成 `isError=true` 的 `CallToolResult` 返回，不抛异常中断链路；二是结果格式化时，错误结果用 `mcp-error` 模板渲染成'工具调用异常'的提示文本，LLM 会基于这个提示生成回复，而不是沉默失败；三是多个 MCP 工具通过独立线程池并行，单工具挂了不阻塞其他工具。如果是模型层的故障，还有 infra-ai 层的三态熔断器，自动切换到备选模型。"

### Q5：你说两条路径并行执行，具体是怎么并行的？用的什么并发原语？

> "Java 的 `CompletableFuture` + 独立线程池。在 `buildSubQuestionContext()` 内部，KB 检索和 MCP 调用是两个独立的 `CompletableFuture.supplyAsync()`，提交到各自的线程池（KB 用 `ragRetrievalExecutor`，MCP 用 `mcpBatchExecutor`），然后分别 join。更高一层，多个子问题也通过 `ragContextExecutor` 并行。整个检索层有 5 个线程池、3 层并行嵌套。选 CompletableFuture 而不是 ParallelStream 是因为它更可控——可以指定独立线程池、异常处理更灵活、join 时可以单独 catch 而不会像 ParallelStream 那样一个异常终止整个流。"

### Q6：为什么用模板方法模式做 AbstractParallelRetriever？

> "因为 `IntentParallelRetriever`（按意图节点并行）和 `CollectionParallelRetriever`（按 Collection 并行）的并行框架完全一样——都是'对每个目标创建任务、提交线程池、join 收集、按 score 归并排序'，只有'对单个目标怎么检索'这一个步骤不同。模板方法把通用逻辑放在父类 `executeParallelRetrieval()` 的 final 方法里，子类只实现 `createRetrievalTask()` 等 3 个抽象方法。好处是新增一种并行检索策略时（比如未来加 ES 检索的并行器），不用重复写线程池提交和结果归并的逻辑，只关注检索本身。也保证了所有并行检索的出口都有统一的全局相关性排序不变式。"

### Q7：意图定向检索的 topK 为什么要乘以 multiplier(2)？

> "因为后面有去重和 RRF 融合——多个意图检索的结果可能有重叠，去重后数量会减少；而且 RRF 融合后还要截断到 rerankCandidateLimit 送入 Rerank。如果定向检索只取 topK=10，去重融合后可能只剩 6-7 条，Rerank 的候选池太小，精排效果出不来。乘以 2 取 20 条候选，给去重和融合留出余量，保证送入 Rerank 时有足够的候选（接近 rerankCandidateLimit=30）。全局检索的 multiplier 是 3，更大，因为它本来就是兜底通道，要尽量多召回。这些都是通过评测集调优过的。"
