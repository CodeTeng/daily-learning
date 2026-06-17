# 《AI大模型Ragent项目》——项目模块介绍

这篇文档带着大家一起看看 Ragent 的项目整体结构，搞清楚每个目录和模块各自负责什么。

项目中的代码并不是一成不变的，未来如果有更好的设计思路，会进行重构、优化，甚至新增功能模块。如果发现文档内容和实际代码对不上，请联系马哥，谢谢。

## 根目录文件一览

### 1. `pom.xml`

这是 Maven 父 POM，管理所有子模块的依赖版本和构建插件。打开它你会看到四个 `<module>`：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
<modules> <module>bootstrap</module> <module>framework</module> <module>infra-ai</module> <module>mcp-server</module> </modules>
```

它通过 `<dependencyManagement>` 统一锁定了所有关键依赖的版本号，比如 Spring Boot 3.5.7、Milvus SDK 2.6.6、MyBatis Plus 3.5.14 等等。子模块引用这些依赖时不需要再写版本号，避免版本冲突。

### 2. `lombok.config`

Lombok 的全局配置文件。几个关键设置：

- 让 Jacoco 忽略 Lombok 生成的代码（这个是 GitHub 统计时需要，大家忽略即可）。

- 禁止 `@Data` 自动调用 `callSuper`，避免继承场景下生成不合理的 `equals`/`hashCode`。

- 允许 Spring 的 `@Qualifier` 注解在 Lombok 构造器注入时被正确复制。

### 3. `.gitignore`

定义了哪些文件不纳入 Git 管理：构建产物（`target/`）、IDE 配置（`.idea/`）、前端的 `node_modules` 和 `.env.local`、以及日志目录等。

### 4. `mvnw` / `mvnw.cmd`

Maven Wrapper 脚本，分别对应 Unix 和 Windows。有了它，即使机器上没有全局安装 Maven，也能直接用 `./mvnw` 来构建项目。

### 5. `LICENSE`

Apache License 2.0 许可证全文。

## 四大子模块

Ragent 的代码按职责拆成了四个模块，依赖关系大致是这样的：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
bootstrap ──依赖──▶ framework │ ▲ └──依赖──▶ infra-ai ┘ mcp-server（独立运行）
```

`bootstrap` 是最上层的业务模块，它依赖 `framework`（通用基础设施）和 `infra-ai`（AI 能力层）。`mcp-server` 是一个独立的 Spring Boot 应用，通过 HTTP 提供 MCP 工具调用服务。

## `framework` —— 通用基础设施层

这个模块不包含任何业务逻辑，放的全是跨模块复用的基础组件。任何模块都可能依赖它。

### 1. 统一数据结构

- `Result<T>`：标准 API 响应包装。所有接口返回的都是这个结构，包含 `code`（状态码，`"0"` 表示成功）、`message`、`data`，以及一个 `requestId` 用于链路追踪。

- `ChatRequest`：发给大模型的请求体。封装了 `messages`（对话历史）、`temperature`、`topP`、`maxTokens` 等参数，用 Builder 模式构建。不管底层接哪家大模型，上层都用这一个类。

- `ChatMessage`：对话中的单条消息，包含角色（`SYSTEM` / `USER` / `ASSISTANT`）和内容，提供了 `system()`、`user()`、`assistant()` 三个工厂方法。

- `RetrievedChunk`：向量检索返回的单条结果，包含 `id`、`text` 和相似度 `score`。

### 2. 异常体系

- `BaseErrorCode`：错误码枚举，遵循阿里巴巴的 A/B/C 分类规范。A 类是客户端错误（参数校验失败、重复提交等），B 类是服务端错误（超时、内部异常），C 类是远程调用错误（第三方接口挂了）。

- `AbstractException`：异常基类，携带错误码和错误消息。

- `RemoteException`：专门用于远程服务调用失败的异常。

- `GlobalExceptionHandler`：全局异常拦截器，把各种异常统一转成 `Result<Void>` 返回给前端，同时记录日志。它还处理了 Sa-Token 的 `NotLoginException` 和 `NotRoleException`。

### 3. 用户上下文

- `UserContext`：基于 `TransmittableThreadLocal` 的用户信息容器。在请求入口设置当前用户信息，后续业务代码随时可以通过 `UserContext.getUserId()` 获取，即使跨线程池也不会丢。这里之所以用 `TransmittableThreadLocal` 而不是普通 `ThreadLocal`，是因为普通 `ThreadLocal` 在线程池场景下会失效——线程被复用时，子线程拿不到父线程设置的值。`TransmittableThreadLocal`（来自阿里的 TTL 库）能在线程池提交任务时自动传递上下文，而 RAG 系统大量使用异步线程池做检索和模型调用，所以这个选择是必须的。

- `LoginUser`：用户数据传输对象，包含 `userId`、`username`、`role`、`avatar`。

