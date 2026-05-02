# Java volatile 关键字深入解析

> 本文系统讲解 `volatile` 的原理：从 JMM 内存模型 → CPU 缓存 → MESI 协议 → 内存屏障 → happens-before，
> 对应可运行 demo 在 [`src/main/java/com/example/demo/concurrent/`](../src/main/java/com/example/demo/concurrent/)。

## 目录

- [一、volatile 解决哪些问题](#一volatile-解决哪些问题)
- [二、可见性问题的根源 —— JMM 模型](#二可见性问题的根源--jmm-模型)
- [三、可见性反例（demo: VisibilityDemo）](#三可见性反例demo-visibilitydemo)
- [四、volatile 如何保证可见性 —— 字节码 + CPU 指令](#四volatile-如何保证可见性--字节码--cpu-指令)
- [五、有序性问题的根源 —— 重排序](#五有序性问题的根源--重排序)
- [六、volatile 如何保证有序性 —— 内存屏障](#六volatile-如何保证有序性--内存屏障)
- [七、happens-before 规则](#七happens-before-规则)
- [八、volatile 不保证原子性（demo: AtomicityDemo）](#八volatile-不保证原子性demo-atomicitydemo)
- [九、典型应用 1：DCL 单例（demo: DclSingletonDemo）](#九典型应用-1dcl-单例demo-dclsingletondemo)
- [十、典型应用 2：状态标志位](#十典型应用-2状态标志位)
- [十一、volatile vs synchronized 对比](#十一volatile-vs-synchronized-对比)
- [十二、一句话总结](#十二一句话总结)
- [附录：跑 demo 的命令](#附录跑-demo-的命令)

---

## 一、volatile 解决哪些问题

并发编程有 3 个核心特性：

| 特性 | 含义 | volatile 保证？ |
|---|---|---|
| **原子性** | 操作要么全部执行，要么不执行 | ❌ 不保证（`i++` 还是会出错） |
| **可见性** | 一个线程修改了变量，其它线程能立刻看到 | ✅ 保证 |
| **有序性** | 代码不会被乱序执行（重排序） | ✅ 部分保证 |

> **关键认知**：`volatile` 不是线程安全的银弹，它只搞定可见性和有序性。
> 需要原子性时还得用 `synchronized` / `AtomicInteger` / `Lock`。

---

## 二、可见性问题的根源 —— JMM 模型

要理解 volatile，必须先理解 **Java 内存模型 (JMM)**：

```
        ┌──────────────┐  ┌──────────────┐
        │  Thread A    │  │  Thread B    │
        │ ┌──────────┐ │  │ ┌──────────┐ │
        │ │工作内存   │ │  │ │工作内存   │ │  ← 对应 CPU 寄存器 + L1/L2 缓存
        │ │ flag = T │ │  │ │ flag = F │ │  ← 各自的副本可能不一致！
        │ └──────────┘ │  │ └──────────┘ │
        └──────┬───────┘  └──────┬───────┘
               │                  │
               └────────┬─────────┘
                        ↓
               ┌──────────────────┐
               │     主内存        │
               │   flag = false   │   ← 真实存储位置（对应物理 RAM）
               └──────────────────┘
```

**问题**：每个线程操作变量时，先把变量从主内存"复制一份"到自己的工作内存，
操作完再"刷"回主内存。这中间窗口期就出现了**数据不一致**：

```
T0: 主内存 flag=false，A、B 工作内存都 false
T1: A 把 flag 改成 true（只在 A 自己工作内存里）
T2: B 读 flag → 还是 false（B 工作内存里没看到 A 的修改）
T3: B 进入死循环！
```

物理层面对应的是：

| 层级 | 容量 | 延迟 | 共享 |
|---|---|---|---|
| **CPU 寄存器** | 极小 | <1ns | 私有 |
| **L1 cache** | 几十 KB | ~1ns | 每核私有 |
| **L2 cache** | 几百 KB | ~3ns | 每核私有 |
| **L3 cache** | 几十 MB | ~10ns | 多核共享 |
| **主存（RAM）** | GB 级 | ~100ns | 全局 |

CPU 不可能每次访问变量都跑到 RAM，那性能会暴跌 100 倍。所以缓存是必须的，
但缓存就带来了"多核之间副本不一致"的问题。

---

## 三、可见性反例（demo: VisibilityDemo）

```java
public class VisibilityDemo {
    private static boolean stop = false;   // 注意：没加 volatile

    public static void main(String[] args) throws InterruptedException {
        Thread worker = new Thread(() -> {
            int count = 0;
            while (!stop) {                // 工作线程读自己工作内存的 stop 副本
                count++;
            }
            System.out.println("worker 退出，count=" + count);
        });
        worker.start();

        Thread.sleep(1000);
        stop = true;                       // 主线程改主内存的 stop
        System.out.println("main 设置 stop=true");
        worker.join();                     // 永远等不到 worker 退出！
    }
}
```

**实际表现**：worker 线程的 JIT 编译器把 `while (!stop)` 优化成了：

```
寄存器 r1 = stop;         // 加载一次
LOOP: if (r1) goto END;   // 永远在循环里读寄存器，根本不去读主内存
      count++;
      goto LOOP;
END:
```

加上 `volatile`：

```java
private static volatile boolean stop = false;
```

worker 立刻退出。**这就是可见性。**

> 完整可运行的对比 demo：
> [`src/main/java/com/example/demo/concurrent/VisibilityDemo.java`](../src/main/java/com/example/demo/concurrent/VisibilityDemo.java)

---

## 四、volatile 如何保证可见性 —— 字节码 + CPU 指令

JVM 在编译 volatile 写/读时，会插入特殊指令：

### 写 volatile 变量

```
普通写 (不加 volatile):
  mov [stop_addr], 1                # 写入 cache，可能缓存里待半天

volatile 写:
  mov [stop_addr], 1
  lock addl $0, (%rsp)              # ★ x86 上的关键指令
```

**`lock` 前缀**做了两件事：

1. **强制把当前 CPU 的 store buffer 刷到 L1 cache**（一秒变可见）
2. **触发 MESI 缓存一致性协议**：通过 CPU 总线广播 `invalidate` 消息，
   让所有其它核里同一个 cache line 失效

### 读 volatile 变量

```
volatile 读:
  mov [stop_addr], %eax             # 读到本地 cache line 时
                                    # 如果这个 cache line 是 Invalid 状态
                                    # 必须从其它 CPU 或主存重新加载最新值
```

### 底层：MESI 缓存一致性协议

每个 cache line 有 4 种状态：

| 状态 | 含义 |
|---|---|
| **M** (Modified) | 我修改过，跟主存不一致，只我有 |
| **E** (Exclusive) | 只我有，跟主存一致 |
| **S** (Shared) | 多个 CPU 都有这份 |
| **I** (Invalid) | 我这份是无效的，要重新读 |

CPU A 写 `volatile stop = true` 的全过程：

```
T0: 多核都缓存了 stop=false
    A 的 cache line: S        B 的 cache line: S

T1: A 准备写，先发 invalidate 总线消息
    A 的 cache line: → M      B 的 cache line: → I

T2: B 读 stop，发现自己的 cache line 是 I 状态
    B 必须重新从 A (或主存) 拉取最新值
    → 读到 stop = true
```

**这就是 volatile 保证可见性的物理机制：靠 CPU 的 MESI 协议 + lock 指令的强制刷新。**

---

## 五、有序性问题的根源 —— 重排序

CPU 和编译器为了性能，会**乱序执行指令**，只要保证单线程内的最终结果不变
（"as-if-serial"语义）。

3 个层面的重排序：

| 层面 | 例子 |
|---|---|
| **编译器重排序** | javac / JIT 重排序源代码生成的指令 |
| **CPU 指令级重排序** | 现代 CPU pipeline、超标量执行 |
| **内存系统重排序** | store buffer / invalidate queue 让"看似已写"的值延迟可见 |

### 经典反例

```java
int x = 0;
boolean flag = false;

// 线程 A
x = 42;          // (1)
flag = true;     // (2)

// 线程 B
if (flag) {      // (3)
    System.out.println(x);   // (4) 可能打印 0 而不是 42！
}
```

**原因**：(1) 和 (2) 没有数据依赖，可能被重排序成：

```
flag = true;     // (2) 先执行
x = 42;          // (1) 后执行
```

线程 B 看到 `flag=true` 但还没看到 `x=42`，打印 0。

---

## 六、volatile 如何保证有序性 —— 内存屏障

JVM 在 volatile 读写前后插入 4 种**内存屏障 (Memory Barrier)**，
禁止特定方向的重排序：

| 屏障类型 | 作用 |
|---|---|
| **LoadLoad** | 屏障前的读不能与屏障后的读重排序 |
| **StoreStore** | 屏障前的写不能与屏障后的写重排序 |
| **LoadStore** | 屏障前的读不能与屏障后的写重排序 |
| **StoreLoad** | 屏障前的写不能与屏障后的读重排序（最重的屏障） |

JMM 对 volatile 的具体规则：

```
写 volatile 变量时:
  ┌─────────────────────────────┐
  │   StoreStore 屏障            │ ← 之前的所有写都必须先完成
  ├─────────────────────────────┤
  │   volatile write             │
  ├─────────────────────────────┤
  │   StoreLoad 屏障             │ ← 之后的所有读不能提到这之前
  └─────────────────────────────┘

读 volatile 变量时:
  ┌─────────────────────────────┐
  │   volatile read              │
  ├─────────────────────────────┤
  │   LoadLoad 屏障              │ ← 之后的所有读不能提到这之前
  ├─────────────────────────────┤
  │   LoadStore 屏障             │ ← 之后的所有写不能提到这之前
  └─────────────────────────────┘
```

回到上面那个例子，把 `flag` 加 volatile：

```java
volatile boolean flag = false;

// 线程 A
x = 42;          // (1) 普通写
flag = true;     // (2) volatile 写
                 // ↓ JVM 在这插入 StoreStore 屏障
                 // 保证 (1) 一定在 (2) 之前完成

// 线程 B
if (flag) {      // (3) volatile 读
                 // ↓ JVM 在这插入 LoadLoad 屏障
                 // 保证 (4) 一定在 (3) 之后执行
    print(x);    // (4) 一定能看到 x=42
}
```

---

## 七、happens-before 规则

JMM 用一组 **happens-before** 规则定义"如果操作 A happens-before 操作 B，
那 A 的结果对 B 可见"。

跟 volatile 相关的有：

1. **程序顺序规则**：同一线程内，前面的操作 happens-before 后面的操作
2. **volatile 变量规则**：对一个 volatile 变量的**写** happens-before 后续对同一变量的**读**
3. **传递性规则**：A happens-before B，B happens-before C，则 A happens-before C

回到上面例子：

```
(1) x = 42         ── 程序顺序 ──→ (2) flag = true (volatile 写)
                                              │
                                              ▼ volatile 规则
                                   (3) if(flag) (volatile 读)
                                              │
                                              ▼ 程序顺序
                                              (4) print(x)

传递性：(1) happens-before (4)，所以 (4) 一定能看到 x=42
```

---

## 八、volatile 不保证原子性（demo: AtomicityDemo）

```java
private static volatile int count = 0;   // 加了 volatile

// 10 个线程各自执行 100000 次自增
for (int i = 0; i < 10; i++) {
    new Thread(() -> {
        for (int j = 0; j < 100_000; j++) {
            count++;        // 期望最终 1,000,000
        }
    }).start();
}
// 实际结果通常是 800,000 ~ 950,000
```

**为什么不对**？因为 `count++` 不是一条指令，是 3 步：

```
1. tmp = count      (读)
2. tmp = tmp + 1    (改)
3. count = tmp      (写)
```

volatile 保证每一步**单独**是可见的，但 3 步之间另一个线程可以插进来：

```
线程 A: 读 count=100, 改 tmp=101, [被切走]
线程 B: 读 count=100, 改 tmp=101, 写 count=101
线程 A: [被换回] 写 count=101    ← 100→101 应该 +2 但只 +1，丢失一次更新
```

**正确做法**：

```java
private static AtomicInteger count = new AtomicInteger(0);
count.incrementAndGet();   // CAS 原子操作

// 或
synchronized (lock) { count++; }
```

> 完整对比 demo（volatile vs AtomicInteger vs synchronized）：
> [`src/main/java/com/example/demo/concurrent/AtomicityDemo.java`](../src/main/java/com/example/demo/concurrent/AtomicityDemo.java)

---

## 九、典型应用 1：DCL 单例（demo: DclSingletonDemo）

```java
public class Singleton {
    private static volatile Singleton instance;   // ★★★ 必须 volatile

    public static Singleton getInstance() {
        if (instance == null) {                    // 第一次检查（无锁，快）
            synchronized (Singleton.class) {
                if (instance == null) {            // 第二次检查（持锁）
                    instance = new Singleton();    // ★ 这一行不原子！
                }
            }
        }
        return instance;
    }
}
```

**为什么必须 volatile**？`new Singleton()` 在字节码层面是 3 步：

```
1. 分配内存
2. 初始化对象 (构造函数)
3. instance 指向内存
```

如果发生 2、3 **重排序**变成 1、3、2：

```
T1 线程: 1. 分配内存 → 3. instance 指向内存 → ⏸ 被切走
T2 线程: if (instance == null)  → false（不为 null）→ 直接返回 instance
T2 线程: 使用 instance → ★ 但 2 还没执行，对象未初始化！NPE！
```

加 volatile 就禁止了 2、3 重排序，保证 instance 不为 null 时对象一定完全初始化好了。

> 完整 demo（200 个线程并发抢 getInstance，验证只创建 1 个实例）：
> [`src/main/java/com/example/demo/concurrent/DclSingletonDemo.java`](../src/main/java/com/example/demo/concurrent/DclSingletonDemo.java)

---

## 十、典型应用 2：状态标志位

线程间的开关、状态通知，是 volatile 最朴素也最常见的用法：

```java
public class WorkerService {
    private volatile boolean running = true;

    public void start() {
        new Thread(() -> {
            while (running) {       // 主循环
                doWork();
            }
            cleanup();
        }).start();
    }

    public void stop() {
        running = false;            // 一个线程改，另一个线程立刻可见
    }
}
```

**JDK 源码大量使用**：

```java
// java.util.concurrent.ConcurrentHashMap
volatile Node<K,V>[] table;
volatile int sizeCtl;

// java.util.concurrent.locks.AbstractQueuedSynchronizer (AQS 锁的核心)
private volatile int state;

// java.util.concurrent.ThreadPoolExecutor
private final AtomicInteger ctl = ...   // 这里用 Atomic，但内部也是 volatile + CAS
```

---

## 十一、volatile vs synchronized 对比

| 维度 | volatile | synchronized |
|---|---|---|
| 适用范围 | 变量 | 代码块 / 方法 |
| 原子性 | ❌ 单变量读/写原子，复合操作不原子 | ✅ 整个块原子 |
| 可见性 | ✅ | ✅ |
| 有序性 | ✅ 禁止特定重排序 | ✅ 锁内有序 |
| 阻塞 | ❌ 永远不阻塞，无锁 | ✅ 会阻塞 |
| 性能开销 | 小（一条 lock 指令） | 大（用户态/内核态切换、context switch） |
| 应用场景 | 状态标志、DCL 单例、AQS state | 复合操作、临界区 |

**经验法则**：

- 单纯**读多写少 / 读写都是单一变量** → volatile
- 涉及**多个变量复合操作 / 检查再修改** → synchronized 或 Atomic 类
- DCL 单例 → 两个都用（synchronized 保护初始化 + volatile 防重排序）

---

## 十二、一句话总结

> **volatile 通过 CPU 的 lock 前缀指令强制刷 cache + MESI 缓存一致性协议保证可见性，
> 通过 JVM 在读写前后插入内存屏障禁止特定方向的重排序保证有序性，
> 但它不保证 i++ 这种复合操作的原子性。它的核心定位是"轻量级线程通信"——
> 一写多读、状态标志、DCL 防重排序，性能远好于 synchronized 但功能也弱得多。**

---

## 附录：跑 demo 的命令

三个 demo 都不依赖 Spring Boot，可独立运行：

```bash
# 编译
mvn -q -DskipTests compile

# 1. 可见性 demo（演示无 volatile 时 worker 死循环，加 volatile 后立刻退出）
java -cp target/classes com.example.demo.concurrent.VisibilityDemo

# 2. 原子性 demo（对比 volatile / AtomicInteger / synchronized 三种计数）
java -cp target/classes com.example.demo.concurrent.AtomicityDemo

# 3. DCL 单例 demo（200 线程并发抢实例，验证只创建 1 次）
java -cp target/classes com.example.demo.concurrent.DclSingletonDemo
```

---

## 参考

- [JSR 133: Java Memory Model and Thread Specification](https://www.jcp.org/en/jsr/detail?id=133)
- [Doug Lea — The JSR-133 Cookbook](https://gee.cs.oswego.edu/dl/jmm/cookbook.html) — 内存屏障实现细节
- [《深入理解 Java 虚拟机》第 12 章 Java 内存模型与线程](https://book.douban.com/subject/34907497/)
- [《Java 并发编程实战》第 3 章 对象的共享](https://book.douban.com/subject/10484692/)
