# handleGuidance 完整流程详解

## 概述

`handleGuidance` 是 `StreamChatPipeline` 中的**歧义引导阶段**，在记忆加载、查询改写、意图解析之后执行。其核心目标是：**当用户提问存在品类歧义时，生成引导式澄清提示并通过流式回调返回给用户，短路后续检索和响应流程**。

---

## 顶层调用流程

`handleGuidance` 在管道中的位置：

```
execute()
  ├── loadMemory(ctx)           — 加载对话记忆
  ├── rewriteQuery(ctx)         — 改写 & 拆分查询
  ├── resolveIntents(ctx)       — 意图解析
  ├── handleGuidance(ctx)       — ◀ 歧义引导（本流程）
  │     └── 若触发 → return（短路）
  ├── handleSystemOnly(ctx)     — 纯系统意图处理
  ├── retrieve(ctx)             — 检索
  ├── handleEmptyRetrieval()    — 空检索处理
  └── streamRagResponse()       — 流式 RAG 响应
```

---

## handleGuidance 主流程图

```mermaid
flowchart TD
    START([handleGuidance 入口]) --> DETECT[guidanceService.detectAmbiguity\n传入: rewrittenQuestion + subIntents]
    DETECT --> DECISION{GuidanceDecision\n.isPrompt()?}
    DECISION -- false --> NOT_HANDLED([return false\n管道继续执行])
    DECISION -- true --> SEND_PROMPT[callback.onContent(decision.getPrompt())]
    SEND_PROMPT --> COMPLETE[callback.onComplete()]
    COMPLETE --> HANDLED([return true\n管道短路结束])

    style START fill:#4CAF50,color:#fff
    style HANDLED fill:#2196F3,color:#fff
    style NOT_HANDLED fill:#FF9800,color:#fff
```

---

## detectAmbiguity 详细流程

```mermaid
flowchart TD
    START([detectAmbiguity 入口]) --> CHECK_ENABLED{guidanceProperties\n.enabled?}
    CHECK_ENABLED -- false --> NONE1([return GuidanceDecision.none])
    CHECK_ENABLED -- true --> FIND_GROUP[findAmbiguityGroup\n传入: question + subIntents]

    FIND_GROUP --> GROUP_RESULT{AmbiguityGroup\n是否为空?}
    GROUP_RESULT -- "group == null 或\nranked 为空" --> NONE2([return GuidanceDecision.none])
    GROUP_RESULT -- 有歧义组 --> BUILD_PROMPT[buildPrompt\n传入: topicName + ranked]

    BUILD_PROMPT --> PROMPT_RESULT[生成引导提示文本]
    PROMPT_RESULT --> RETURN_PROMPT([return GuidanceDecision.prompt\n含引导提示文本])

    style START fill:#4CAF50,color:#fff
    style NONE1 fill:#FF9800,color:#fff
    style NONE2 fill:#FF9800,color:#fff
    style RETURN_PROMPT fill:#2196F3,color:#fff
```

---

## findAmbiguityGroup 详细流程

