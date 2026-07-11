# rewriteQuery 完整流程文档

## 总览

`rewriteQuery` 是 RAG 流式对话管道（`StreamChatPipeline`）中的**第二个阶段**，负责对用户原始问题进行改写和多问句拆分，产出 `RewriteResult` 供后续意图识别和检索使用。

### 入口方法全景

`QueryRewriteService` 接口提供三个入口方法，最终均汇聚到 `MultiQuestionRewriteService` 的核心实现：

| 入口方法 | 场景 | 最终调用 |
|---------|------|---------|
| `rewrite(question)` | 仅需改写结果（不拆分） | → `rewriteAndSplit(question)` → 取 `.rewrittenQuestion()` |
| `rewriteWithSplit(question)` | 无历史上下文场景 | → `rewriteAndSplit(question)` |
| `rewriteWithSplit(question, history)` | **管道实际调用**，含会话历史 | → 归一化 → `callLLMRewriteAndSplit(normalized, original, history)` |

```mermaid
flowchart TD
    A["用户原始问题 + 会话历史"] --> B["StreamChatPipeline.rewriteQuery(ctx)"]
    B --> C["queryRewriteService.rewriteWithSplit(question, history)"]
    C --> C1["MultiQuestionRewriteService.rewriteWithSplit(question, history)<br/>⬇️ @RagTraceNode(name=query-rewrite-and-split)"]
    C1 --> D{queryRewriteEnabled?}
    D -- "❌ 关闭" --> E["规则模式：归一化 + 规则拆分"]
    D -- "✅ 开启" --> F["LLM 模式：归一化 + LLM改写拆分"]
    E --> G["返回 RewriteResult"]
    F --> G
    G --> H["ctx.setRewriteResult(rewriteResult)"]
    H --> I["后续阶段：resolveIntents → 检索 → 生成"]

    style C1 fill:#fff3cd,stroke:#856404
```

> **💡 @RagTraceNode 说明**：`@RagTraceNode` 是 RAG 链路追踪注解（定义于 `framework.trace` 包），标注在方法上后，AOP 切面会自动记录该节点的执行耗时、入参和出参，用于全链路可观测性。注解属性：`name`（节点名称，用于展示）、`type`（节点类型，用于分组统计）。

---

## 详细流程图

> **⚠️ 注意**：管道实际调用的是带 history 的 `rewriteWithSplit(question, history)` 方法。另有 `rewrite(question)` 和 `rewriteWithSplit(question)` 两个入口走私有方法 `rewriteAndSplit()`（无历史参数），其内部逻辑与带历史版本相同，只是 `callLLMRewriteAndSplit` 的 history 参数传空列表。

```mermaid
flowchart TD
    START(["🔴 rewriteQuery 入口"]) --> A["ctx.getQuestion() → 用户原始问题"]
    A --> B["ctx.getHistory() → 会话历史消息"]
    B --> C["queryRewriteService.rewriteWithSplit(question, history)<br/>⬇️ @RagTraceNode(name=query-rewrite-and-split, type=REWRITE)"]

    C --> D{检查开关<br/>ragConfigProperties.queryRewriteEnabled}

    D -- "false<br/>❌ 关闭" --> E1["queryTermMappingService.normalize(question)"]
    E1 --> E2["ruleBasedSplit(normalized)"]
    E2 --> E3["new RewriteResult(normalized, subs)"]
    E3 --> RETURN(["🟢 返回结果"])

    D -- "true<br/>✅ 开启" --> F1["queryTermMappingService.normalize(question)<br/>⬇️ 术语归一化"]
    F1 --> F2["callLLMRewriteAndSplit(normalizedQuestion, originalQuestion, history)<br/>⬇️ normalized=归一化后问题, original=原始问题"]

    %% callLLMRewriteAndSplit 子流程
    F2 --> G1["promptTemplateLoader.load(QUERY_REWRITE_AND_SPLIT_PROMPT_PATH)<br/>⬇️ 加载系统提示词（带内存缓存）"]
    G1 --> G2["buildRewriteRequest(systemPrompt, normalizedQuestion, history)<br/>⬇️ 构建聊天请求（第2个参数是归一化后的问题）"]
    G2 --> G3["llmService.chat(req)<br/>⬇️ 调用 LLM"]
    G3 --> G4["parseRewriteAndSplit(raw)<br/>⬇️ 解析 JSON 结果"]
    G4 --> G5{解析成功?}
    G5 -- "✅ parsed ≠ null" --> G6["记录日志 → 返回 parsed"]
    G6 --> RETURN
    G5 -- "❌ parsed == null" --> G7["⚠️ 兜底：new RewriteResult(normalizedQuestion, List.of(normalizedQuestion))"]
    G7 --> RETURN

    %% LLM 调用异常分支
    G3 --> X1["⚠️ Exception 捕获"]
    X1 --> X2["日志警告：使用归一化问题兜底"]
    X2 --> G7

    RETURN --> H1["ctx.setRewriteResult(rewriteResult)"]
    H1 --> END(["🔵 rewriteQuery 结束"])
```

