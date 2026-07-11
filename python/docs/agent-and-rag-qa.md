# Agent 与 RAG 核心问题详解

> 配套代码：[`src/learning_py/agent/`](../src/learning_py/agent/) |
> 配套文档：[`agent-landing-guide.md`](agent-landing-guide.md)
>
> 十个高频问题的深入解析，涵盖 Agent 架构、RAG 工程、上下文管理、幻觉治理等核心主题。

---

## 1. ReAct 中工具报错怎么处理，保证循环不中断

核心思想：**工具报错不是系统异常，而是 Agent 的一次"观察"**——让 LLM 看到错误信息，
它会自行决定下一步（换个工具、换个参数、或直接用已有信息回答）。

### 1.1 三层防护架构

```
Layer 1: 工具内部 → 永远返回字符串，不抛异常
Layer 2: call_tool → try/except 兜底，把任何异常转成 OBSERVATION
Layer 3: Agent 循环 → Prompt 告诉 LLM 怎么处理工具失败
```

### 1.2 Layer 1：工具内部不抛异常

工具的返回值会被作为 OBSERVATION 喂回 LLM，所以工具失败也要返回字符串，
让模型能看到"这条路走不通"，而不是把整个 Agent 弄崩：

```python
def tool_calc(expression: str) -> str:
    try:
        tokens = tokenize(expression)
        result = parse_and_eval(tokens)
        return str(result)
    except (ValueError, ZeroDivisionError) as e:
        # ✅ 返回错误字符串，不抛异常
        return f"（calc 错误：{e}）"
```

### 1.3 Layer 2：call_tool 兜底

即使工具内部忘了处理异常，调度层也要兜住：

```python
# ❌ 原始版本：工具内部异常会直接崩掉整个 Agent
def call_tool(toolbox, name, arg):
    if name not in toolbox:
        return f"（无此工具：{name}）"
    return toolbox[name](arg)  # 如果抛异常，Agent 就崩了

# ✅ 改进版本：任何异常都变成 OBSERVATION
def call_tool(toolbox, name, arg):
    if name not in toolbox:
        return f"（错误：无此工具 '{name}'，可用工具：{list(toolbox.keys())}）"
    try:
        return toolbox[name](arg)
    except Exception as e:
        return f"（工具 {name} 执行出错：{type(e).__name__}: {e}）"
```

### 1.4 Layer 3：Prompt 引导 LLM 处理错误

在 System Prompt 或 ReAct Prompt 中加入错误处理指令：

```python
prompt += (
    "重要规则：\n"
    "- 如果 OBSERVATION 包含"错误"或"出错"，分析原因后尝试不同的参数或工具\n"
    "- 如果连续 2 次工具调用都失败，用已有信息直接给出 FINAL 答案\n"
    "- 不要重复调用同一个工具和相同参数\n"
)
```

### 1.5 实际效果

```
用户: "帮我算 1/0"

THOUGHT: 用 calc 算一下
ACTION: calc(1/0)
OBSERVATION: （工具 calc 执行出错：ZeroDivisionError: division by zero）
                                    ↑ 错误变成了一条普通的 OBSERVATION

THOUGHT: 除以零了，数学上无意义，直接告诉用户
FINAL: 1/0 在数学上没有定义（除数不能为零）。
                                    ↑ LLM 自己消化了错误，给出了合理回答
```

### 1.6 进阶：可恢复错误的有限重试

对于网络超时等瞬时错误，可以在 `call_tool` 层面加有限重试：

```python
def call_tool(toolbox, name, arg, max_retries=2):
    if name not in toolbox:
        return f"（错误：无此工具 '{name}'）"
    for attempt in range(max_retries + 1):
        try:
            return toolbox[name](arg)
        except TimeoutError:
            if attempt < max_retries:
                continue  # 超时可以重试
            return f"（工具 {name} 超时，已重试 {max_retries} 次仍失败）"
        except Exception as e:
            # 非超时异常不重试，直接返回
            return f"（工具 {name} 出错：{type(e).__name__}: {e}）"
```

---

## 2. PDF 切块：表格、跨页段落处理

PDF 的两大难点：

```
难点 1：表格被 PDF 解析器拆成散乱的文本行
  原始 PDF 表格:        解析后变成:
  ┌──────┬──────┐       "产品名称 价格"
  │产品名│ 价格 │  →    "iPhone 15 6999"
  │iPhone│ 6999 │       "MacBook 12999"
  └──────┴──────┘

难点 2：一个段落跨了两页，被强行切断
  第 1 页末尾: "Python 是一种解释型的高级编程语-"
  第 2 页开头: "言，广泛用于数据分析..."
```

### 2.1 解决方案：表格单独提取 + 跨页合并

