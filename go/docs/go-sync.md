# sync 与 atomic 速记

> 原则：能用 channel 协作就用 channel；保护一份**共享可变状态**时才用 mutex / atomic。

## sync.Mutex / RWMutex

```go
var (
    mu    sync.Mutex
    cache = map[string]string{}
)

func Get(k string) string {
    mu.Lock()
    defer mu.Unlock()
    return cache[k]
}
```

要点：

- 锁的粒度尽量小：`Lock` → 操作内存 → `Unlock`，不要在持锁期间做 IO。
- 复制结构体会复制内部 mutex，从此两份是两把锁；想避免就让结构体只能通过指针传。
- `RWMutex` 仅当读远多于写时才更优，写竞争激烈时反而比 `Mutex` 慢。
- 检测竞态：`go test -race` / `go run -race`，CI 必跑。

## sync.WaitGroup

等一组 goroutine 全部结束。

```go
var wg sync.WaitGroup
for _, x := range xs {
    wg.Add(1)
    go func(x T) {
        defer wg.Done()
        work(x)
    }(x)
}
wg.Wait()
```

- `Add` 必须发生在对应 `go` 之前，否则会出现 `Wait` 已经返回但 goroutine 还没记账的竞态。
- `Done` 用 `defer`，确保 panic 也能 -1，不然 `Wait` 永远卡住。

## sync.Once 与 OnceFunc / OnceValue（Go 1.21+）

延迟初始化、且要保证只发生一次：

```go
var (
    once sync.Once
    cli  *http.Client
)
func Client() *http.Client {
    once.Do(func() { cli = newClient() })
    return cli
}
```

Go 1.21 起更趁手：

```go
var Client = sync.OnceValue(func() *http.Client { return newClient() })
// 调用 Client() 等价于 once.Do + 返回值
```

注意：`once.Do(f)` 即使 `f` panic 也会被记为「已执行」，下次 `Do` 不会重试；如果想要可重试，得自己实现。

## sync.Map vs map+Mutex

`sync.Map` 适合**键集合很稳定、读远多于写**的场景（典型：连接缓存）。其他情况用普通 `map` + `Mutex/RWMutex` 更快、API 也更顺手。**不要默认用 sync.Map**。

## sync/atomic

只对单个字（含 `atomic.Int64/Pointer[T]` 这些 1.19 引入的泛型类型）做无锁原子操作：

```go
var hits atomic.Int64
hits.Add(1)
fmt.Println(hits.Load())
```

- 用于计数器、标志位等单字段；多字段一致性还是要 mutex。
- 不要把 atomic 与普通赋值混用同一个变量，否则就回到了 data race。

## context.Context

虽然不在 `sync` 包，但它是 Go 并发协作的事实标准：

- **取消**：`ctx, cancel := context.WithCancel(parent)`，`defer cancel()`。
- **超时**：`context.WithTimeout(parent, d)`。
- **传值**：仅用于请求作用域元数据（trace id 等），不要拿来传可选参数。

任何长期运行的 goroutine 都应在 `select` 中监听 `<-ctx.Done()` 才能被外界取消。

## 验证

```bash
go run ./cmd/sync-demo
go test -race ./internal/syncx/...
```