### 另两个入口方法流程

```mermaid
flowchart TD
    ENTRY1(["rewrite(question) 入口<br/>⬇️ @RagTraceNode(name=query-rewrite, type=REWRITE)"]) --> R1["rewriteAndSplit(question)"]
    ENTRY2(["rewriteWithSplit(question) 入口<br/>无历史版本"]) --> R1

    R1 --> R2{queryRewriteEnabled?}
    R2 -- "❌ 关闭" --> R3["normalize + ruleBasedSplit"]
    R2 -- "✅ 开启" --> R4["normalize(question)<br/>→ callLLMRewriteAndSplit(normalized, original, List.of())<br/>⬇️ 注意：history 传空列表"]

    R3 --> R5["new RewriteResult(normalized, subs)"]
    R4 --> R5

    R5 --> R6{"调用方是<br/>rewrite() ?"}
    R6 -- "是" --> R7["返回 result.rewrittenQuestion()<br/>⬇️ 仅取改写结果，丢弃子问题"]
    R6 -- "否" --> R8["返回 RewriteResult 完整结果"]
```

---

## 核心内部函数详解

### 1. QueryTermMappingService.normalize — 术语归一化

**职责**：将用户问题中的非标准术语替换为标准术语（如 "平安保司" → "平安保险"）

```mermaid
flowchart TD
    N1(["normalize(text) 入口"]) --> N2{text == null 或空?}
    N2 -- "是" --> N3["直接返回原文本 text"]
    N2 -- "否" --> N4["loadMappings()<br/>⬇️ 加载映射规则（缓存优先→DB回填）"]
    N4 --> N5{mappings 为空?}
    N5 -- "是" --> N3B["返回原文本 text<br/>⬇️ 无规则可应用"]
    N5 -- "否" --> N6["初始化 result = text"]
    N6 --> N7["逐条遍历映射规则"]
    N7 --> N7A{当前规则 enabled == null<br/>或 enabled == 0?}
    N7A -- "是，跳过" --> N7
    N7A -- "否" --> N7B{matchType != null<br/>且 matchType != 1?}
    N7B -- "是，跳过<br/>⬇️ 仅处理精确匹配" --> N7
    N7B -- "否（matchType==1<br/>或 matchType==null）" --> N7C{source/target<br/>为空?}
    N7C -- "是，跳过" --> N7
    N7C -- "否" --> N8["QueryTermMappingUtil.applyMapping(result, source, target)<br/>⬇️ 安全替换（防重复归一化）"]
    N8 --> N7
    N7 -- "遍历结束" --> N9{result ≠ text?<br/>⬇️ 即有归一化变更}
    N9 -- "是" --> N10["日志：查询归一化 original → normalized"]
    N9 -- "否" --> N11["无变更，静默返回"]
    N10 --> N11["返回 result"]

    style N3B fill:#e8f5e9
```

#### 1.1 loadMappings — 加载映射规则

