# Java ThreadLocal 深入解析

> 本文系统讲解 `ThreadLocal`：从真实场景 → 内部数据结构 → 内存泄漏根源 → 跨线程传值方案，
> 对应 4 个可运行 demo 在 [`src/main/java/com/example/demo/concurrent/threadlocal/`](../src/main/java/com/example/demo/concurrent/threadlocal/)。
> 适合在读完 [`java-volatile.md`](./java-volatile.md) / [`cas-and-longadder.md`](./cas-and-longadder.md) 后阅读。

## 目录

- [一、ThreadLocal 解决什么问题](#一threadlocal-解决什么问题)
- [二、5 个真实场景用法](#二5-个真实场景用法)
  - [2.1 用户/请求上下文（最常见 ★）](#21-用户请求上下文最常见-)
  - [2.2 分布式追踪 traceId（MDC 内部就是 ThreadLocal）](#22-分布式追踪-traceidmdc-内部就是-threadlocal)
  - [2.3 SimpleDateFormat 线程安全包装](#23-simpledateformat-线程安全包装)
  - [2.4 数据库连接 / 事务管理](#24-数据库连接--事务管理)
  - [2.5 限流 / 熔断的调用链上下文](#25-限流--熔断的调用链上下文)
- [三、ThreadLocal 原理 —— 数据到底存在哪里](#三threadlocal-原理--数据到底存在哪里)
  - [3.1 错误的直觉](#31-错误的直觉)
  - [3.2 真实结构](#32-真实结构)
  - [3.3 set/get 源码逻辑](#33-setget-源码逻辑)
  - [3.4 ThreadLocalMap 的关键设计](#34-threadlocalmap-的关键设计)
- [四、内存泄漏 —— 弱引用与强引用的错配](#四内存泄漏--弱引用与强引用的错配)
  - [4.1 Entry 的特殊结构](#41-entry-的特殊结构)
  - [4.2 引用链全景图](#42-引用链全景图)
  - [4.3 泄漏发生的精确时序](#43-泄漏发生的精确时序)
  - [4.4 为什么线程池场景特别危险](#44-为什么线程池场景特别危险)
  - [4.5 JDK 的"被动清理"为什么不够](#45-jdk-的被动清理为什么不够)
  - [4.6 实测（demo: ThreadLocalLeakDemo）](#46-实测demo-threadlocalleakdemo)
  - [4.7 唯一解药：`try-finally remove()`](#47-唯一解药try-finally-remove)
- [五、跨线程传递 ThreadLocal 的值](#五跨线程传递-threadlocal-的值)
  - [5.1 普通 ThreadLocal 子线程拿不到](#51-普通-threadlocal-子线程拿不到)
  - [5.2 InheritableThreadLocal（父子线程）](#52-inheritablethreadlocal父子线程)
  - [5.3 线程池场景失效（demo: InheritableThreadLocalDemo）](#53-线程池场景失效demo-inheritablethreadlocaldemo)
  - [5.4 阿里 TransmittableThreadLocal（线程池场景标准方案）](#54-阿里-transmittablethreadlocal线程池场景标准方案)
  - [5.5 手写简化版 ContextRunnable（demo: ContextRunnableDemo）](#55-手写简化版-contextrunnabledemo-contextrunnabledemo)
  - [5.6 JDK 21+ ScopedValue（终极方案）](#56-jdk-21-scopedvalue终极方案)
  - [5.7 选型决策表](#57-选型决策表)
- [六、ThreadLocal vs 加锁共享 —— 本质对比](#六threadlocal-vs-加锁共享--本质对比)
- [七、最佳实践清单](#七最佳实践清单)
- [八、一句话总结](#八一句话总结)
- [附录：跑 demo 的命令](#附录跑-demo-的命令)
- [参考](#参考)

---

## 一、ThreadLocal 解决什么问题

并发编程里有两类截然不同的需求：

| 需求 | 工具 | 思路 |
|---|---|---|
| 多个线程**共享同一个**变量 | `volatile` / `synchronized` / `Atomic*` / `Lock` | 控制并发访问 |
| 每个线程**各自独立**的变量副本 | **`ThreadLocal`** | 干脆不共享，每个线程一份 |

`ThreadLocal` 的本质是**用空间换并发安全**：每个线程独立持有自己的副本，
天然不存在共享 → 天然无需加锁。

它解决两个核心痛点：

1. **隐式上下文传递**：避免在调用链上每个方法都加一个 `userId` 参数
2. **非线程安全对象的复用**：例如 `SimpleDateFormat` 不能被多线程共用，但每个线程持有一个就行

---

## 二、5 个真实场景用法

### 2.1 用户/请求上下文（最常见 ★）

每个 HTTP 请求有自己的 `userId`、`tenantId`，需要在 Service / Mapper 等任何层级随时取到，
但又不想每个方法都加参数：

```java
public class UserContext {
    private static final ThreadLocal<UserInfo> HOLDER = new ThreadLocal<>();

    public static void set(UserInfo u) { HOLDER.set(u); }
    public static UserInfo get() { return HOLDER.get(); }
    public static void clear() { HOLDER.remove(); }   // ★ 必须！防内存泄漏
}

@Component
public class AuthFilter implements Filter {
    public void doFilter(ServletRequest req, ServletResponse resp, FilterChain chain) {
        UserInfo user = parseToken(((HttpServletRequest) req).getHeader("Authorization"));
        UserContext.set(user);
        try {
            chain.doFilter(req, resp);    // 后续整个调用链都能拿到 user
        } finally {
            UserContext.clear();          // ★ finally 务必清理
        }
    }
}

public class OrderService {
    public void createOrder(...) {
        UserInfo user = UserContext.get();   // 不用从 controller 一路传
        log.info("user={} 创建订单", user.getId());
    }
}
```

**Spring Security 的 `SecurityContextHolder` 内部就是这套机制。**

对应 demo: [`ThreadLocalBasicDemo`](../src/main/java/com/example/demo/concurrent/threadlocal/ThreadLocalBasicDemo.java)

### 2.2 分布式追踪 traceId（MDC 内部就是 ThreadLocal）

slf4j 的 `MDC`（Mapped Diagnostic Context）就是 `ThreadLocal<Map<String,String>>`：

```java
String traceId = req.getHeader("X-Trace-Id");
if (traceId == null) traceId = UUID.randomUUID().toString();
MDC.put("traceId", traceId);
try {
    chain.doFilter(...);
} finally {
    MDC.clear();
}
```

logback 配置：

```xml
<pattern>%d [%X{traceId}] [%thread] %level - %msg%n</pattern>
<!--          ↑ 自动从 MDC ThreadLocal 取 -->
```

效果：

```
2026-05-02 23:45:01 [a3f8d-traceId] [http-nio-8080-exec-1] INFO - 订单创建成功
2026-05-02 23:45:01 [a3f8d-traceId] [http-nio-8080-exec-1] INFO - 库存扣减成功
```

整个请求链路所有日志都自动带 traceId，**业务代码无需手写**。

### 2.3 SimpleDateFormat 线程安全包装

`SimpleDateFormat` 不是线程安全的（内部 `Calendar` 实例字段会被并发修改），多线程共用会出错：

```java
public class DateUtils {
    // ★ 经典坑：SimpleDateFormat 不能 static 共享！
    private static final ThreadLocal<SimpleDateFormat> FORMATTER =
        ThreadLocal.withInitial(() -> new SimpleDateFormat("yyyy-MM-dd HH:mm:ss"));

    public static String format(Date d) {
        return FORMATTER.get().format(d);   // 每个线程自己一个 SDF 实例
    }
}
```

> **JDK 8+ 推荐**：直接用 `DateTimeFormatter`（线程安全的不可变对象），就不用 ThreadLocal 包了。

### 2.4 数据库连接 / 事务管理

Spring 的 `TransactionSynchronizationManager`：

```java
// Spring 源码片段
private static final ThreadLocal<Map<Object, Object>> resources =
    new NamedThreadLocal<>("Transactional resources");
```

每个请求线程绑定一个 `Connection`，事务方法之间共享同一连接，
**无需手动传参，也避免了多线程共用连接的并发问题**。
`@Transactional` 之所以能"无侵入"，背后就是这块在工作。

### 2.5 限流 / 熔断的调用链上下文

阿里 Sentinel：

```java
// Sentinel 源码片段
private static ThreadLocal<Context> contextHolder = new ThreadLocal<>();
```

每个请求一个 `Context`，记录访问的资源、调用关系。
RPC 框架（Dubbo）的 `RpcContext`、链路追踪（Skywalking、Sleuth）的 trace 上下文都是同样的设计。

---

## 三、ThreadLocal 原理 —— 数据到底存在哪里

### 3.1 错误的直觉

很多人以为 `ThreadLocal` 内部是这样：

```java
class ThreadLocal<T> {
    Map<Thread, T> map;   // ← 错的！
}
```

如果是这样：
- map 会随应用运行越积越大
- 必须加锁保证并发安全
- 线程结束后无法主动清理

### 3.2 真实结构

实际是**反过来的** —— 每个 `Thread` 自己持有一个 Map，key 是 ThreadLocal 实例：

```
┌──────────────────────────┐
│ Thread A                 │
│ ┌─────────────────────┐  │
│ │ threadLocals (Map)  │  │
│ │ ┌────────┬────────┐ │  │
│ │ │ TL1    │ value1 │ │  │   ← key 是 ThreadLocal 实例
│ │ │ TL2    │ value2 │ │  │   ← value 是该线程独有的值
│ │ │ TL3    │ value3 │ │  │
│ │ └────────┴────────┘ │  │
│ └─────────────────────┘  │
└──────────────────────────┘

┌──────────────────────────┐
│ Thread B                 │
│ ┌─────────────────────┐  │
│ │ threadLocals (Map)  │  │
│ │ ┌────────┬────────┐ │  │
│ │ │ TL1    │ valueX │ │  │   ← 同一个 TL1 实例，不同线程的 value 不同
│ │ │ TL2    │ valueY │ │  │
│ │ └────────┴────────┘ │  │
│ └─────────────────────┘  │
└──────────────────────────┘
```

这个设计带来 4 个好处：

| 设计 | 好处 |
|---|---|
| Map 在 `Thread` 上而不是在 `ThreadLocal` 上 | 线程结束 Map 自动随线程被 GC，无需全局清理 |
| key 是 `ThreadLocal` 实例（不是字符串名字） | 一个线程可同时持有多个 ThreadLocal，互不干扰 |
| ThreadLocalMap 用**开放地址法**（线性探测） | ThreadLocal 数量通常少（每个线程几个），开放地址比链表 HashMap 更紧凑 |
| key 是**弱引用** | 防止 ThreadLocal 实例在被外部废弃后还被 Map 强引用着泄漏 |

### 3.3 set/get 源码逻辑

```java
// java.lang.ThreadLocal#set
public void set(T value) {
    Thread t = Thread.currentThread();              // ① 拿当前线程
    ThreadLocalMap map = getMap(t);                 // ② 取线程的 map
    if (map != null) {
        map.set(this, value);                       // ③ 以 this（即 ThreadLocal 实例）为 key
    } else {
        createMap(t, value);                        // 第一次调用时创建 map
    }
}

ThreadLocalMap getMap(Thread t) {
    return t.threadLocals;                          // map 是 Thread 的字段
}

// java.lang.ThreadLocal#get
public T get() {
    Thread t = Thread.currentThread();
    ThreadLocalMap map = getMap(t);
    if (map != null) {
        Entry e = map.getEntry(this);               // 用 this 为 key 查
        if (e != null) return (T) e.value;
    }
    return setInitialValue();                       // 没 set 过则返回初始值（默认 null）
}
```

关键：`set` 和 `get` 都不需要锁 —— 因为读写的都是 `Thread.currentThread().threadLocals`，
**只有当前线程能访问到自己的 ThreadLocalMap**。

### 3.4 ThreadLocalMap 的关键设计

`ThreadLocalMap` 是 `ThreadLocal` 的**静态内部类**，跟普通 `HashMap` 完全是两套东西：

```java
static class ThreadLocalMap {
    static class Entry extends WeakReference<ThreadLocal<?>> {
        Object value;            // ★ value 是普通强引用！
        Entry(ThreadLocal<?> k, Object v) {
            super(k);            // ★ key 通过 WeakReference 传给父类
            value = v;
        }
    }

    private Entry[] table;       // hash 表，开放地址法（不用链表）
    // ...
}
```

注意三个**反 HashMap 直觉**的设计：

1. **`Entry` 直接继承 `WeakReference<ThreadLocal>`** —— 这意味着 key 是弱引用
2. **value 是普通强引用** —— 这是内存泄漏的根源（见下一节）
3. **冲突解决用开放地址法**（线性探测），不是链表 —— 因为 ThreadLocal 数量本身不多

---

## 四、内存泄漏 —— 弱引用与强引用的错配

### 4.1 Entry 的特殊结构

回顾上一节的 Entry：

```java
static class Entry extends WeakReference<ThreadLocal<?>> {
    Object value;                // 强引用
    Entry(ThreadLocal<?> k, Object v) {
        super(k);                // 弱引用
        value = v;
    }
}
```

**只有 key 是弱引用，value 是强引用** —— JDK 的设计师并非疏忽，他们必须这样做：

> 如果 value 也是弱引用，那 `tl.set(new BigObject())` 之后，
> 如果业务代码没有把 `BigObject` 别的地方再持有一次，
> 下一次 GC 就会把 value 回收掉，`tl.get()` 立刻拿到 null —— 这违背了 ThreadLocal 的语义。

但是这个"必要的"强引用，遇上"用完不 remove"的代码，就成了泄漏源。

### 4.2 引用链全景图

```
Thread (worker，线程池场景下长生不死)
  ↓ 强引用
Thread.threadLocals (ThreadLocalMap 实例)
  ↓ 强引用
Entry[] table (数组)
  ↓ 强引用
Entry
  ├─ key: WeakReference<ThreadLocal>     ← 弱引用！
  └─ value: 强引用 → 实际业务对象（可能很大）

         ↑                                  ↑
    ThreadLocal 实例                      value 对象
    （外部引用消失时，                  （没人能再访问，
     被 GC 回收，                       但被 Thread 强引用着，
     Entry.key 变成 null）              永远不会被回收 ★）
```

### 4.3 泄漏发生的精确时序

考虑这段"看起来没问题"的代码：

```java
public void doWork() {
    ThreadLocal<byte[]> tl = new ThreadLocal<>();   // 局部变量
    tl.set(new byte[100 * 1024 * 1024]);           // 100MB
    // ... 业务处理 ...
}   // 方法结束
```

```
T0: 方法执行中
    栈: tl → ThreadLocal 实例
    Thread.threadLocals → Entry → key=WeakRef(TL), value=100MB byte[]
                                  ↑ TL 同时被栈强引用 + Entry 弱引用着

T1: 方法结束，tl 出栈
    栈: (空)
    Thread.threadLocals → Entry → key=WeakRef(TL), value=100MB byte[]
                                  ↑ TL 只剩弱引用了

T2: GC 触发
    ThreadLocal 实例只有弱引用 → 被回收
    Entry → key=null, value=100MB byte[]   ★ value 还在！

T3: 但 Thread.threadLocals 还活着（线程还活着）
    Entry 仍然在 table 里
    100MB byte[] 永远无法回收 → 内存泄漏！
```

### 4.4 为什么线程池场景特别危险

普通线程跑完就死，`Thread.threadLocals` 跟着销毁，泄漏的 value 也随之被回收，
**问题不大**。

但线程池里：

```
worker 线程一辈子（应用运行期间）都活着
  → ThreadLocalMap 一直存在
  → 累积越来越多 key=null 的 Entry
  → 累积的 value 永远不释放
  → OOM
```

**几乎所有 Java Web 应用都跑在线程池里**（Tomcat / Netty / 各种业务线程池），
所以"用 ThreadLocal 必须 remove" 不是建议，是铁律。

### 4.5 JDK 的"被动清理"为什么不够

`ThreadLocalMap.set/get/remove` 时会顺便清理一些 key=null 的 Entry：

```java
// 源码片段（伪代码）
private void set(ThreadLocal<?> key, Object value) {
    // ... 找位置 ...
    if (e.get() == null) {                    // 发现 key 已被 GC
        replaceStaleEntry(key, value, i);     // 顶替这个空位
        return;
    }
    // ... 然后 expungeStaleEntry() 进一步清理周围 stale entry
}
```

但这是**机会主义清理**，存在两个问题：

1. 如果你 set 一次后再也不调用任何 ThreadLocal 方法，那个泄漏的 Entry 永远清不掉
2. 即使触发了清理，每次只清扫 hash 表的一小段，不能保证清完所有 stale entry

**所以不能依赖 JDK 的被动清理，必须主动 `remove()`。**

### 4.6 实测（demo: ThreadLocalLeakDemo）

[`ThreadLocalLeakDemo`](../src/main/java/com/example/demo/concurrent/threadlocal/ThreadLocalLeakDemo.java)
模拟生产环境（静态 ThreadLocal + 4 个 worker 的线程池 + 8 轮任务，每轮 set 30MB）：

```
========== 对比结果 ============
场景 A（不 remove）  GC 后剩余: 125 MB  ★ 泄漏（理论 4×30=120MB，实测 125MB）
场景 B（有 remove）  GC 后剩余:   1 MB  ★ 干净
```

差了 100 倍以上。这就是为什么这条规则要写进每家公司的代码规范里。

### 4.7 唯一解药：`try-finally remove()`

```java
ThreadLocal<UserInfo> tl = new ThreadLocal<>();

try {
    tl.set(user);
    // ... 业务 ...
} finally {
    tl.remove();   // ★ 不可少
}
```

> **阿里巴巴 Java 开发手册（黄山版）强制条款**：
> "ThreadLocal 对象使用 `static` 修饰，并且不再使用时务必调用 `remove()` 方法。"
> 配套的 IDE 插件 `Alibaba Java Coding Guidelines` 会扫描出未 remove 的代码并报警。

---

## 五、跨线程传递 ThreadLocal 的值

ThreadLocal 设计上是"线程私有"，跨线程传值是**反设计**的需求 —— 但实际项目里非常常见：

- 异步任务要继承父线程的 traceId
- 子线程要拿到父请求的 userId
- 线程池 worker 要看到提交方设置的上下文

### 5.1 普通 ThreadLocal 子线程拿不到

```java
ThreadLocal<String> tl = new ThreadLocal<>();
tl.set("parent-value");

new Thread(() -> {
    System.out.println(tl.get());   // → null  ★ 拿不到
}).start();
```

子线程是新的 `Thread` 实例，`Thread.threadLocals` 是空的。

### 5.2 InheritableThreadLocal（父子线程）

JDK 自带，**新建子线程时 copy 父线程的值**：

```java
InheritableThreadLocal<String> tl = new InheritableThreadLocal<>();
tl.set("parent-value");

new Thread(() -> {
    System.out.println(tl.get());   // → "parent-value"  ★ 拿到了
}).start();
```

实现原理（`Thread` 构造函数关键片段）：

```java
public Thread(Runnable r) {
    Thread parent = currentThread();
    if (parent.inheritableThreadLocals != null) {
        // ★ 子线程创建时复制父线程的 inheritableThreadLocals
        this.inheritableThreadLocals =
            ThreadLocal.createInheritedMap(parent.inheritableThreadLocals);
    }
}
```

`Thread` 类有两个 ThreadLocalMap 字段：

```java
ThreadLocal.ThreadLocalMap threadLocals;            // 普通 ThreadLocal 用的
ThreadLocal.ThreadLocalMap inheritableThreadLocals; // InheritableThreadLocal 用的
```

### 5.3 线程池场景失效（demo: InheritableThreadLocalDemo）

`InheritableThreadLocal` 致命缺陷：**只在线程创建瞬间 copy**。
线程池里 worker 线程被复用，不重新创建 → 后续 set 的值传不进去：

```java
ExecutorService pool = Executors.newFixedThreadPool(1);
InheritableThreadLocal<String> tl = new InheritableThreadLocal<>();

tl.set("v1");
pool.submit(() -> System.out.println(tl.get()));   // → "v1"（线程第一次创建时 copy 了）

tl.set("v2");
pool.submit(() -> System.out.println(tl.get()));   // → "v1" ★ 还是 v1！
//                                                    因为 worker 没重新创建，没 copy
```

实测见 [`InheritableThreadLocalDemo`](../src/main/java/com/example/demo/concurrent/threadlocal/InheritableThreadLocalDemo.java)：

```
父线程 set v1
worker 第 1 次 get: v1   （首次创建 worker，copy 了 v1）
父线程 set v2
worker 第 2 次 get: v1   ★ 还是 v1！worker 没重新创建
父线程 set v3
worker 第 3 次 get: v1   ★ 仍然是 v1
```

### 5.4 阿里 TransmittableThreadLocal（线程池场景标准方案）

阿里专门为线程池场景开源的 `TransmittableThreadLocal`（简称 TTL）：

```xml
<dependency>
    <groupId>com.alibaba</groupId>
    <artifactId>transmittable-thread-local</artifactId>
    <version>2.14.5</version>
</dependency>
```

```java
TransmittableThreadLocal<String> ttl = new TransmittableThreadLocal<>();

// ★ 关键：用 TtlExecutors 包装线程池
ExecutorService pool = TtlExecutors.getTtlExecutorService(
    Executors.newFixedThreadPool(2));

ttl.set("v1");
pool.submit(() -> System.out.println(ttl.get()));   // → "v1"

ttl.set("v2");
pool.submit(() -> System.out.println(ttl.get()));   // → "v2" ★ 正确！
```

**TTL 实现的核心三步法**：

```
1. 提交端 capture：
   ttl.set(value) 时把 ttl 自己注册到一个全局 holder
   submit 时遍历所有 TTL，capture 当前值

2. 执行端 replay：
   worker 执行任务前，把 capture 的所有值 set 到 worker 的 ThreadLocal

3. 执行端 restore：
   任务执行完，恢复 worker 原本的 ThreadLocal 值（避免污染下一个任务）
```

这套机制保证**每次提交都重新传递最新值**，不像 `InheritableThreadLocal` 只在线程创建时 copy 一次。

**生产应用**：Skywalking、Spring Cloud Sleuth 内部都集成了 TTL 来传递分布式追踪上下文。

### 5.5 手写简化版 ContextRunnable（demo: ContextRunnableDemo）

理解了 TTL 的 capture/replay/restore 思路，自己手写一个简化版：

```java
public class ContextRunnable implements Runnable {
    private final Runnable task;
    private final UserInfo capturedContext;   // ★ 提交时捕获

    public ContextRunnable(Runnable task) {
        this.task = task;
        this.capturedContext = UserContext.get();   // 在【调用方线程】捕获
    }

    @Override
    public void run() {
        UserInfo backup = UserContext.get();
        UserContext.set(capturedContext);     // ★ replay：worker 注入捕获值
        try {
            task.run();
        } finally {
            if (backup == null) {
                UserContext.clear();          // ★ restore（避免污染 worker）
            } else {
                UserContext.set(backup);
            }
        }
    }
}

// 用法
pool.submit(new ContextRunnable(() -> {
    UserInfo user = UserContext.get();   // ★ 能拿到提交时的 user
}));
```

完整实现见 [`ContextRunnableDemo`](../src/main/java/com/example/demo/concurrent/threadlocal/ContextRunnableDemo.java)，跑出来：

```
>>> 实验组: 用 ContextRunnable 包装
  [main] 设置 TRACE_ID=trace-BBBB
  [worker] get TRACE_ID = trace-BBBB  ★ 拿到了 BBBB
  [main] 改设 TRACE_ID=trace-CCCC
  [worker] get TRACE_ID = trace-CCCC  ★ 拿到了 CCCC（每次提交重新捕获）
```

### 5.6 JDK 21+ ScopedValue（终极方案）

Project Loom 认为 ThreadLocal 整体设计有问题（可变 + 内存泄漏 + 不适合虚拟线程），
JDK 21 引入了全新的 `ScopedValue`（JDK 21 是 preview，JDK 25 GA）：

```java
public class ScopedValueDemo {
    private static final ScopedValue<String> USER = ScopedValue.newInstance();

    public static void main(String[] args) {
        ScopedValue.where(USER, "alice").run(() -> {
            // 在这个 scope 里 USER.get() == "alice"
            doWork();
        });
        // ★ scope 结束，USER 自动失效，不可能内存泄漏
    }

    static void doWork() {
        System.out.println("user = " + USER.get());
    }
}
```

**核心改进**：

| 维度 | ThreadLocal | ScopedValue |
|---|---|---|
| **可变性** | 可变（set/remove） | **不可变**（一旦 where 就锁定） |
| **生命周期** | 跟线程同寿命 | **绑定 scope**，run 结束自动失效 |
| **内存泄漏** | 容易泄漏 | **结构上不可能泄漏** |
| **跨虚拟线程传递** | 占内存（每个虚拟线程一份） | **共享一份只读引用**（极轻） |
| **适合 Loom 虚拟线程** | ❌ 百万虚拟线程 ThreadLocal 会爆内存 | ✅ 设计目标 |

Spring Framework 6.2+ / Spring Boot 3.4+ 已开始向 `ScopedValue` 迁移上下文管理。

### 5.7 选型决策表

| 场景 | 选什么 |
|---|---|
| 单线程内传递上下文 | `ThreadLocal` + `try-finally remove()` |
| 父线程 → 普通子线程（手动 `new Thread`） | `InheritableThreadLocal` |
| 父线程 → 线程池 worker | `TransmittableThreadLocal` (阿里 TTL) |
| 跨虚拟线程 / 现代 JDK 项目 | `ScopedValue` (JDK 21+) |
| 日志上下文 | `MDC`（本质就是 ThreadLocal） |
| 数据库事务 | Spring `TransactionSynchronizationManager`（基于 ThreadLocal） |

---

## 六、ThreadLocal vs 加锁共享 —— 本质对比

| 维度 | 共享变量 + 加锁 | ThreadLocal |
|---|---|---|
| **数据共享方式** | 一份共享数据 | 每线程一份独立副本 |
| **并发安全机制** | 锁 / CAS | 天然隔离，无需同步 |
| **性能** | 锁竞争降低吞吐 | 几乎无开销（类似局部变量） |
| **传递方式** | 显式传参 / 共享引用 | 隐式传递（链路任意位置可取） |
| **多线程能看到对方修改？** | ✅ 能 | ❌ 看不到（这是设计目标） |
| **内存开销** | 低（一份数据） | 高（N 线程 × 数据大小） |
| **典型坑** | 死锁、活锁、可见性 | **内存泄漏**、跨线程传值难 |

简单记忆：

> **要"共享"就加锁，要"独占"就 ThreadLocal。**
> 如果你的需求是"每个请求/线程有自己的上下文，链路上多处都要用"——选 ThreadLocal。

---

## 七、最佳实践清单

铁律 5 条：

1. ✅ **`ThreadLocal` 必须 `static final`**
   - 避免误以为"每个对象一个 ThreadLocal"，那会创建一堆 ThreadLocal 实例
   - 也是阿里规范强制条款

2. ✅ **`try-finally` 配 `remove()` 是标配**
   - 任何 `set()` 都必须有对应 `remove()`
   - 在 Filter / Interceptor / AOP 切面统一收口

3. ✅ **不要存大对象**
   - 即使你 remove 了，过程中也会增加 GC 压力
   - 大对象建议存 ID，按需 lazy-load

4. ✅ **跨线程传值用对工具**
   - `new Thread()` 子线程 → `InheritableThreadLocal`
   - 线程池 → `TransmittableThreadLocal` 或包装 Runnable
   - JDK 21+ → `ScopedValue`

5. ✅ **`@Async` / `CompletableFuture.supplyAsync` 也是线程池**
   - 默认它们用的也是线程池，普通 ThreadLocal 传不过去
   - 需要走 TTL 或者手动包装

反模式 3 个：

1. ❌ 局部变量定义 ThreadLocal
2. ❌ set 后忘记 remove
3. ❌ 在 ThreadLocal 里存可变集合，多个组件共享时混乱

---

## 八、一句话总结

> **ThreadLocal 的本质是"每个 Thread 自己持有一个 ThreadLocalMap，以 ThreadLocal 实例为 key 存值"，
> 让线程私有变量无需加锁、无需传参就能在调用链任意位置取到。
>
> 内存泄漏的根源是 `Entry.key` 是弱引用、`value` 是强引用 ——
> ThreadLocal 实例被回收后 value 仍被 `Thread.threadLocals` 强引用着，
> 在线程池 worker 长生不死的场景下尤其致命，唯一解药是 `try-finally { tl.remove() }`。
>
> 跨线程传值按场景选：父子线程用 `InheritableThreadLocal`，线程池用阿里 TTL，
> JDK 21+ 直接用 `ScopedValue` 一劳永逸。**

---

## 附录：跑 demo 的命令

```bash
# 编译
mvn -q compile

# Demo 1: ThreadLocal 线程隔离
java -cp target/classes com.example.demo.concurrent.threadlocal.ThreadLocalBasicDemo

# Demo 2: 内存泄漏对比（建议加 -Xmx1g）
java -Xmx1g -cp target/classes com.example.demo.concurrent.threadlocal.ThreadLocalLeakDemo

# Demo 3: InheritableThreadLocal 父子线程 + 线程池失效
java -cp target/classes com.example.demo.concurrent.threadlocal.InheritableThreadLocalDemo

# Demo 4: 手写 ContextRunnable 解决线程池跨线程传值
java -cp target/classes com.example.demo.concurrent.threadlocal.ContextRunnableDemo
```

预期输出关键片段：

```
[Demo 2 对比结果]
场景 A（不 remove）  GC 后剩余: 125 MB  ★ 泄漏
场景 B（有 remove）  GC 后剩余:   1 MB  ★ 干净

[Demo 3 线程池失效场景]
父线程 set v1
worker 第 1 次 get: v1
父线程 set v2
worker 第 2 次 get: v1   ★ 还是 v1（暴露失效）

[Demo 4 用 ContextRunnable 修复]
[main] 设置 TRACE_ID=trace-BBBB
[worker] get TRACE_ID = trace-BBBB   ★ 拿到了
```

---

## 参考

- JDK 源码：`java.lang.ThreadLocal` / `java.lang.Thread`
- 阿里 TTL 项目：<https://github.com/alibaba/transmittable-thread-local>
- 《阿里巴巴 Java 开发手册》—— ThreadLocal 章节
- JEP 446 / 487：Scoped Values（JDK 21 preview / JDK 25 final）
- 美团技术博客《ThreadLocal 详解》：<https://tech.meituan.com/2018/11/29/java-thread-local.html>
