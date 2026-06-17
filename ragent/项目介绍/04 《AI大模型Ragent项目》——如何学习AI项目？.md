# 《AI大模型Ragent项目》——如何学习AI项目？

Ragent AI 覆盖了 RAG 从数据入库到问答生成的完整链路，模块多、设计细节也多。直接翻源码大概率迷失在各种类和接口之间。这篇文档帮你理清学习节奏，少走弯路。

## 学习方式

### 以文档为主，视频为辅

教学内容以文档为主。文档可以按自己节奏来，遇到不理解的地方随时翻代码验证。后续会有部分视频补充操作演示和系统效果，但核心知识点都在文档里，不看视频不影响学习。

文档写的非常详细，我觉得如果从讲解项目角度上，完全不需要视频。

### 不建议从零写代码

40000 行后端代码从零敲一遍，大量时间花在抄写上，对理解架构帮助有限。更推荐 Debug + AI 辅助编码：

- Debug 跟代码：在关键方法上打断点，跑一次完整问答流程，跟着调用链走下去。比如在检索入口打断点，看多路检索怎么并行、后处理器链怎么串起来，比读代码直观得多

- AI 辅助理解：遇到看不懂的模块，直接把代码贴给 AI 工具。比如把熔断器的状态转换逻辑贴进去，让它解释状态流转条件。Cursor、Claude Code、Codex 都行，选顺手的

- 小范围改代码验证：理解某个模块后做些小改动验证。比如改检索的 `topK` 看效果变化，或者在后处理器链里加个自定义节点，比从零写更能锻炼对架构的理解

## 学习路线

整体节奏：补基础概念 → 跑通系统 → 带着问题深入模块代码。