> **⚠️ 排序逻辑说明**：代码使用 `Comparator.comparing(priority, nullsLast(Integer::compareTo)).reversed().thenComparing(sourceTerm.length, reverseOrder())`。
> - `.comparing(priority, nullsLast)` 构造升序比较器（null排末尾）
> - `.reversed()` 反转整个比较器 → 变为 **priority 降序**，且 `nullsLast` 也被反转，**null 排首位**（等同于 nullsFirst 效果）
> - `.thenComparing(sourceTerm长度, reverseOrder())` = 长词排在前面，优先匹配
> - **⚠️ 设计矛盾**：`QueryTermMappingDO.priority` 字段注释说"数值越小优先级越高"，但代码按 **降序排列**（大值先执行），这意味着 **优先级数值越大的规则实际先被应用**，与注释语义相反。同时，priority 为 null 的规则会排在最前面先执行，这可能也不是预期行为。长词优先匹配的需求通过 `thenComparing` 的长度降序来实现。

```mermaid
flowchart TD
    L1(["loadMappings() 入口"]) --> L2["cacheManager.getMappingsFromCache()<br/>⬇️ Redis 缓存读取（key=ragent:query-term:mappings）"]
    L2 --> L3{缓存命中且非空?}
    L3 -- "✅ 命中" --> L4["返回缓存数据"]
    L3 -- "❌ 未命中或为null" --> L5["mappingMapper.selectList(enabled=1)<br/>⬇️ MyBatis-Plus 数据库查询<br/>⬇️ 条件：enabled = 1"]
    L5 --> L6["排序规则：<br/>① priority 降序（reversed反转nullsLast → null排首位）<br/>② sourceTerm 长度降序（长词先匹配）"]
    L6 --> L7["cacheManager.saveMappingsToCache(dbList)<br/>⬇️ 回填 Redis（7天过期）<br/>⬇️ 异常仅打日志，不影响业务"]
    L7 --> L4
```

#### 1.2 QueryTermMappingUtil.applyMapping — 安全替换

```mermaid
flowchart TD
    M1(["applyMapping(text, sourceTerm, targetTerm) 入口"]) --> M2{"text/sourceTerm<br/>为空?"}
    M2 -- "是" --> M3["返回原文本"]
    M2 -- "否" --> M4["遍历 text，查找 sourceTerm"]
    M4 --> M5{"找到 sourceTerm<br/>位置 hit"}
    M5 -- "❌ 未找到" --> M6["拷贝剩余文本，结束"]
    M5 -- "✅ 找到" --> M7{"当前位置已是<br/>targetTerm 开头?"}
    M7 -- "是（已归一化）" --> M8["保留原文 targetTerm<br/>跳过 targetLen 字符"]
    M7 -- "否（需替换）" --> M9["写入 targetTerm<br/>跳过 sourceLen 字符"]
    M8 --> M4
    M9 --> M4
    M6 --> M10["返回归一化结果"]
```

**映射规则数据结构**（`QueryTermMappingDO`）：

| 字段 | 说明 |
|------|------|
| `sourceTerm` | 用户原始短语 |
| `targetTerm` | 归一化目标短语 |
| `matchType` | 匹配类型：1=精确匹配（当前仅用此类型） |
| `priority` | 优先级（数值越小越高，长词优先匹配） |
| `enabled` | 1=生效，0=禁用 |
| `domain` | 业务域标识（可选） |

---

### 2. callLLMRewriteAndSplit — LLM 改写 + 拆分

**职责**：将归一化后的问题通过 LLM 改写为适合检索的查询，并判断是否需要拆分为多个子问题