### 4. 链路追踪与幂等

- `RagTraceContext`：分布式链路追踪上下文，用 TTL 实现跨线程传递。维护 `traceId`、`taskId`，以及一个节点栈来追踪 DAG 执行路径。

- `IdempotentSubmit`：幂等注解，防止表单重复提交。用 SpEL 表达式自定义幂等键。

### 5. SSE 工具

- `SseEmitterSender`：对 Spring 的 `SseEmitter` 做了线程安全封装。通过 `AtomicBoolean` 保证连接只关闭一次，发送前检查连接状态，避免往已关闭的连接写数据时抛异常。

## `infra-ai` —— AI 模型基础设施层

这个模块是整个系统和大模型之间的桥梁。它屏蔽了不同 AI 服务商的接口差异，对上层提供统一的调用方式。内部按能力分为四个子包：`chat`（对话）、`embedding`（向量化）、`rerank`（重排序）、`model`（路由与容错）。

### 1. `chat` 子包 —— 对话能力

#### 1.1 客户端与服务接口

- `ChatClient`：对话客户端的接口定义。

- `BaiLianChatClient`：对接阿里云百炼平台。

- `SiliconFlowChatClient`：对接 SiliconFlow 平台。

- `OllamaChatClient`：对接本地部署的 Ollama。

- `LLMService`：大模型调用的顶层接口，提供流式和非流式两种调用方式。

- `RoutingLLMService`：`LLMService` 的实现，通过 `ModelSelector` 选候选模型，再交给 `ModelRoutingExecutor` 执行（自动容错降级）。

#### 1.2 流式相关

- `StreamCallback`：流式回调接口，定义了 `onToken`（收到一个 token）、`onThinking`（思考过程）、`onComplete`（完成）、`onError`（出错）等事件。

- `StreamAsyncExecutor`：异步执行流式调用，确保不阻塞主线程。

- `StreamCancellationHandle` / `StreamCancellationHandles`：用来取消正在进行的流式请求（比如用户关掉了页面）。

- `OpenAIStyleSseParser`：解析 OpenAI 风格的 SSE 响应。很多国内大模型平台的流式接口格式都兼容 OpenAI，所以这个解析器能复用。

- `FirstPacketAwaiter`：等待流式响应的第一个数据包到达，用于超时检测。

### 2. `embedding` 子包 —— 向量化能力

- `EmbeddingClient`：向量化客户端接口。

- `SiliconFlowEmbeddingClient` / `OllamaEmbeddingClient`：两个具体实现。

- `EmbeddingService`：向量化服务接口。

- `RoutingEmbeddingService`：带路由和容错的实现，逻辑跟 `RoutingLLMService` 一样——选候选、降级、熔断。

### 3. `rerank` 子包 —— 重排序能力

检索到的文档块按向量相似度排序往往不够精确，重排序模型可以进一步优化排名。

- `RerankClient`：重排序客户端接口。

- `BaiLianRerankClient`：对接百炼的重排序模型。

- `NoopRerankClient`：空实现，不做任何重排序，直接透传。用于没有配置重排序模型的场景。

- `RerankService` / `RoutingRerankService`：重排序服务及其路由实现。

### 4. `model` 子包 —— 模型路由与容错

这是 `infra-ai` 最核心的部分，实现了多模型候选 + 自动降级 + 熔断保护的机制。

#### 4.1 `ModelTarget`

一个 `record` 类，封装了一个候选模型的完整信息：模型 ID、候选配置（`ModelCandidate`）、服务商配置（`ProviderConfig`）。可以理解为一次模型调用的目标。

#### 4.2 `ModelSelector`

负责根据调用场景选出一组候选模型。比如：

- `selectChatCandidates(deepThinking)` —— 选对话模型的候选列表。如果开启了深度思考，会优先选支持 thinking 能力的模型。

- `selectEmbeddingCandidates()` —— 选向量化模型。

- `selectRerankCandidates()` —— 选重排序模型。

选出来的候选按优先级排序，同时会通过 `ModelHealthStore` 过滤掉正在熔断中的模型。

#### 4.3 `ModelRoutingExecutor`

拿到候选列表后，逐个尝试调用。第一个成功了就返回结果，失败了就标记健康状态、记录日志、尝试下一个。所有候选都失败了才抛 `RemoteException`。

#### 4.4 `ModelHealthStore`

实现了经典的熔断器模式，维护每个模型的健康状态，有三个状态：

- CLOSED（正常）：所有请求正常通过。

- OPEN（熔断）：连续失败次数达到阈值后进入此状态，所有请求直接拒绝，不再实际调用模型。

- HALF_OPEN（试探）：熔断持续一段时间后，允许一个请求试探。成功则恢复到 CLOSED，失败则回到 OPEN。

