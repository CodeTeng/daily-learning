# CAS 自旋开销与 LongAdder 解法

> 本文聚焦 CAS（Compare-And-Swap）算法在高并发下"自旋时间长、开销大"的根因，
> 系统讲解 5 种主流解决方案，重点展开 JDK 8 的 `LongAdder`。
> 适合读完 [`java-volatile.md`](./java-volatile.md) 后阅读。

## 目录

- [一、CAS 自旋问题的本质](#一cas-自旋问题的本质)
- [二、为什么自旋会"开销大"](#二为什么自旋会开销大)
- [三、解决方案 1：自适应自旋](#三解决方案-1自适应自旋)
- [四、解决方案 2：LongAdder（★ 最经典）](#四解决方案-2longadder--最经典)
  - [4.1 AtomicLong 的瓶颈](#41-atomiclong-的瓶颈)
  - [4.2 LongAdder 的分散思路](#42-longadder-的分散思路)
  - [4.3 防止 false sharing（伪共享）](#43-防止-false-sharing伪共享)
  - [4.4 用法对比](#44-用法对比)
  - [4.5 性能对比数据](#45-性能对比数据)
  - [4.6 LongAdder 的代价](#46-longadder-的代价)
  - [4.7 LongAccumulator —— 通用版本](#47-longaccumulator--通用版本)
- [五、解决方案 3：pause 指令降低自旋成本](#五解决方案-3pause-指令降低自旋成本)
- [六、解决方案 4：退避策略 (Backoff)](#六解决方案-4退避策略-backoff)
- [七、解决方案 5：阻塞同步（锁升级）](#七解决方案-5阻塞同步锁升级)
- [八、选型决策表](#八选型决策表)
- [九、一句话总结](#九一句话总结)
- [附录：自己动手对比的代码](#附录自己动手对比的代码)
- [参考](#参考)

---

## 一、CAS 自旋问题的本质

先回顾 CAS 的核心实现（以 `AtomicInteger.incrementAndGet()` 为例）：

```java
public final int incrementAndGet() {
    int prev, next;
    do {
        prev = get();           // ① 读旧值
        next = prev + 1;        // ② 算新值
    } while (!compareAndSet(prev, next));   // ③ CAS：旧值还是 prev 才写入
    return next;
}
```

CAS 是**乐观锁 + 自旋**的组合：

- **乐观**：先假设没人跟我抢，直接算
- **CAS**：写入时再检查"我读到时的旧值现在还是不是？"
- **自旋**：失败就重试，永不阻塞

低竞争下几乎一次成功；**高竞争下灾难来临**：

```
100 个线程同时 incrementAndGet()：

  Thread 1:  CAS(0→1) ✓ 成功
  Thread 2:  CAS(0→1) ✗ 失败（值已经是 1 了）→ 重试 CAS(1→2) ✓
  Thread 3:  CAS(0→1) ✗ → CAS(1→2) ✗ → CAS(2→3) ✓
  ...
  Thread 100: 可能要重试几十次才成功
```

整体效果：**CPU 大量时间花在"读旧值 → 算 → CAS 失败 → 再读"上**，做的有效工作很少。

---

## 二、为什么自旋会"开销大"

不是单纯的 while 循环耗 CPU 那么简单。三个层面叠加：

### 1. CPU 自旋空转

while 循环吃 100% 单核 CPU，几十个线程同时自旋直接把整机 load 推爆。

### 2. cache line 在多核间反复搬运（cache line ping-pong）

```
T0: 多核都缓存 value=0
    Core A: cache line [value=0]  状态 S
    Core B: cache line [value=0]  状态 S

T1: Core A 写 CAS(0→1)
    → 通过 MESI 协议发 invalidate 给 B
    Core A: [value=1]  M
    Core B: [value=invalid]  I

T2: Core B 想 CAS(0→1)，发现自己 cache line 失效
    → 必须从 Core A 拉取最新值（跨核读，可能 100+ ns）
    Core B: [value=1]  S
    Core A: [value=1]  S

T3: Core B 算出 next=2，CAS(1→2)
    → 又给 A 发 invalidate
    ...

cache line 在两个核之间疯狂来回搬运 —— 这就是 cache ping-pong
```

100 个线程抢同一个变量，整机的内存子系统大部分带宽都浪费在这上面。

### 3. bus 总线被 lock 指令频繁占用

x86 平台 CAS 是 `lock cmpxchg` 指令。`lock` 前缀会暂时锁住总线（或更精确的 cache line lock），强制刷 store buffer + 同步 cache。频繁的 `lock` 指令会让所有核访问内存都变慢。

> 实测：1 核心 CAS 操作约 5 ns；100 线程争抢同一变量时，单次 CAS 可能膨胀到 500 ns 以上 —— **100 倍的退化**。

---

## 三、解决方案 1：自适应自旋

最朴素的思路：**自旋有上限，超过就阻塞挂起**（让 OS 调度别的线程上）。

JDK 6 之前自旋次数写死（10 次），之后引入**自适应自旋**：

> JVM 根据上次同一锁上自旋成功的概率，动态调整这次的自旋次数。
> 自旋通常很快成功 → 下次自旋次数增加
> 自旋几乎从不成功 → 直接挂起省 CPU

**应用场景**：`synchronized` 的轻量级锁、`ReentrantLock` 内部的 AQS。

**JVM 参数**（一般不需要调）：

```
-XX:+UseSpinning              # 开启自旋（默认开）
-XX:PreBlockSpin=10           # 自旋次数（已被自适应取代）
```

---

## 四、解决方案 2：LongAdder（★ 最经典）

`LongAdder` 是 Doug Lea 在 JDK 8 引入的类，**专门为高并发计数场景设计**。

核心思想：**化整为零，分散竞争**。

### 4.1 AtomicLong 的瓶颈

```
100 个线程都去 CAS 同一个变量 value：

   ┌──────────┐
   │ value=0  │  ← 所有线程都抢这一个 cache line
   └──────────┘
        ↑
  T1 T2 T3 ... T100   全部撞在一起 → cache line ping-pong
```

### 4.2 LongAdder 的分散思路

```
   ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
   │Cell0│  │Cell1│  │Cell2│  │Cell3│  │Cell4│  │Cell5│  │Cell6│  │Cell7│
   │  =5 │  │  =3 │  │ =8  │  │  =7 │  │ =12 │  │  =6 │  │ =9  │  │ =4  │
   └─────┘  └─────┘  └─────┘  └─────┘  └─────┘  └─────┘  └─────┘  └─────┘
      ↑        ↑        ↑        ↑        ↑        ↑        ↑        ↑
    T1,T9   T2,T10   T3,T11   T4,T12  T5,T13   T6,T14   T7,T15   T8,T16
    (按线程 hash 分散到不同 Cell)

   sum() = 5+3+8+7+12+6+9+4 = 54
```

**关键设计**：

1. 内部维护一个 `Cell[]` 数组，每个 Cell 有自己独立的 cache line
2. 线程根据自己的 thread-local hash 选一个 Cell 来 CAS，**不再抢同一个变量**
3. **竞争自适应**：竞争激烈时 `Cell[]` 自动扩容（最多到 CPU 核数）
4. 读取时 `sum()` 把所有 Cell 加起来

### 4.3 防止 false sharing（伪共享）

`Cell` 类用了 `@Contended` 注解，让每个 Cell 独占一个 cache line（通常 64 字节）：

```java
// JDK 源码 java.util.concurrent.atomic.Striped64.Cell
@jdk.internal.vm.annotation.Contended
static final class Cell {
    volatile long value;
    Cell(long x) { value = x; }
    final boolean cas(long cmp, long val) { ... }
}
```

**为什么需要 `@Contended`**？没有它的话：

```
没有 @Contended：8 个 Cell 可能挤在 1 个 cache line 里
  cache line[64 字节]: [Cell0=5][Cell1=3][Cell2=8]...[Cell7=4]

  Core A 修改 Cell0 → invalidate 整个 cache line
  → 即使 Core B 在改 Cell1，也被波及（cache line miss，重新拉）
  → 这就是 "false sharing"，看起来分散了，实际还是抢
```

加上 `@Contended` 后，JVM 会**给字段前后填充 padding**，强制每个 Cell 独占一个 cache line：

```
有 @Contended：
  cache line 1: [pad][Cell0=5][pad pad pad...]
  cache line 2: [pad][Cell1=3][pad pad pad...]
  cache line 3: [pad][Cell2=8][pad pad pad...]
  ...

  Core A 改 Cell0 不会影响其它 Core 的 Cell1/Cell2
```

> 注意：JDK 8+ 用户类要用 `@Contended` 必须加 JVM 参数
> `-XX:-RestrictContended`（默认只对 JDK 内部类生效）。

### 4.4 用法对比

```java
// AtomicLong
AtomicLong a = new AtomicLong();
a.incrementAndGet();      // +1
a.addAndGet(5);           // +5
long total = a.get();     // 读

// LongAdder（用法几乎一样）
LongAdder b = new LongAdder();
b.increment();            // +1
b.add(5);                 // +5
long total = b.sum();     // 读：遍历 Cell[] 求和
```

**API 差别**：

| AtomicLong | LongAdder |
|---|---|
| `incrementAndGet()` | `increment()` |
| `addAndGet(x)` | `add(x)` |
| `get()` | `sum()` |
| `set(x)` | `reset()`（只能清零） |
| 支持 CAS、`getAndAdd` 返回旧值 | 不支持，只为累加优化 |

### 4.5 性能对比数据

典型 benchmark 数据（CPU: 8 核，操作: 累加 10M 次）：

| 线程数 | AtomicLong (ns/op) | LongAdder (ns/op) | LongAdder 提速 |
|---|---|---|---|
| 1 | 7 | 8 | -10%（略慢） |
| 4 | 35 | 12 | **3x** |
| 16 | 180 | 18 | **10x** |
| 64 | 720 | 25 | **28x** |
| 128 | 1500 | 30 | **50x** |

**线程数越多，LongAdder 优势越明显**：
- AtomicLong 的 CAS 失败率随线程数指数上升
- LongAdder 把竞争分散到 N 个 Cell，每个 Cell 的竞争压力被摊薄到 1/N

### 4.6 LongAdder 的代价

天下没有免费午餐。LongAdder 的取舍：

| 维度 | AtomicLong | LongAdder |
|---|---|---|
| 写性能（高并发） | 差 | **极好** ✅ |
| 写性能（单线程） | 好 | 略差（多一次 hash 查找） |
| 读 `get()` / `sum()` | O(1) 准确 | O(n) 且**不严格准确** |
| 内存占用 | 8 字节 | 几十~几百字节（多 Cell + padding） |
| API 丰富度 | 全（CAS、getAndAdd 返回旧值等） | 只能 add / sum |

**`sum()` 不严格准确的原因**：

```java
public long sum() {
    Cell[] as = cells;
    long sum = base;
    if (as != null) {
        for (Cell a : as)
            if (a != null) sum += a.value;   // 遍历期间其它线程可能正在改 Cell
    }
    return sum;
}
```

`sum()` 不持锁、不暂停其它线程，**遍历过程中其它线程可能正在写**。所以 sum 是个"最终一致的近似值"，不是某个时刻的精确快照。

**适用场景**：

| 场景 | 适合 LongAdder？ |
|---|---|
| QPS 计数、监控指标 | ✅ 完美 |
| 接口调用次数统计 | ✅ |
| 流量统计 / 字节计数 | ✅ |
| 严格的全局唯一 ID 生成 | ❌ 用 AtomicLong |
| 需要 "增加并返回新值" 的逻辑 | ❌ 用 AtomicLong |
| 需要瞬时精确值（账本、库存） | ❌ 用 AtomicLong / 锁 |

**JDK 内部使用**：

- `ConcurrentHashMap.size()` —— Java 8 改用 LongAdder 思路
- Spring Cloud / Tomcat 的指标统计
- Micrometer 监控库

### 4.7 LongAccumulator —— 通用版本

`LongAccumulator` 是 `LongAdder` 的泛化版本，支持自定义二元操作：

```java
// LongAdder 等价于 LongAccumulator (累加器)
LongAccumulator adder = new LongAccumulator(Long::sum, 0L);
adder.accumulate(5);

// 求最大值
LongAccumulator max = new LongAccumulator(Long::max, Long.MIN_VALUE);
max.accumulate(42);
max.accumulate(17);
max.accumulate(100);
System.out.println(max.get());   // 100

// 求积
LongAccumulator product = new LongAccumulator((a, b) -> a * b, 1L);
product.accumulate(2);
product.accumulate(3);
System.out.println(product.get());   // 6
```

要求：传入的二元函数必须**满足结合律和交换律**（因为 Cell 累加顺序不确定）。

---

## 五、解决方案 3：pause 指令降低自旋成本

x86 提供了 `pause` 指令，专门给自旋循环用：

```c
while (!cas(...)) {
    asm("pause");   // 提示 CPU "我在自旋，别瞎调度"
}
```

`pause` 的作用：

1. 告诉 CPU 流水线"这是个自旋循环"，避免内存乱序推测带来的代价
2. 让超线程的另一个逻辑核获得更多 CPU 资源
3. 节省功耗

**Java 标准 API**（JDK 9+）：

```java
while (!cas(...)) {
    Thread.onSpinWait();   // 跨平台：x86 → pause，ARM → yield
}
```

JVM 的 `synchronized` 自旋、`ReentrantLock` 的 spin-then-block 内部都用了 pause。
**这是底层默认就在用的优化，应用层一般不用关心**。

---

## 六、解决方案 4：退避策略 (Backoff)

CAS 失败后**不立刻重试，先退一步**，避免雪崩。

### 6.1 指数退避

```java
int delay = 1;
while (!cas(...)) {
    LockSupport.parkNanos(delay);
    delay = Math.min(delay * 2, maxDelay);   // 指数增长，封顶
}
```

类似 TCP 拥塞控制的思路。Disruptor、Cassandra 等高性能框架内部使用。

### 6.2 随机退避

```java
int failCount = 0;
while (!cas(...)) {
    Thread.onSpinWait();
    if (++failCount > threshold) {
        LockSupport.parkNanos(ThreadLocalRandom.current().nextInt(100));
    }
}
```

加随机性可以打散"多个线程同时重试"造成的二次冲突（类似 Ethernet 的 CSMA/CD）。

---

## 七、解决方案 5：阻塞同步（锁升级）

如果竞争实在太激烈（比如几百个线程抢一个资源），CAS 自旋已经 hold 不住了，
应该**直接换成阻塞锁**：

```java
private final ReentrantLock lock = new ReentrantLock();

lock.lock();
try {
    // 临界区
} finally {
    lock.unlock();
}
```

`ReentrantLock` 内部实现：**先自旋几次（轻量级），失败就 park 阻塞**
（`LockSupport.park`）。这样竞争激烈时不会一直烧 CPU。

JVM 的 `synchronized` 在 JDK 6 之后也是这个套路 —— **锁升级**：

```
偏向锁 (无竞争)
    ↓ 出现第二个线程
轻量级锁 (CAS 自旋)
    ↓ CAS 自旋多次仍失败
重量级锁 (OS mutex 阻塞)
```

每升一级，单次操作开销越大，但竞争越激烈反而越合算（因为不再烧 CPU）。

> 注意：JDK 15+ 默认禁用偏向锁（实际收益小、维护复杂）。JDK 17 起彻底废弃。

---

## 八、选型决策表

| 场景 | 推荐方案 | 理由 |
|---|---|---|
| 单线程或极低竞争 | `AtomicXxx` | 最简单 |
| **多线程高频累加（计数器、QPS）** | **`LongAdder` / `DoubleAdder`** ✅ | 分散竞争，10x+ 性能 |
| 需要"加并返回新值" | `AtomicLong` | LongAdder 不支持 |
| 需要瞬时精确值（账本、库存） | `AtomicLong` 或 `synchronized` | LongAdder sum 非精确 |
| 多变量复合操作（CAS 装不下） | `synchronized` / `ReentrantLock` | CAS 只能保护单变量 |
| 公平性要求 | `ReentrantLock(true)` | synchronized 不公平 |
| 读多写少 | `ReentrantReadWriteLock` / `StampedLock` | 读不阻塞读 |
| 需要等待/通知机制 | `ReentrantLock + Condition` | 替代 wait/notify |
| 极致性能、可接受精度损失 | LongAdder + 定时刷主存 | 监控埋点经典套路 |

---

## 九、一句话总结

> **CAS 自旋开销大的根本原因是"多线程争抢同一个变量导致 cache line 在多核间疯狂 ping-pong"。
> 解决思路有两条路线：
> （1）**分散竞争** —— 用 LongAdder 把单变量拆成多个 Cell，每个线程操作自己的 Cell，sum 时合并；
> （2）**控制自旋** —— 自适应自旋次数 + pause 指令 + 指数退避，超过阈值就 park 阻塞
> （synchronized 锁升级、ReentrantLock 都是这套）。
> JDK 8+ 的 LongAdder 是最经典的实战解法，高并发写场景比 AtomicLong 快 10 倍以上。**

---

## 附录：自己动手对比的代码

把下面这段贴到一个 main 方法里跑，能直观看到 LongAdder vs AtomicLong 的差距：

```java
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

public class CasBenchmark {
    public static void main(String[] args) throws Exception {
        for (int threads : new int[]{1, 4, 16, 64}) {
            long t1 = bench("AtomicLong   ", threads, new AtomicLong()::incrementAndGet);

            LongAdder adder = new LongAdder();
            long t2 = bench("LongAdder    ", threads, adder::increment);

            System.out.printf("[threads=%3d]  AtomicLong=%5d ms  LongAdder=%5d ms  speedup=%.1fx%n%n",
                    threads, t1, t2, (double) t1 / t2);
        }
    }

    static long bench(String name, int threads, Runnable op) throws Exception {
        int loops = 5_000_000;
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(threads);

        for (int i = 0; i < threads; i++) {
            new Thread(() -> {
                try { start.await(); } catch (InterruptedException e) { return; }
                for (int j = 0; j < loops; j++) op.run();
                done.countDown();
            }).start();
        }

        long t0 = System.currentTimeMillis();
        start.countDown();   // 同时开闸
        done.await();
        return System.currentTimeMillis() - t0;
    }
}
```

预期输出（不同机器数据有差异）：

```
[threads=  1]  AtomicLong=   45 ms  LongAdder=   58 ms  speedup=0.8x
[threads=  4]  AtomicLong=  280 ms  LongAdder=   90 ms  speedup=3.1x
[threads= 16]  AtomicLong= 1450 ms  LongAdder=  130 ms  speedup=11.2x
[threads= 64]  AtomicLong= 5800 ms  LongAdder=  210 ms  speedup=27.6x
```

---

## 参考

- [Doug Lea — JDK 8 LongAdder 设计文档](https://docs.oracle.com/javase/8/docs/api/java/util/concurrent/atomic/LongAdder.html)
- [JEP 142: Reduce Cache Contention on Specified Fields](https://openjdk.org/jeps/142) — `@Contended` 注解的引入
- [《Java 并发编程实战》第 15 章 原子变量与非阻塞同步机制](https://book.douban.com/subject/10484692/)
- [《深入理解 Java 虚拟机》第 13 章 线程安全与锁优化](https://book.douban.com/subject/34907497/)
- [Cache Line Ping-Pong 详解 (Mechanical Sympathy 博客)](https://mechanical-sympathy.blogspot.com/2011/07/false-sharing.html)