```python
import pdfplumber

class PDFChunker:
    def chunk(self, pdf_path: str) -> list[dict]:
        chunks = []
        full_text_lines = []

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                # ── 表格单独提取 ──
                tables = page.extract_tables()
                for table in tables:
                    md_table = self._table_to_markdown(table)
                    chunks.append({
                        "content": md_table,
                        "type": "table",
                        "page": page.page_number,
                    })

                # ── 正文提取（排除表格区域）──
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text:
                    full_text_lines.append(text)

        # ── 跨页段落合并 ──
        full_text = self._merge_cross_page_text(full_text_lines)

        # ── 正文递归分割 ──
        text_chunks = self._recursive_split(full_text, chunk_size=500, overlap=80)
        for tc in text_chunks:
            chunks.append({"content": tc, "type": "text"})

        return chunks

    def _table_to_markdown(self, table: list[list]) -> str:
        """表格 → Markdown，保留结构信息"""
        if not table:
            return ""
        header = table[0]
        rows = table[1:]

        md = "| " + " | ".join(str(c or "") for c in header) + " |\n"
        md += "| " + " | ".join("---" for _ in header) + " |\n"
        for row in rows:
            md += "| " + " | ".join(str(c or "") for c in row) + " |\n"
        return md

    def _merge_cross_page_text(self, pages: list[str]) -> str:
        """合并跨页断行"""
        if not pages:
            return ""
        merged = pages[0]
        for next_page in pages[1:]:
            if merged.rstrip().endswith("-"):
                # 连字符断字：去掉连字符直接拼接
                merged = merged.rstrip()[:-1] + next_page.lstrip()
            elif merged.rstrip()[-1:] not in ("。", ".", "！", "!", "？", "?", "\n"):
                # 不是句子结尾，说明段落跨页了
                merged = merged.rstrip() + next_page.lstrip()
            else:
                merged = merged + "\n" + next_page
        return merged

    def _recursive_split(self, text, chunk_size, overlap):
        """递归分割：先按双换行，再按单换行，再按句号"""
        separators = ["\n\n", "\n", "。", ". ", "；", "; "]
        return self._split_with_separators(text, separators, chunk_size, overlap)

    def _split_with_separators(self, text, separators, chunk_size, overlap):
        if not separators or len(text) <= chunk_size:
            return [text] if text.strip() else []

        sep = separators[0]
        parts = text.split(sep)
        chunks = []
        current = ""

        for part in parts:
            candidate = current + sep + part if current else part
            if len(candidate) > chunk_size and current:
                chunks.append(current.strip())
                current = current[-overlap:] + sep + part if overlap else part
            else:
                current = candidate

        if current.strip():
            chunks.append(current.strip())

        result = []
        for c in chunks:
            if len(c) > chunk_size * 1.5:
                result.extend(
                    self._split_with_separators(c, separators[1:], chunk_size, overlap)
                )
            else:
                result.append(c)
        return result
```

### 2.2 处理效果

```
输入 PDF：
  第 1 页：正文段落 + 一张价格表
  第 2 页：段落跨页续接 + 正文

输出 chunks：
  [0] {"type": "table",  "content": "| 产品 | 价格 |\n| --- | --- |\n| iPhone | 6999 |..."}
  [1] {"type": "text",   "content": "这是第一段完整的正文..."}
  [2] {"type": "text",   "content": "这个段落跨了两页但已被正确合并..."}  ← 跨页修复
  [3] {"type": "text",   "content": "第二页剩余的正文..."}
```

---

## 3. 语义分割分块

核心思想：**计算相邻句子的 embedding 相似度，在相似度骤降的地方切分**——
说明话题变了。

### 3.1 完整实现

```python
import numpy as np

class SemanticChunker:
    """基于 embedding 相似度检测话题切换点来分块"""

    def __init__(self, embed_fn, threshold_percentile: int = 25):
        self.embed_fn = embed_fn  # 函数：str -> list[float]
        self.threshold_percentile = threshold_percentile

    def chunk(self, text: str) -> list[str]:
        # 1. 按句子分割
        sentences = self._split_sentences(text)
        if len(sentences) <= 3:
            return [text]

        # 2. 每个句子算 embedding
        embeddings = [self.embed_fn(s) for s in sentences]

        # 3. 计算相邻句子的余弦相似度
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = self._cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)

        # 4. 找"话题切换点"：相似度低于阈值的位置
        threshold = np.percentile(similarities, self.threshold_percentile)
        breakpoints = [
            i + 1 for i, sim in enumerate(similarities) if sim < threshold
        ]

        # 5. 按切换点分块
        chunks = []
        start = 0
        for bp in breakpoints:
            chunk_text = "".join(sentences[start:bp])
            if chunk_text.strip():
                chunks.append(chunk_text.strip())
            start = bp
        remaining = "".join(sentences[start:])
        if remaining.strip():
            chunks.append(remaining.strip())

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        import re
        parts = re.split(r'((?<=[。！？.!?])\s*)', text)
        sentences = []
        for i in range(0, len(parts) - 1, 2):
            sentences.append(parts[i] + parts[i + 1])
        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1])
        return sentences

    def _cosine_similarity(self, a, b) -> float:
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))
```

### 3.2 使用示例