```mermaid
flowchart TD
    C1(["callLLMRewriteAndSplit(normalized, original, history) 入口"]) --> C2["promptTemplateLoader.load<br/>('prompt/user-question-rewrite.st')<br/>⬇️ 加载系统提示词模板"]

    C2 --> C3["buildRewriteRequest(systemPrompt, normalizedQuestion, history)<br/>⬇️ 构建聊天请求（第2个参数是归一化后的问题）"]
    C3 --> C3A["构建消息列表 messages"]
    C3A --> C3B{"systemPrompt 非空?"}
    C3B -- "是" --> C3C["添加 System 消息"]
    C3B -- "否" --> C3D["跳过"]
    C3C --> C3D
    C3D --> C3E{"history 非空?"}
    C3E -- "是" --> C3F["过滤保留 USER + ASSISTANT 消息<br/>最多保留最近 4 条（2轮）"]
    C3E -- "否" --> C3G["跳过"]
    C3F --> C3G
    C3G --> C3H["添加 User 消息：归一化后的问题"]
    C3H --> C3I["构建 ChatRequest：<br/>temperature=0.1, topP=0.3, thinking=false"]
    C3I --> C4["llmService.chat(req) ⬇️ 调用 LLM"]

    C4 --> C5["parseRewriteAndSplit(raw) ⬇️ 解析结果"]

    C5 --> C5A["LLMResponseCleaner.stripMarkdownCodeFence(raw)<br/>⬇️ 去除 Markdown 代码块"]
    C5A --> C5B["JsonParser.parseString → 解析 JSON"]
    C5B --> C5C{"是 JsonObject?"}
    C5C -- "否" --> C5NULL["返回 null"]
    C5C -- "是" --> C5D["提取 rewrite 字段"]
    C5D --> C5E{"有 sub_questions<br/>且是 JsonArray?"}
    C5E -- "是" --> C5F["遍历提取非空字符串<br/>→ subs 列表"]
    C5E -- "否" --> C5G["subs 空列表"]
    C5F --> C5H{"rewrite 为空?"}
    C5G --> C5H
    C5H -- "是" --> C5NULL
    C5H -- "否" --> C5I{"subs 为空?"}
    C5I -- "是" --> C5J["subs = List.of(rewrite)<br/>即不拆分"]
    C5I -- "否" --> C5K["返回 RewriteResult(rewrite, subs)"]
    C5J --> C5K

    C5K --> C6{"解析成功?"}
    C6 -- "✅ parsed ≠ null" --> C7["日志记录：原始→归一化→改写→子问题"]
    C7 --> C8["返回 parsed"]
    C6 -- "❌ parsed == null" --> C9["⚠️ 兜底：RewriteResult(normalized, List.of(normalized))"]

    %% 异常分支
    C4ERR["⚠️ Exception"] --> C10["日志警告：LLM调用失败"]
    C10 --> C9

    C8 --> RET(["🟢 最终返回"])
    C9 --> RET
```

---

### 3. ruleBasedSplit — 规则拆分（兜底）

**职责**：当 LLM 不可用或开关关闭时，按常见分隔符拆分多问句

```mermaid
flowchart TD
    S1(["ruleBasedSplit(question) 入口"]) --> S2["按分隔符正则拆分：<br/>[?？。；;\\n]+"]
    S2 --> S3["trim + 过滤空白"]
    S3 --> S4{拆分结果为空?}
    S4 -- "是" --> S5["返回 List.of(question)<br/>即不拆分"]
    S4 -- "否" --> S6["每个片段：<br/>若不以？/?结尾则补？"]
    S6 --> S7["返回子问题列表"]
```

---

### 4. buildRewriteRequest — 构建聊天请求

**职责**：组装 LLM 调用所需的 `ChatRequest`，控制历史消息截断

> **⚠️ 历史截断逻辑细节**：代码 `history.stream().filter(...).skip(Math.max(0, history.size() - 4))` 中，`skip` 的数值基于**原始 history.size()** 而非过滤后的列表大小。这意味着当 history 中含有大量 System 消息时，filter 先筛掉 System 消息，但 skip 仍按原始数量跳过，可能导致实际保留的历史消息少于 4 条甚至为空。这是当前实现的一个潜在问题。