```mermaid
flowchart TD
    START([findAmbiguityGroup 入口]) --> CHECK_SIZE{subIntents\n是否为空或\nsize != 1?}
    CHECK_SIZE -- 是 --> NULL1([return null])
    CHECK_SIZE -- 否（仅1个子意图） --> FILTER[filterCandidates\n过滤 KB 类型 + 最低分数]

    FILTER --> CHECK_CANDIDATES{candidates\n.size < 2?}
    CHECK_CANDIDATES -- 是 --> NULL2([return null])
    CHECK_CANDIDATES -- 否 --> BUILD_MAP[构建 systemBest Map\n按系统节点ID分组\n保留每组最高分]

    BUILD_MAP --> SORT[按分数降序排列\n得到 ranked 列表]
    SORT --> CHECK_RANKED{ranked\n.size < 2?}
    CHECK_RANKED -- 是 --> NULL3([return null])
    CHECK_RANKED -- 否 --> SKIP_CHECK[shouldSkipGuidance\n判断是否应跳过]

    SKIP_CHECK --> SKIP_RESULT{是否跳过?}
    SKIP_RESULT -- 是 --> NULL4([return null])
    SKIP_RESULT -- 否 --> CONFIRM[confirmAmbiguity\n确认是否歧义]

    CONFIRM --> CONFIRM_RESULT{确认歧义?}
    CONFIRM_RESULT -- false --> NULL5([return null])
    CONFIRM_RESULT -- true --> TRIM[trimRankedOptions\n截断到 maxOptions 上限]

    TRIM --> BUILD_GROUP[构建 AmbiguityGroup\ntopicName + trimmedRanked]
    BUILD_GROUP --> RETURN_GROUP([return AmbiguityGroup])

    style START fill:#4CAF50,color:#fff
    style NULL1 fill:#FF9800,color:#fff
    style NULL2 fill:#FF9800,color:#fff
    style NULL3 fill:#FF9800,color:#fff
    style NULL4 fill:#FF9800,color:#fff
    style NULL5 fill:#FF9800,color:#fff
    style RETURN_GROUP fill:#2196F3,color:#fff
```

---

## shouldSkipGuidance 详细流程

```mermaid
flowchart TD
    START([shouldSkipGuidance 入口]) --> CHECK_TOP{top 分数\n<= 0?}
    CHECK_TOP -- 是 --> SKIP1([return true\n跳过引导])
    CHECK_TOP -- 否 --> CALC_RATIO[计算 ratio =\nsecond.score / top.score]

    CALC_RATIO --> CHECK_RATIO{ratio <\nthreshold - margin?}
    CHECK_RATIO -- 是 --> SKIP2([return true\n意图明确，跳过引导])
    CHECK_RATIO -- 否 --> CHECK_QUESTION{question\n非空?}

    CHECK_QUESTION -- 否 --> NO_SKIP([return false\n不跳过])
    CHECK_QUESTION -- 是 --> GET_DOMAINS[提取 ranked 中各节点的\nDOMAIN 级名称]

    GET_DOMAINS --> NORMALIZE[标准化用户问题\nnormalizeName]
    NORMALIZE --> MATCH[遍历 domainNames\n构建别名 buildSystemAliases\n检查问题是否包含]

    MATCH --> MATCH_RESULT{问题包含\n系统域名?}
    MATCH_RESULT -- 是 --> SKIP3([return true\n用户已明确指定系统])
    MATCH_RESULT -- 否 --> NO_SKIP2([return false\n不跳过])

    style START fill:#4CAF50,color:#fff
    style SKIP1 fill:#FF9800,color:#fff
    style SKIP2 fill:#9C27B0,color:#fff
    style SKIP3 fill:#9C27B0,color:#fff
    style NO_SKIP fill:#2196F3,color:#fff
    style NO_SKIP2 fill:#2196F3,color:#fff
```

### 分数比值区间说明

| 区间 | ratio 范围 | 行为 |
|------|-----------|------|
| **明确区** | ratio < threshold - margin | 跳过引导（意图明确） |
| **边界区** | threshold - margin ≤ ratio < threshold | 进入 LLM 二次确认 |
| **歧义区** | ratio ≥ threshold | 直接判定歧义 |

> 默认配置：threshold = 0.8, margin = 0.15
> - 明确区：ratio < 0.65
> - 边界区：0.65 ≤ ratio < 0.8
> - 歧义区：ratio ≥ 0.8

---

## confirmAmbiguity 详细流程

