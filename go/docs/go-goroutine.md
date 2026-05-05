# Goroutine 速记

## 是什么

Goroutine 是 Go 运行时管理的**用户态轻量级线程**。`go f()` 即可启动，初始栈仅 2 KB（按需扩容到几 GB），调度发生在 Go 运行时而不是内核。

```go
go func() {
    doWork()
}()
```

## GMP 调度模型

- **G**（Goroutine）：用户协程
- **M**（Machine）：操作系统线程
- **P**（Processor）：调度上下文，数量由 `GOMAXPROCS` 决定（默认 = 逻辑 CPU 数）

调度时机（M 把当前 G 让出 P）：

1. channel 收发阻塞 / `select` 全部 case 阻塞
2. `time.Sleep`、IO 系统调用
3. 函数调用前的**抢占点**（自 Go 1.14 起支持基于信号的异步抢占，长循环也能被抢）
4. `runtime.Gosched()` 主动让出

阻塞性系统调用会触发 **handoff**：当前 M 与 P 解绑，运行时分配新的 M 继续跑别的 G，避免 P 被一个 syscall 卡死。

## 与线程对比

| 维度 | OS 线程 | Goroutine |
| --- | --- | --- |
| 初始栈 | 1–8 MB | 2 KB（自动伸缩） |
| 切换成本 | 微秒级（陷入内核） | 几十纳秒（用户态） |
| 数量级 | 数千 | 数十万到百万 |
| 同步原语 | mutex、condvar、信号量 | channel + sync 包 |

> "Don't communicate by sharing memory; share memory by communicating." —— 优先用 channel 做协作，其次才考虑 mutex。

## 常见坑

1. **goroutine 泄漏**：启动的 goroutine 永远阻塞（如读一个再也不会被写的 channel），最终把内存耗光。所有长期 goroutine 都应能通过 `context.Context` 取消。
2. **闭包捕获 for 变量**：Go 1.22 之前 `for i := range xs { go func(){ use(i) }() }` 会全部看到末值；Go 1.22 起每轮都有独立变量，但仍建议用参数显式传入：
   ```go
   for _, x := range xs {
       go func(x T) { use(x) }(x)
   }
   ```
3. **WaitGroup 用法**：`wg.Add(n)` 必须在 `go` 之前；`wg.Done()` 用 `defer` 确保 panic 也会触发。
4. **GOMAXPROCS = CPU 数 ≠ 越多越快**：CPU 密集型适当上调 P 收益明显；IO 密集型瓶颈在外部，调高没用。

## 验证

```bash
go run ./cmd/goroutine-demo
```

代码会启动若干 goroutine，输出 `runtime.NumGoroutine()` 与 `runtime.GOMAXPROCS(0)`，让你直观感受启动开销与并行度。