```python
text = """
Python 是一种解释型的高级编程语言。它的设计哲学强调代码可读性。
Python 支持多种编程范式，包括面向对象、函数式和过程式编程。

机器学习是人工智能的一个子领域。它使用统计方法让计算机从数据中学习。
常见的机器学习框架有 TensorFlow、PyTorch 和 scikit-learn。

今天天气很好，适合出去散步。公园里的樱花开了，很多人在拍照。
"""

chunker = SemanticChunker(embed_fn=your_embedding_function, threshold_percentile=30)
chunks = chunker.chunk(text)
# 结果：3 个 chunk → Python 介绍 / 机器学习 / 天气
```

### 3.3 相似度变化曲线

```
相似度
1.0 ┤
    │ ████
0.8 ┤ ████ ████
    │ ████ ████
0.6 ┤ ████ ████           ████
    │ ████ ████           ████ ████
0.4 ┤ ████ ████           ████ ████
    │ ████ ████      ↓    ████ ████     ↓
0.2 ┤ ████ ████ ████████  ████ ████ ████████
    │ ████ ████ ████████  ████ ████ ████████
0.0 ┼─────────────────────────────────────────
     句1  句2  句3  句4   句5  句6  句7  句8
     ├─ Python ─┤ 切 ├─ ML ─┤ 切 ├─ 天气 ─┤
              这里切           这里切
```

---

## 4. 代码分块

代码不能按字符数硬切——按语法结构（函数、类）切才有意义。

### 4.1 基于 AST 语法树的 Python 代码分块

```python
import ast

class PythonCodeChunker:
    """基于 AST 语法树的 Python 代码分块器"""

    def chunk(self, source_code: str, file_path: str = "") -> list[dict]:
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return self._fallback_split(source_code, file_path)

        chunks = []
        lines = source_code.splitlines()

        # 提取 import 块（作为每个 chunk 的共享上下文）
        import_lines = self._extract_imports(tree, lines)
        import_context = "\n".join(import_lines)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunk_text = self._extract_node_source(node, lines)
                chunks.append({
                    "content": f"{import_context}\n\n{chunk_text}",
                    "type": "function",
                    "name": node.name,
                    "file": file_path,
                    "line_start": node.lineno,
                    "line_end": node.end_lineno,
                })

            elif isinstance(node, ast.ClassDef):
                class_source = self._extract_node_source(node, lines)

                if len(class_source) > 1000:
                    # 大类拆成方法级 chunk
                    class_header = self._extract_class_header(node, lines)
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_source = self._extract_node_source(item, lines)
                            chunks.append({
                                "content": f"{import_context}\n\n{class_header}\n\n    {method_source}",
                                "type": "method",
                                "name": f"{node.name}.{item.name}",
                                "file": file_path,
                                "line_start": item.lineno,
                                "line_end": item.end_lineno,
                            })
                else:
                    chunks.append({
                        "content": f"{import_context}\n\n{class_source}",
                        "type": "class",
                        "name": node.name,
                        "file": file_path,
                        "line_start": node.lineno,
                        "line_end": node.end_lineno,
                    })

        return chunks

    def _extract_imports(self, tree, lines) -> list[str]:
        result = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                result.append(lines[node.lineno - 1])
        return result

    def _extract_node_source(self, node, lines) -> str:
        return "\n".join(lines[node.lineno - 1 : node.end_lineno])

    def _extract_class_header(self, node, lines) -> str:
        """提取类签名 + docstring"""
        header_end = node.lineno
        for item in node.body:
            if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
                header_end = item.end_lineno  # docstring
                break
            else:
                break
        return "\n".join(lines[node.lineno - 1 : header_end])

    def _fallback_split(self, source, file_path) -> list[dict]:
        """语法解析失败时退化为按空行分割"""
        blocks = source.split("\n\n")
        return [{"content": b, "type": "block", "file": file_path}
                for b in blocks if b.strip()]
```

### 4.2 实际效果

以仓库中的 `tools.py`（139 行）为例：

```
输入：tools.py

输出 chunks：
  [0] type=function  name="tool_search"    line=29~42
      content: "import re\n...\n\ndef tool_search(query):\n    ..."
               ↑ import 上下文自动附加

  [1] type=function  name="tool_calc"      line=45~98
      content: "import re\n...\n\ndef tool_calc(expression):\n    ..."

  [2] type=function  name="tool_translate"  line=104~113
      content: "import re\n...\n\ndef tool_translate(text):\n    ..."

  [3] type=function  name="call_tool"       line=135~138
      content: "...\ndef call_tool(toolbox, name, arg):\n    ..."
```

每个函数是一个独立的 chunk，都附带了 import 上下文，
检索命中时 LLM 能直接理解函数在做什么。

### 4.3 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 分割粒度 | 函数级 / 方法级 | 一个函数是最小的"完整语义单元" |
| import 处理 | 附加到每个 chunk | 缺少 import 上下文 LLM 无法理解类型 |
| 大类处理 | 拆成方法级 + 类签名 | 整个大类作为 chunk 噪声太多 |
| 语法错误 | 退化为按空行切 | 不能因为一个文件解析失败就丢掉所有内容 |
| 元数据 | 保留文件名 + 行号 | 方便溯源和跳转 |