```mermaid
flowchart TD
    B1(["buildRewriteRequest(systemPrompt, question, history) 入口<br/>⬇️ question = 归一化后的问题(normalizedQuestion)"]) --> B2["初始化 messages 列表"]
    B2 --> B3{"systemPrompt 非空?"}
    B3 -- "是" --> B4["messages.add(ChatMessage.system(systemPrompt))"]
    B3 -- "否" --> B5["跳过"]
    B4 --> B5
    B5 --> B6{"history 非空?"}
    B6 -- "是" --> B7["① filter：仅保留 USER + ASSISTANT 角色<br/>② skip(Math.max(0, history.size() - 4))<br/>⬇️ skip数基于原始history.size()<br/>⬇️ 最多保留最近4条（≈2轮对话）<br/>⚠️ 当history含大量System消息时可能截断过度"]
    B7 --> B8["messages.addAll(recentHistory)"]
    B6 -- "否" --> B9["跳过"]
    B8 --> B9
    B9 --> B10["messages.add(ChatMessage.user(question))<br/>⬇️ question = 归一化后的问题"]
    B10 --> B11["构建 ChatRequest：<br/>messages=messages<br/>temperature=0.1（保守采样）<br/>topP=0.3（保守nucleus）<br/>thinking=false"]
    B11 --> B12["返回 ChatRequest"]

    style B7 fill:#fff3cd,stroke:#856404
```

---

### 5. parseRewriteAndSplit — 解析 LLM JSON 输出

**职责**：将 LLM 返回的 JSON 文本解析为 `RewriteResult`

```mermaid
flowchart TD
    P1(["parseRewriteAndSplit(raw) 入口"]) --> P2["LLMResponseCleaner.stripMarkdownCodeFence(raw)<br/>⬇️ 去除 ```json ... ``` 围栏"]
    P2 --> P3["JsonParser.parseString(cleaned)"]
    P3 --> P4{"是 JsonObject?"}
    P4 -- "否" --> P5["返回 null"]
    P4 -- "是" --> P6["提取 'rewrite' 字段 → trimmed"]
    P6 --> P7{"有 'sub_questions'<br/>且为 JsonArray?"}
    P7 -- "是" --> P8["遍历数组<br/>提取非空字符串 → subs"]
    P7 -- "否" --> P9["subs = 空列表"]
    P8 --> P10{"rewrite 为空?"}
    P9 --> P10
    P10 -- "是" --> P5
    P10 -- "否" --> P11{"subs 为空?"}
    P11 -- "是" --> P12["subs = List.of(rewrite)<br/>⬇️ 未拆分：子问题=改写结果"]
    P11 -- "否" --> P13["返回 RewriteResult(rewrite, subs)"]
    P12 --> P13
    P3ERR["⚠️ JSON 解析异常"] --> P14["日志警告 → 返回 null"]
```

---

### 6. LLMResponseCleaner.stripMarkdownCodeFence — 去除代码围栏

**职责**：清理 LLM 输出中可能包裹的 Markdown 代码块标记

```mermaid
flowchart TD
    F1(["stripMarkdownCodeFence(raw) 入口"]) --> F2{"raw == null?"}
    F2 -- "是" --> F3["返回 null"]
    F2 -- "否" --> F4["raw.trim()"]
    F4 --> F5["去除开头围栏：```json 等标记<br/>⬇️ 正则: ^```[\\w-]*\\s*\\n?"]
    F5 --> F6["去除结尾围栏：```<br/>⬇️ 正则: \\n?```\\s*$"]
    F6 --> F7["再次 trim()"]
    F7 --> F8["返回 cleaned"]
```

---

### 7. PromptTemplateLoader.load — 提示词模板加载

**职责**：从 classpath 加载提示词模板文件，带内存缓存，避免重复 IO

> 模板路径常量：`QUERY_REWRITE_AND_SPLIT_PROMPT_PATH = "prompt/user-question-rewrite.st"`，定义于 `RAGConstant`。