![无法获取该图片](https://oss.open8gu.com/iShot_2026-03-17_10.28.66.jpg)

### 第一步：掌握 AI 基础知识

如果之前没接触过 RAG 相关技术，先把基础篇过一遍。每篇都从零开始讲，不需要 AI 背景知识，并且附带完整可运行的 Java 代码示例。

顺序

文档

核心收获

1

什么是 RAG？

核心六步流程，准备阶段和运行阶段各做什么

2

大模型基础 LLM

Token、上下文窗口、Temperature 等核心概念，主流模型选型

3

模型调用 API

OpenAI 兼容协议的请求响应格式，流式与非流式调用

4

Prompt 工程

五要素框架，RAG 场景下怎么写 Prompt 才不容易出幻觉

5

数据分块 Chunk

为什么要分块，五种分块策略各自适合什么场景

6

元数据管理 Metadata

元数据在检索过滤、答案溯源中的作用

7

向量化 Embedding

文本怎么变成向量，余弦相似度怎么算

8

向量数据库 VectorDatabase

Milvus 核心概念，IVF 和 HNSW 两种索引算法

9

检索策略 RetrievalStrategy

BM25、混合检索、RRF 融合、Reranking 重排序

10

生成策略 GenerationStrategy

三段式 Prompt 结构，幻觉抑制，引用对齐

11

函数调用 FunctionCall

Function Call 的本质和完整流程

12

MCP 协议

MCP 三层架构，工具调用的标准化方案

13

会话记忆 ConversationMemory

五种记忆策略，Token 预算分配

14

Query 改写 QueryRewrite

指代消解、上下文补全、口语化转正式

15

意图识别与问题路由 IntentRouting

四种意图类型，规则 + 大模型的混合分类方案

16

评估与优化 Evaluation

分层评估指标，LLM-as-Judge 自动评测

不用急着一口气读完，跟着跑一遍代码示例效果更好。

### 第二步：跑通一次完整问答

基础概念到位后，按快速启动文档把系统跑起来。目标很简单：至少完成一次从用户输入到系统返回答案的完整问答。

跑通后在管理后台熟悉一下各功能：

- 知识库管理：文档怎么上传和入库

- 意图树：怎么配置

- 链路追踪：一次问答经过哪些环节、每个环节耗时

这一步不需要看代码，纯粹建立宏观认知——系统长什么样、有哪些功能、完整流程是什么。有这个整体感觉，后面深入代码才不会迷路。

### 第三步：跟着实战章节 Debug 代码

接下来深入代码。实战章节每篇聚焦一个模块，讲清设计思路和关键实现，跟着文档 Debug 即可掌握。

已发布和规划中的内容：

知识库模块 —— 文档从上传到可检索的完整流程

- 知识库系统宏观设计

- 文件上传的限流策略和内存控制

- 文档上传、分块、同步的接口实现

- 定时同步的调度引擎与故障恢复

本地大模型 —— 为什么需要本地部署、怎么接入

- 为什么要本地部署大模型

- Ollama 核心概念与架构

- Ollama 安装与模型调用实战

大模型调度引擎 —— 核心基础设施，模型路由、容错、流式处理

- AI 基础设施层宏观设计

- 多模型路由与智能选择

- 三态熔断器与故障转移

- Chat 同步调用与模板方法

- SSE 流式解析与异步执行

- 流式路由的首包探测机制

- Embedding 向量化客户端

- Rerank 重排序与辅助工具

SSE 系列 —— 流式响应的协议和工程实现

- SSE 协议与流式响应

- Spring Boot SSE 服务端实战

MCP 系列 —— 工具调用的协议规范和架构设计

- JSON-RPC 2.0 标准说明

- 工具调用架构设计指南

- 工具调用稳定性与安全保障

等等。

每篇文章都会标明在哪个类打断点、跟着什么链路走、关注哪些关键逻辑。Debug 时结合文档一起看，比单独看代码或单独看文档都高效。

## 怎么算学透了？

不是每行代码看过就算学透，关键是能回答以下问题，并且知道对应代码在哪里。

### 1. RAG 核心链路

主链路是系统骨架。入口 `RAGChatServiceImpl#streamChat`，一个用户问题进来后经过七个环节：记忆加载 → 改写拆分 → 意图解析 → 歧义引导 → 检索（KB + MCP）→ Prompt 组装 → 流式输出。

需要搞清楚的问题：

改写和拆分是怎么一起做的？

`MultiQuestionRewriteService` 先做术语归一化（如缩写还原全称），再调一次 LLM 同时完成改写和多问句拆分，输出 `RewriteResult` 包含改写后的完整问题和子问题列表。LLM 调用失败时，用归一化后的问题 + 规则拆分兜底，不中断链路。

意图识别怎么处理多子问题？

`IntentResolver#resolve` 把每个子问题并行提交到 `intentClassifyExecutor` 线程池做意图分类。当子问题过多、意图总数超上限时，有一套截断策略——每个子问题至少保留一个最高分意图，剩余配额按分数从高到低分配。

歧义引导插在哪个环节？

在意图识别之后、检索之前。`IntentGuidanceService#detectAmbiguity` 判断问题是否模糊，需要引导澄清时直接返回引导话术，跳过后续检索和生成。

改写后的问题和原始问题分别用在哪？

检索和 Prompt 组装用改写后的问题（语义更精准），会话记忆里存的是用户原始输入。

### 2. 多路检索引擎

检索是最容易出效果问题的环节。分两层：`RetrievalEngine` 做顶层编排，`MultiChannelRetrievalEngine` 做通道级并行。

两个检索通道各自做什么？

`IntentDirectedSearchChannel` 根据意图识别结果做定向检索，只在命中意图关联的知识库范围内搜索；`VectorGlobalSearchChannel` 做全局向量检索，不限定范围。两个通道通过 `CompletableFuture` 并行执行，提交到专用的 `ragRetrievalExecutor` 线程池。

通道结果怎么合并？

两个通道的 `SearchChannelResult` 合并成一个 Chunk 列表，依次经过后处理器链：`DeduplicationPostProcessor` 按内容哈希去重，`RerankPostProcessor` 调 Reranker 模型精排序。执行顺序由 `getOrder()` 决定，某个处理器失败不中断整条链。

KB 检索和 MCP 工具调用怎么并行？

`RetrievalEngine#retrieve` 把每个子问题的 KB 检索和 MCP 调用分开。KB 走多通道检索引擎，MCP 走 `executeMcpTools` 并行调用多个工具，结果合并成 `RetrievalContext`，分别填充到 Prompt 的不同区域。

`topK` 怎么动态确定？

不是简单的全局配置。`resolveSubQuestionTopK` 先看意图节点上有没有节点级 `topK`，多个意图节点都配了则取最大值；没有节点级配置才回退到全局默认值。

### 3. 模型路由与容错

大模型 API 不稳定是常态，`infra-ai` 层做了一整套路由和容错机制。代码量不大，但并发控制细节密集。

同步调用的容错怎么做？

`ModelRoutingExecutor#executeWithFallback` 遍历候选模型列表依次尝试。每次调用前先问 `ModelHealthStore#allowCall` 模型是否可用，成功标记 `markSuccess`，失败标记 `markFailure`。全部失败才抛异常。

三态熔断器的状态转换条件？

`ModelHealthStore` 用 `ConcurrentHashMap` + `compute` 保证线程安全。`CLOSED` 状态连续失败次数达 `failureThreshold` 切到 `OPEN`；`OPEN` 到冷却时间（`openDurationMs`）自动切到 `HALF_OPEN`；`HALF_OPEN` 只放一个请求（`halfOpenInFlight` 标志位），成功回 `CLOSED`，失败回 `OPEN`。

流式调用的首包探测怎么做？

这是容错机制里最难的部分。`RoutingLLMService#streamChat` 不能等完整响应再判断成败——连接建立但迟迟没内容也算失败。`ProbeStreamBridge` 拦截在真正的 `StreamCallback` 前面，用 `CompletableFuture` 阻塞等首包。首包到了才算成功，超时或报错就取消当前连接、切下一个模型。首包到达前所有回调缓冲在 `buffer` 列表里，确认成功后 `commit` 批量回放给下游，用 `synchronized` + `volatile committed` 保证线程安全和可见性。

### 4. 会话记忆管理

多轮对话的记忆管理要在 Token 成本、响应速度和上下文质量之间做平衡。

记忆加载的并行优化怎么做？

`DefaultConversationMemoryService#load` 并行加载摘要和历史记录（两个 `CompletableFuture`），合并时摘要插在历史记录前面。摘要加载失败不阻塞整个流程，只跳过摘要。

摘要压缩的触发时机？

每次 `append` 新消息后，`ConversationMemorySummaryService#compressIfNeeded` 检查历史轮数是否超阈值，超过则异步触发摘要生成（提交到 `memorySummaryExecutor` 线程池），把早期对话压缩成一条摘要消息。

改写阶段怎么使用历史记录？

`MultiQuestionRewriteService#buildRewriteRequest` 从历史记录中过滤掉 System 摘要消息（避免浪费 Token），只保留最近 x 轮的 User 和 Assistant 消息拼到改写 Prompt 里。这样改写模型能理解上下文，把“那它的保修期呢”改写成“iPhone 16 Pro 的保修期是多久”。

### 5. 文档入库流水线

文档从上传到可检索要经过完整流水线。`IngestionEngine` 是执行引擎，基于节点连线的链式执行模型。

流水线的节点编排怎么实现？

`PipelineDefinition` 定义节点列表，每个 `NodeConfig` 有 `nodeId`、`nodeType`、`nextNodeId` 和可选 `condition`。引擎启动时先通过路径追踪检测环，再找到起始节点（未被任何节点引用），然后链式执行。

节点执行失败怎么办？

失败中断整条流水线，状态置为 `FAILED` 并记录错误信息。每个节点的执行结果（耗时、输入输出、成功/失败）写入 `NodeLog`，方便排查。

条件节点怎么跳过？

`NodeConfig` 可配置 `condition`，`ConditionEvaluator` 执行前评估，不满足则跳过该节点直接走 `nextNodeId`。

不同文档抓取方式怎么扩展？

`DocumentFetcher` 是策略接口，已有 `S3Fetcher`（对象存储）、`LocalFileFetcher`（本地文件）、`HttpUrlFetcher`（网页）、`FeishuFetcher`（飞书文档）四种实现。新增抓取方式实现该接口即可。

分块策略怎么选？

`ChunkingStrategy` 是策略接口，`ChunkingStrategyFactory` 根据配置选择具体实现。不同文档类型适合不同策略，基础篇的数据分块章节有详细讲解。

### 6. MCP 工具调用

知识检索和业务系统调用融合在同一套流程里，这是 Ragent AI 区别于简单 RAG 系统的地方。

知识检索和工具调用怎么在同一次问答中并存？

意图识别阶段给每个子问题打上 `IntentKind`——`KB`（知识库检索）或 `MCP`（工具调用）。`RetrievalEngine#buildSubQuestionContext` 按类型分别走不同路径，KB 走多通道检索，MCP 走工具执行，结果分别放入 `kbContext` 和 `mcpContext`，最终都拼到 Prompt 里。

MCP 工具的参数怎么提取？

`MCPParameterExtractor` 根据工具定义（`MCPTool`）里声明的参数 Schema，用 LLM 从用户问题中提取参数。意图节点上还可配置 `paramPromptTemplate` 自定义提取提示词。

MCP 工具的注册和发现机制？

`MCPToolRegistry` 管理所有已注册的工具执行器（`MCPToolExecutor`），按 `toolId` 查找。工具定义遵循 JSON-RPC 2.0 协议，每个执行器实现 `execute` 方法处理请求并返回 `MCPResponse`。

### 7. 分布式排队限流

大模型 API 并发能力有限，不做限流会被打崩。`ChatQueueLimiter` 实现了基于 Redis 的跨实例排队机制，是系统里并发控制最复杂的一块。

三个 Redis 数据结构各自的职责？

`RPermitExpirableSemaphore` 控制全局并发上限；`RScoredSortedSet`（ZSET）维护等待队列，score 是自增序列号保证 FIFO；`RTopic`（Pub/Sub）在 permit 释放时通知所有实例的等待者。

排队核心流程？

请求进来先尝试直接获取 permit，拿到就执行；拿不到就加入 ZSET 队列，启动定时轮询（`scheduleAtFixedRate`）。轮询时先用 Lua 脚本原子判断是否排到队首（`claimIfReady`），再尝试获取 permit。拿到 permit 后提交到 `chatEntryExecutor` 线程池执行。

为什么需要 Lua 脚本？

排队位置检查和出队必须原子操作。两步操作（先查排名再删除）在高并发下会出现多个请求同时认为自己排到队首的问题。

资源泄漏怎么防？

`SseEmitter` 的 `onCompletion`、`onTimeout`、`onError` 三个回调都注册了 `releaseOnce`，用 `AtomicBoolean` + `AtomicReference` 保证 permit 只释放一次。`PollNotifier` 内部有定时清理，5 分钟没轮询的注册者自动移除。

排队超时怎么处理？

超过 `globalMaxWaitSeconds` 后请求从队列移除，记录一条被拒绝的对话记录（用户消息 + 拒绝回复），通过 SSE 推送拒绝事件给前端。

### 8. 全链路追踪

注意，如果学习时间比较紧，本章节可忽略。属于增强式功能，不在核心链路中。

系统有 9 个专用线程池（MCP 批处理、RAG 上下文处理、RAG 通道检索、RAG 内部检索、意图分类、记忆摘要、模型流式输出、SSE 排队入口、知识库文档分块），一个请求可能跨越多个线程池，上下文不丢是实际工程问题。

Trace 上下文怎么跨线程透传？

`RagTraceContext` 用阿里 TTL（`TransmittableThreadLocal`）存储 `traceId`、`taskId` 和节点栈。所有线程池通过 `TtlExecutors.getTtlExecutor()` 包装，任务提交时 TTL 自动把父线程上下文拷贝到子线程。漏了这层包装，子线程取到的 `traceId` 就是 `null`。

`@RagTraceNode` 注解做了什么？

AOP 切面注解，标记在关键方法上（改写、意图识别、检索、LLM 路由等）。切面在方法执行前 `pushNode`、执行后 `popNode`，形成调用栈结构，配合耗时记录，可在管理后台看到完整调用链路和每个环节的耗时分布。

Trace 记录的生命周期？

`ChatRateLimitAspect` 负责创建和收尾。排队获得 permit 后、执行 `streamChat` 前，生成 `traceId` 和 `taskId`，写入 `RUNNING` 状态的 Trace Run 记录；执行完成后更新为 `SUCCESS` 或 `ERROR`，记录总耗时。中间各环节通过 `@RagTraceNode` 自动记录子节点。

## 小结

不需要一次性把所有模块搞定。挑最感兴趣或和工作最相关的 2-3 个模块先深入，把对应的问题搞清楚，能结合代码讲出设计思路和工程取舍，这个系统就算掌握了。剩下的模块用到时再补，有了前面的基础，上手会很快。

> Source: https://t.zsxq.com/tJKcd
> Resolved: https://articles.zsxq.com/id_0oaux6bp2v2a.html