用 `ConcurrentHashMap` 存储状态，CAS 操作保证线程安全。

#### 4.5 `ModelCaller`

一个泛型函数式接口：`T call(C client, ModelTarget target)`。`ModelRoutingExecutor` 通过它来抽象具体的调用逻辑，不关心调的是对话模型还是向量化模型。

### 5. 其他辅助类

- `AIModelProperties`：从 `application.yaml` 读取模型配置的属性类。定义了服务商（`ProviderConfig`）、模型候选（`ModelCandidate`）的结构。

- `ModelCapability` / `ModelProvider`：枚举类型，分别定义模型能力（对话、向量化、重排序）和服务商（百炼、SiliconFlow、Ollama）。

- `ModelUrlResolver`：根据服务商和能力类型拼接 API 地址。

- `TokenCounterService` / `HeuristicTokenCounterService`：Token 计数服务，用启发式方法估算文本的 token 数量（不依赖具体的 tokenizer）。

- `LLMResponseCleaner`：清理大模型返回内容中的格式标记（比如 Markdown 代码块标记）。

## `bootstrap` —— 业务主模块

这是整个系统的入口，也是代码量最大的模块，`RagentApplication.java` 启动类就在这里。

`bootstrap` 按功能域划分为以下几个包：

### 1. `rag` —— RAG 对话核心

整个 RAG 问答的主流程都在这里。一次用户提问的完整链路：

- 1.
加载记忆 —— `ConversationMemoryService` 从缓存或数据库加载最近几轮对话历史。

- 2.
查询改写 —— `QueryRewriteService` 结合上下文重写用户问题，还会把复杂问题拆成多个子问题。

- 3.
意图识别 —— `IntentResolver` 把问题匹配到意图树节点，判断该走知识库检索还是 MCP 工具调用。

- 4.
歧义引导 —— `IntentGuidanceService` 发现问题模糊时，生成引导性提示让用户进一步明确。

- 5.
多通道检索 —— `RetrievalEngine` 并行执行向量检索和 MCP 工具调用，`MultiChannelRetrievalEngine` 协调多个搜索通道。

- 6.
上下文组装 —— `RAGPromptService` + `ContextFormatter` 把检索结果格式化后拼进 Prompt。

- 7.
流式生成 —— 调用 `LLMService` 流式获取大模型回答，通过 SSE 推送给前端。

#### 1.1 检索子系统的细节

检索部分有两条主通道：

- `VectorGlobalSearchChannel`：全局向量搜索，直接拿用户问题（或改写后的子问题）去 Milvus 里做相似度检索。

- `IntentDirectedSearchChannel`：意图定向检索，根据意图树匹配到的节点，在特定范围内做更精准的向量搜索。

检索完之后经过后处理链：

- `DeduplicationPostProcessor`：去重，多个通道可能返回相同的文档块。

- `RerankPostProcessor`：用重排序模型对结果重新打分排序。

#### 1.2 记忆管理

对话记忆分两层：

- 短期记忆：`ConversationMemoryService` 根据配置保留最近 x 轮对话。

- 长期记忆：`ConversationMemorySummaryService` 在对话超过 x 轮时自动生成摘要，持久化到 MySQL 摘要表。

### 2. `ingestion` —— 数据 ETL 流水线

这个包实现了一套可配置的文档处理流水线。你可以把它想象成一条工厂的流水线，文档从一头进去，经过若干工位加工，最终变成向量存到数据库里。

#### 2.1 流水线节点

每个节点实现 `IngestionNode` 接口，按顺序串联执行：

节点

职责

`FetcherNode`

从数据源获取原始文档（支持本地文件、HTTP URL、飞书、S3）

`ParserNode`

解析文档内容（PDF、Markdown、纯文本等，底层用 Apache Tika）

`EnricherNode`

内容增强，比如抽取摘要、补充元数据

`ChunkerNode`

把长文本切成小块（支持按段落、按句子、固定长度等策略）

`EnhancerNode`

对切好的块做后处理优化

`IndexerNode`

调用 Embedding 服务向量化，写入 Milvus

#### 2.2 执行引擎

`IngestionEngine` 是流水线的执行器。它按 DAG（有向无环图）的拓扑结构依次执行每个节点，支持条件分支（通过 `ConditionEvaluator` 判断是否跳过某个节点），并做环路检测防止死循环。

### 3. `knowledge` —— 知识库管理

管理知识库、文档、文档块三个层级的 CRUD：

- 知识库（`KnowledgeBaseService`）：创建和管理知识库，每个知识库关联一条摄入流水线。

- 文档（`KnowledgeDocumentService`）：在知识库内管理文档，追踪文档状态。

- 文档块（`KnowledgeChunkService`）：管理已经切好并入库的文本块，支持单条修改。

还有一个定时任务（`KnowledgeDocumentScheduleServiceImpl`）会周期性扫描需要同步的知识库文档，用分布式锁保证集群环境下不会重复执行。