```mermaid
flowchart TD
    START([confirmAmbiguity 入口]) --> CHECK_TOP2{top 分数\n<= 0?}
    CHECK_TOP2 -- 是 --> NOT_AMBIG[return false]
    CHECK_TOP2 -- 否 --> CALC_RATIO2[计算 ratio =\nsecond.score / top.score]

    CALC_RATIO2 --> ZONE_CHECK{ratio 所在区间?}

    ZONE_CHECK -- "ratio >= threshold\n歧义区" --> AMBIGUOUS([return true\n直接判定歧义])

    ZONE_CHECK -- "threshold - margin\n<= ratio < threshold\n边界区" --> LLM_CHECK[ambiguityLLMChecker\n.checkAmbiguity]

    ZONE_CHECK -- "ratio < threshold - margin\n明确区" --> NOT_AMBIG2([return false\n不歧义])

    LLM_CHECK --> LLM_RESULT([return LLM 判定结果])

    style START fill:#4CAF50,color:#fff
    style AMBIGUOUS fill:#F44336,color:#fff
    style NOT_AMBIG fill:#FF9800,color:#fff
    style NOT_AMBIG2 fill:#FF9800,color:#fff
    style LLM_RESULT fill:#9C27B0,color:#fff
```

---

## AmbiguityLLMChecker.checkAmbiguity 详细流程

```mermaid
flowchart TD
    START([checkAmbiguity 入口]) --> BUILD_CANDIDATES[buildCandidatesText\n格式化候选项文本:\n品类ID / 名称 / 路径 / 分数]

    BUILD_CANDIDATES --> RENDER_PROMPT[promptTemplateLoader.render\n渲染歧义确认 Prompt 模板\n变量: question + candidates]

    RENDER_PROMPT --> BUILD_REQUEST[构建 ChatRequest\ntemperature=0.1 / topP=0.3\nthinking=false]

    BUILD_REQUEST --> CALL_LLM[llmService.chat\n同步调用 LLM]

    CALL_LLM --> PARSE{解析返回结果}
    PARSE -- 成功 --> CLEAN[LLMResponseCleaner\n.stripMarkdownCodeFence]
    CLEAN --> JSON_PARSE[JsonParser.parseString]

    JSON_PARSE --> CHECK_JSON{是否为\nJSONObject?}
    CHECK_JSON -- 否 --> WARN1[日志警告:\n返回非 JSON 对象] --> DEGRADE1([降级: return true\n触发澄清])

    CHECK_JSON -- 是 --> CHECK_FIELD{含 ambiguous\n字段?}
    CHECK_FIELD -- 是 --> GET_RESULT[读取 ambiguous 布尔值]
    GET_RESULT --> RETURN_RESULT([return ambiguous])

    CHECK_FIELD -- 否 --> WARN2[日志警告:\n缺少 ambiguous 字段] --> DEGRADE2([降级: return true\n触发澄清])

    PARSE -- 异常 --> CATCH[catch Exception]
    CATCH --> WARN3[日志警告:\nLLM 调用失败] --> DEGRADE3([降级: return true\n触发澄清])

    style START fill:#4CAF50,color:#fff
    style RETURN_RESULT fill:#2196F3,color:#fff
    style DEGRADE1 fill:#F44336,color:#fff
    style DEGRADE2 fill:#F44336,color:#fff
    style DEGRADE3 fill:#F44336,color:#fff
```

> **降级策略**：LLM 调用失败或返回格式异常时，**默认触发澄清**（return true），宁可多问一句也不漏判歧义。

---

## buildPrompt 详细流程

```mermaid
flowchart TD
    START([buildPrompt 入口\ntopicName + ranked]) --> RENDER_OPTS[renderOptions\n遍历 ranked 列表]

    RENDER_OPTS --> LOOP[对每个 NodeScore:\nresolveOptionDisplay]

    LOOP --> DISPLAY_CHECK{node.fullPath\n非空?}
    DISPLAY_CHECK -- 是 --> USE_PATH[使用 fullPath\n作为显示文本]
    DISPLAY_CHECK -- 否 --> USE_NAME[使用 name 或 id\n作为显示文本]

    USE_PATH --> APPEND[格式化为:\n1) 显示文本\n2) 显示文本 ...]
    USE_NAME --> APPEND

    APPEND --> TEMPLATE[promptTemplateLoader.render\n渲染 GUIDANCE_PROMPT_PATH 模板\n变量: topic_name + options]

    TEMPLATE --> RESULT([return 引导提示文本])

    style START fill:#4CAF50,color:#fff
    style RESULT fill:#2196F3,color:#fff
```