```mermaid
flowchart TD
    PT1(["load(path) 入口<br/>⬇️ path = 'prompt/user-question-rewrite.st'"]) --> PT2{"path 为空?"}
    PT2 -- "是" --> PT3["抛 IllegalArgumentException('提示模板路径为空')"]
    PT2 -- "否" --> PT4["cache.computeIfAbsent(path, this::readResource)<br/>⬇️ ConcurrentHashMap 内存缓存"]
    PT4 --> PT5{"缓存命中?"}
    PT5 -- "✅ 命中" --> PT6["直接返回缓存内容"]
    PT5 -- "❌ 未命中" --> PT7["readResource(path)"]
    PT7 --> PT8{"path 以 'classpath:' 开头?"}
    PT8 -- "是" --> PT9["直接使用 path 作为资源定位"]
    PT8 -- "否" --> PT10["拼接 'classpath:' 前缀"]
    PT9 --> PT11["resourceLoader.getResource(location)"]
    PT10 --> PT11
    PT11 --> PT12{"资源文件存在?"}
    PT12 -- "否" --> PT13["抛 IllegalStateException('提示词模板路径不存在')"]
    PT12 -- "是" --> PT14["读取 InputStream → new String(bytes, UTF_8)"]
    PT14 --> PT6

    style PT3 fill:#ffcdd2
    style PT13 fill:#ffcdd2
```

---

## 数据流总结

```mermaid
flowchart LR
    INPUT["用户问题 + 会话历史"] --> NORMALIZE["术语归一化<br/>QueryTermMappingService"]

    NORMALIZE --> BRANCH{开关}

    BRANCH -- "关闭" --> RULE_SPLIT["规则拆分<br/>ruleBasedSplit"]
    BRANCH -- "开启" --> LLM["LLM 改写+拆分<br/>callLLMRewriteAndSplit"]

    RULE_SPLIT --> RESULT["RewriteResult<br/>rewrite: 归一化后问题<br/>subQuestions: 子问题列表"]
    LLM --> RESULT

    RESULT --> CONTEXT["StreamChatContext.rewriteResult"]
    CONTEXT --> NEXT["后续：resolveIntents"]
```

---

## 关键配置项

| 配置 | 说明 | 默认值 |
|------|------|--------|
| `rag.query-rewrite.enabled` | 是否启用 LLM 查询改写 | `true` |
| LLM `temperature` | 改写请求的温度参数 | `0.1` |
| LLM `topP` | 改写请求的 top_p 参数 | `0.3` |
| LLM `thinking` | 是否启用思维链 | `false` |
| 历史消息截断 | 最多保留最近 4 条（2轮对话） | 系统过滤 USER+ASSISTANT |
| 缓存过期 | 术语映射 Redis 缓存有效期 | 7 天 |

---

## 异常兜底策略

| 场景 | 兜底行为 |
|------|----------|
| `queryRewriteEnabled=false` | 仅做术语归一化 + 规则拆分，不调用 LLM |
| LLM 调用抛出异常 | 使用归一化问题作为改写结果，子问题=归一化问题 |
| LLM 返回 JSON 解析失败 | 同上兜底 |
| `rewrite` 字段为空 | 视为解析失败，走兜底 |
| `sub_questions` 为空/缺失 | 子问题列表 = `[rewrite]`，即不拆分 |
| 术语映射缓存/DB 均不可用 | 跳过归一化，使用原始问题 |
| 归一化映射 `matchType≠1` | 跳过该条规则 |

---

## 类与方法索引

