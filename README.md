# learning

个人技术学习仓库，按语言生态拆分为多个独立子项目，互不耦合，可分别打开、构建与运行。

## 仓库布局

```
learning/
├── README.md          # 当前文件：总览与导航
├── java/              # Java 子项目（Spring Boot 3 + JDK 17，Maven 管理）
│   ├── README.md
│   ├── pom.xml
│   ├── docs/          # Java / JVM / 网络相关笔记
│   └── src/...
├── python/            # Python 子项目（uv 管理，src-layout）
│   ├── README.md
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── docs/          # Python 相关笔记
│   ├── src/learning_py/...
│   └── tests/
└── go/                # Go 子项目（Go modules 管理）
    ├── README.md
    ├── go.mod
    ├── docs/          # Go 并发相关笔记
    ├── cmd/           # 每个子目录一个独立 main
    └── internal/      # 可复用工具 + 单元测试
```

每个子项目都是自洽的：自己的依赖管理工具、自己的 `docs/`、自己的 README。

## 快速开始

### Java

```bash
cd java
mvn spring-boot:run
```

详见 [`java/README.md`](./java/README.md)。

### Python

```bash
cd python
uv sync
uv run learning-py
```

详见 [`python/README.md`](./python/README.md)。

## 内容索引

### Java / JVM / 网络

- [`java/docs/java-volatile.md`](./java/docs/java-volatile.md) — `volatile` 的可见性 / 有序性语义
- [`java/docs/cas-and-longadder.md`](./java/docs/cas-and-longadder.md) — CAS 原理与 `LongAdder` 分段累加
- [`java/docs/java-threadlocal.md`](./java/docs/java-threadlocal.md) — `ThreadLocal` 实现、内存泄漏与线程池踩坑
- [`java/docs/http2-and-hol-blocking.md`](./java/docs/http2-and-hol-blocking.md) — HTTP/2 多路复用与队头阻塞
- [`java/docs/linux-troubleshooting.md`](./java/docs/linux-troubleshooting.md) — 线上 Linux 常用排查命令清单

### Python

- [`python/docs/python-gil.md`](./python/docs/python-gil.md) — GIL 的影响与 IO/CPU 密集场景的取舍

## 约定

1. **一篇笔记 + 一段可运行示例**：尽量让 `docs/` 里的每篇文档都有 `src/` 里对应的最小复现代码。
2. **子项目隔离**：不要在仓库根放跨语言的构建脚本；如未来要加跨语言工具，再起一个独立目录。
3. **提交信息使用前缀**：`java: ...` / `python: ...` / `docs: ...` / `chore: ...`，便于按主题翻历史。

## 工具栈

| 子项目 | 语言版本 | 依赖管理 | 运行 |
| --- | --- | --- | --- |
| `java/` | JDK 17 | Maven | `mvn spring-boot:run` |
| `python/` | Python ≥ 3.11 | [uv](https://docs.astral.sh/uv/) | `uv run ...` |