---

## filterCandidates 详细流程

```mermaid
flowchart TD
    START([filterCandidates 入口\nnodeScores 列表]) --> CHECK_EMPTY{scores\n是否为空?}
    CHECK_EMPTY -- 是 --> EMPTY([return 空列表])
    CHECK_EMPTY -- 否 --> FILTER_KB[NodeScoreFilters.kb\n过滤条件:]
    FILTER_KB --> DETAIL["1. score >= INTENT_MIN_SCORE\n2. node 非空\n3. node.isKB() == true"]
    DETAIL --> RESULT([return 过滤后的 KB 候选列表])

    style START fill:#4CAF50,color:#fff
    style EMPTY fill:#FF9800,color:#fff
    style RESULT fill:#2196F3,color:#fff
```

---

## resolveSystemNodeId 详细流程

```mermaid
flowchart TD
    START([resolveSystemNodeId 入口\nIntentNode node]) --> INIT[current = node\nparent = fetchParent]
    INIT --> LOOP{遍历节点层级}
    LOOP --> CHECK_LEVEL{current.level\n== CATEGORY?}
    CHECK_LEVEL -- 是 --> CHECK_PARENT{parent == null\n或 parent.level\n== DOMAIN?}
    CHECK_PARENT -- 是 --> RETURN_CAT([return current.id\n系统节点ID])
    CHECK_PARENT -- 否 --> MOVE_UP[current = parent\nparent = fetchParent]
    MOVE_UP --> LOOP

    CHECK_LEVEL -- 否 --> CHECK_NULL{parent\n== null?}
    CHECK_NULL -- 是 --> RETURN_CURRENT([return current.id\n到达根节点])
    CHECK_NULL -- 否 --> MOVE_UP

    style START fill:#4CAF50,color:#fff
    style RETURN_CAT fill:#2196F3,color:#fff
    style RETURN_CURRENT fill:#2196F3,color:#fff
```

---

## 完整流程总图