| 类 | 方法 | 职责 | 注解 |
|----|------|------|------|
| `StreamChatPipeline` | `rewriteQuery(ctx)` | 管道入口，调用 service 并设置上下文 | — |
| `QueryRewriteService` | `rewrite(question)` | 接口：仅改写，返回字符串 | — |
| `QueryRewriteService` | `rewriteWithSplit(question)` | 接口：改写+拆分，无历史 | — |
| `QueryRewriteService` | `rewriteWithSplit(question, history)` | 接口：改写+拆分，含历史（管道实际调用） | — |
| `MultiQuestionRewriteService` | `rewrite(question)` | 实现：调用 rewriteAndSplit → 取 rewrittenQuestion | `@RagTraceNode(name=query-rewrite)` |
| `MultiQuestionRewriteService` | `rewriteWithSplit(question)` | 实现：调用 rewriteAndSplit（无历史） | — |
| `MultiQuestionRewriteService` | `rewriteWithSplit(question, history)` | **主入口**：开关判断 → 归一化 → LLM/规则 | `@RagTraceNode(name=query-rewrite-and-split)` |
| `MultiQuestionRewriteService` | `rewriteAndSplit(question)` | 私有：无历史版本核心逻辑（被 rewrite 和无历史 rewriteWithSplit 调用） | — |
| `MultiQuestionRewriteService` | `callLLMRewriteAndSplit(normalized, original, history)` | 调用 LLM 进行改写+拆分 | — |
| `MultiQuestionRewriteService` | `buildRewriteRequest(systemPrompt, question, history)` | 组装 ChatRequest（含历史截断） | — |
| `MultiQuestionRewriteService` | `parseRewriteAndSplit(raw)` | 解析 LLM JSON 输出 → RewriteResult | — |
| `MultiQuestionRewriteService` | `ruleBasedSplit(question)` | 规则拆分兜底：按分隔符拆分多问句 | — |
| `QueryTermMappingService` | `normalize(text)` | 术语归一化：遍历规则做安全替换 | — |
| `QueryTermMappingService` | `loadMappings()` | 加载映射规则（缓存优先→DB回填） | — |
| `QueryTermMappingCacheManager` | `getMappingsFromCache()` | Redis 缓存读取（key=`ragent:query-term:mappings`） | — |
| `QueryTermMappingCacheManager` | `saveMappingsToCache(mappings)` | Redis 缓存回填（7天过期） | — |
| `QueryTermMappingCacheManager` | `clearCache()` | 清除缓存（映射规则增删改时调用） | — |
| `QueryTermMappingUtil` | `applyMapping(text, source, target)` | 安全替换：防重复归一化（若已是target则不替换） | — |
| `LLMResponseCleaner` | `stripMarkdownCodeFence(raw)` | 去除 Markdown 代码围栏（```json ... ```） | — |
| `PromptTemplateLoader` | `load(path)` | 从 classpath 加载提示词模板（带 ConcurrentHashMap 缓存） | — |
| `PromptTemplateLoader` | `render(path, slots)` | 加载模板 + 填充变量 + 清理 | — |
| `PromptTemplateLoader` | `loadSection(path, section)` | 加载模板中指定 section | — |
| `PromptTemplateLoader` | `renderSection(path, section, slots)` | 加载 section + 填充变量 | — |
| `RewriteResult` | record | `rewrittenQuestion + subQuestions` 两个字段 | — |
| `RAGConstant` | `QUERY_REWRITE_AND_SPLIT_PROMPT_PATH` | 常量：`"prompt/user-question-rewrite.st"` | — |
| `RAGConfigProperties` | `queryRewriteEnabled` | 配置：`rag.query-rewrite.enabled`（默认 true） | — |
| `QueryTermMappingDO` | 实体类 | 映射规则数据结构（sourceTerm/targetTerm/matchType/priority/enabled/domain） | — |
| `ChatRequest` | builder | 通用大模型请求对象（messages/temperature/topP/topK/maxTokens/thinking/enableTools） | — |
| `RagTraceNode` | 注解 | RAG 链路追踪节点标记（AOP切面记录耗时、入参、出参） | 属性：name, type |

---

## LLM 提示词模板（user-question-rewrite.st）核心要点

- **角色**：查询改写助手，用于 RAG 检索阶段
- **输出格式**：严格 JSON `{ rewrite, should_split, sub_questions }`
- **改写规则**：
  - 保留专有名词、关键限制、业务场景
  - 删除礼貌用语、回答指令、无关描述
  - 禁止添加原文没有的条件/维度/假设
- **拆分规则**：
  - 多问号、显式列举、分号/换行 → 拆分
  - 抽象对比、笼统询问、不确定 → 不拆分
- **指代消解**：结合历史消息还原指代词（"它"、"这个"）
