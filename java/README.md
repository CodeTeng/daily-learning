# Java 子项目

基于 Spring Boot 3.3 + Java 17 的最小学习工程，配合 `docs/` 中的笔记，用来复现并验证并发 / 异步 / WebSocket 等主题的原理。

## 目录结构

```
java/
├── README.md
├── pom.xml
├── docs/                                     # Java 相关知识笔记
│   ├── cas-and-longadder.md
│   ├── http2-and-hol-blocking.md
│   ├── java-threadlocal.md
│   ├── java-volatile.md
│   └── linux-troubleshooting.md
└── src/main/
    ├── java/com/example/demo/
    │   ├── DemoApplication.java              # Spring Boot 启动类
    │   ├── async/                            # @Async / 线程池 / 自定义注解
    │   ├── concurrent/                       # 可见性、原子性、DCL 等并发示例
    │   │   └── threadlocal/                  # ThreadLocal 系列演示
    │   └── ws/                               # WebSocket Server + 自测控制器
    └── resources/
        ├── application.properties
        └── static/chat.html                  # WebSocket 自测页面
```

## 环境

- JDK 17+
- Maven 3.9+（或使用 IDE 自带）

## 常用命令

```bash
cd java

# 编译
mvn -q -DskipTests package

# 启动 Spring Boot 应用（默认 8080）
mvn spring-boot:run

# 跑单个并发示例（含 main 方法的类）
mvn -q exec:java -Dexec.mainClass=com.example.demo.concurrent.VisibilityDemo
```

启动后可访问：

- WebSocket 自测页：<http://localhost:8080/chat.html>
- 异步接口示例：见 `async/UserController.java`

## 与 docs 的对应关系

| 笔记 | 配套代码 |
| --- | --- |
| `docs/java-volatile.md` | `concurrent/VisibilityDemo.java`、`concurrent/DclSingletonDemo.java` |
| `docs/cas-and-longadder.md` | `concurrent/AtomicityDemo.java` |
| `docs/java-threadlocal.md` | `concurrent/threadlocal/*.java` |
| `docs/http2-and-hol-blocking.md` | `ws/*`（用 WebSocket 对照传统 HTTP/2 多路复用模型） |
| `docs/linux-troubleshooting.md` | 通用排查命令记录，无独立代码 |

新增主题时，请尽量保持「一篇文档 + 一组可运行 demo」的成对结构。