```mermaid
flowchart TD
    subgraph Pipeline["StreamChatPipeline.execute()"]
        A1[loadMemory] --> A2[rewriteQuery]
        A2 --> A3[resolveIntents]
        A3 --> A4[handleGuidance]
    end

    subgraph Guidance["handleGuidance(ctx)"]
        A4 --> B1[guidanceService.detectAmbiguity]
        B1 --> B2{isPrompt?}
        B2 -- false --> B3[return false]
        B2 -- true --> B4[callback.onContent]
        B4 --> B5[callback.onComplete]
        B5 --> B6[return true 短路]
    end

    subgraph Detect["detectAmbiguity"]
        B1 --> C1{enabled?}
        C1 -- no --> C2[GuidanceDecision.none]
        C1 -- yes --> C3[findAmbiguityGroup]
        C3 --> C4{group 有效?}
        C4 -- no --> C5[GuidanceDecision.none]
        C4 -- yes --> C6[buildPrompt]
        C6 --> C7[GuidanceDecision.prompt]
    end

    subgraph FindGroup["findAmbiguityGroup"]
        C3 --> D1{subIntents.size == 1?}
        D1 -- no --> D2[return null]
        D1 -- yes --> D3[filterCandidates - KB过滤]
        D3 --> D4{candidates >= 2?}
        D4 -- no --> D5[return null]
        D4 -- yes --> D6[构建 systemBest Map + 排序]
        D6 --> D7{ranked >= 2?}
        D7 -- no --> D8[return null]
        D7 -- yes --> D9[shouldSkipGuidance]
        D9 --> D10{跳过?}
        D10 -- yes --> D11[return null]
        D10 -- no --> D12[confirmAmbiguity]
        D12 --> D13{确认歧义?}
        D13 -- no --> D14[return null]
        D13 -- yes --> D15[trimRankedOptions]
        D15 --> D16[return AmbiguityGroup]
    end

    subgraph Skip["shouldSkipGuidance"]
        D9 --> E1{top <= 0?}
        E1 -- yes --> E2[skip]
        E1 -- no --> E3{ratio < 0.65?}
        E3 -- yes --> E4[skip 意图明确]
        E3 -- no --> E5{问题含系统名?}
        E5 -- yes --> E6[skip 用户已指定]
        E5 -- no --> E7[不跳过]
    end

    subgraph Confirm["confirmAmbiguity"]
        D12 --> F1{ratio >= 0.8?}
        F1 -- yes --> F2[true 歧义]
        F1 -- no --> F3{ratio >= 0.65?}
        F3 -- yes --> F4[LLM 二次确认]
        F3 -- no --> F5[false 不歧义]
        F4 --> F6[ambiguityLLMChecker]
    end

    subgraph LLM["AmbiguityLLMChecker"]
        F6 --> G1[构建候选项文本]
        G1 --> G2[渲染 Prompt 模板]
        G2 --> G3[llmService.chat]
        G3 --> G4{解析成功?}
        G4 -- yes --> G5[return ambiguous]
        G4 -- no --> G6[降级 return true]
    end

    style A4 fill:#4CAF50,color:#fff
    style B6 fill:#2196F3,color:#fff
    style B3 fill:#FF9800,color:#fff
```

---

## 关键配置项

| 配置项 | 配置前缀 | 默认值 | 说明 |
|--------|---------|--------|------|
| `enabled` | `rag.guidance.enabled` | `true` | 是否启用引导式问答 |
| `ambiguityScoreRatio` | `rag.guidance.ambiguity-score-ratio` | `0.8` | 歧义阈值，ratio ≥ 此值直接判定歧义 |
| `ambiguityMargin` | `rag.guidance.ambiguity-margin` | `0.15` | 边界缓冲区宽度，决定 LLM 二次确认区间 |
| `maxOptions` | `rag.guidance.max-options` | `6` | 单次最多展示的选项数量 |

---

## 核心数据结构

### GuidanceDecision

| 字段 | 类型 | 说明 |
|------|------|------|
| `action` | `Action` (NONE / PROMPT) | 决策类型 |
| `prompt` | `String` | 引导提示文本（仅 PROMPT 时有值） |

### AmbiguityGroup（内部 record）

| 字段 | 类型 | 说明 |
|------|------|------|
| `topicName` | `String` | 排名第一的系统名称 |
| `ranked` | `List<NodeScore>` | 按分数降序排列的系统候选列表 |

---

## 涉及的类与文件

| 类 | 文件路径 | 角色 |
|----|---------|------|
| `StreamChatPipeline` | `rag/service/pipeline/StreamChatPipeline.java` | 管道编排，调用 handleGuidance |
| `StreamChatContext` | `rag/service/pipeline/StreamChatContext.java` | 管道上下文，承载 rewriteResult、subIntents |
| `IntentGuidanceService` | `rag/core/guidance/IntentGuidanceService.java` | 歧义检测核心逻辑 |
| `GuidanceDecision` | `rag/core/guidance/GuidanceDecision.java` | 决策结果封装 |
| `AmbiguityLLMChecker` | `rag/core/guidance/AmbiguityLLMChecker.java` | LLM 歧义二次确认 |
| `GuidanceProperties` | `rag/config/GuidanceProperties.java` | 配置项 |
| `NodeScoreFilters` | `rag/core/intent/NodeScoreFilters.java` | 节点分数过滤工具 |