### 4. `admin` —— 管理后台

- `DashboardService`：聚合系统指标，包括总会话数、用户数、文档数、Token 消耗等。

- `DashboardController`：提供三个维度的仪表盘接口——概览（`overview`）、性能（`performance`）、趋势（`trends`）。

- `QueryTermMappingAdminService`：管理关键词到意图的映射关系。

### 5. `user` —— 用户认证

基于 Sa-Token 实现的认证模块：

- `AuthService`：登录验证，生成 Token。

- `UserService`：用户增删改查。

- 默认管理员账号：`admin` / `admin`（初始化数据在 `resources/database/init_data.sql`）。

### 6. `core` —— 核心工具

放了两类与业务无关但被频繁使用的组件：

- 文本切块（`core/chunk/`）：提供多种切块策略——`FixedSizeTextChunker`（固定长度）、`SentenceChunker`（按句子）、`ParagraphChunker`（按段落）、`StructureAwareTextChunker`（识别文档结构）。通过 `ChunkingStrategyFactory` 按配置选择。

- 文档解析（`core/parser/`）：`TikaDocumentParser`（基于 Apache Tika，支持 PDF/Word/HTML 等）和 `MarkdownDocumentParser`（专门处理 Markdown），通过 `DocumentParserSelector` 自动选择。

## `mcp-server` —— MCP 工具服务

这是一个独立部署的 Spring Boot 应用，实现了 MCP（Model Context Protocol）协议。大模型在对话过程中如果发现需要调用外部工具（比如查天气、查工单），就会通过这个服务来执行。

### 1. 协议层

- `MCPEndpoint`：HTTP 入口，接收 `POST /mcp` 请求。

- `JsonRpcRequest`：JSON-RPC 2.0 格式的请求体。

- `MCPDispatcher`：方法路由器，根据 `method` 字段分发到不同处理逻辑：

- `initialize` —— 返回协议版本和服务端能力。

- `tools/list` —— 返回所有已注册工具的定义。

- `tools/call` —— 执行指定工具。

### 2. 工具注册

- `MCPToolRegistry` / `DefaultMCPToolRegistry`：工具注册表，启动时自动发现所有 `MCPToolExecutor` 实现并注册。用 `ConcurrentHashMap` 存储，支持按 `toolId` 查找。

- `MCPToolExecutor`：工具执行器接口，每个工具实现这个接口就能自动被注册和调用。

- `MCPToolDefinition`：工具元数据，包括 `toolId`、描述、参数定义（类型、是否必填、默认值、枚举选项等）。大模型根据这些信息决定什么时候该调用什么工具。

### 3. 内置工具

目前有两个示例工具：

- `WeatherMCPExecutor`：天气查询。支持 20 个国内城市，能返回当前天气或多日预报，数据是基于日期种子生成的（模拟数据）。

- `TicketMCPExecutor`：工单查询。支持按区域、状态、优先级、产品线等维度筛选，提供汇总、列表、统计三种输出格式。

要扩展新工具，只需要实现 `MCPToolExecutor` 接口并注册为 Spring Bean，不需要改任何框架代码。

## 其他根目录内容

### 1. `frontend/`

前端工程，技术栈是 React 18 + TypeScript + Vite + Tailwind CSS，UI 组件基于 Radix UI。这篇文档主要聚焦后端，前端不再展开。

### 2. `resources/`

存放项目级的共享资源：

路径

内容

`resources/format/copyright.txt`

Apache 2.0 版权头模板，Spotless 插件用它给 Java 文件自动加注释

`resources/database/schema_table.sql`

完整的建表 SQL，包含会话、摄入流水线、知识库、用户等所有表

`resources/database/init_data.sql`

初始化数据，目前只有默认管理员账号

`resources/docker/`

Docker Compose 配置，包含 Milvus 向量数据库的部署文件

### 3. `scripts/`

运维脚本目录。目前有一个 `sse_queue_test.sh` 用于 SSE 队列的压测，以及 `logs/` 目录存放脚本运行日志。

### 4. `.mvn/`

Maven Wrapper 的配置目录，存放 `maven-wrapper.properties` 等文件，指定 Maven 的下载地址和版本。

## 技术栈速查

类别

技术选型

运行时

Java 17 + Spring Boot 3.5.7

数据库

PostgreSQL（MyBatis Plus）

向量数据库

Pgvector

缓存 & 会话

Redis（Redisson）

认证

Sa-Token

文档解析

Apache Tika

对象存储

S3 兼容接口

HTTP 客户端

OkHttp

前端

React 18 + TypeScript + Vite

代码规范

Spotless + Lombok

> Source: https://t.zsxq.com/uFeGe
> Resolved: https://articles.zsxq.com/id_u1wvvwhmaxwp.html
