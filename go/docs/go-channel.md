# Channel 与 select 速记

## Channel 语义速查

```go
ch := make(chan int)       // 无缓冲：发送方阻塞直到有接收方（同步交接）
ch := make(chan int, 8)    // 有缓冲：缓冲未满时发送非阻塞
close(ch)                  // 仅发送方关闭；从已关闭通道读会得到零值 + ok=false
v, ok := <-ch              // ok=false 表示通道已关闭并读完
for v := range ch { ... }  // 通道关闭后循环自动退出
```

操作矩阵：

| 操作 \ 状态 | nil | 空 | 满 | 已关闭 |
| --- | --- | --- | --- | --- |
| send | 永久阻塞 | 阻塞或入队 | 阻塞 | **panic** |
| recv | 永久阻塞 | 阻塞 | 出队 | 立即返回零值, ok=false |
| close | panic | 关闭 | 关闭 | **panic（重复关闭）** |

记住两条铁律：

1. **由发送方关闭通道**，且仅在「不会再有发送」时关闭。多生产者场景需要额外协调（如 `sync.Once` 或独立 done 通道）。
2. **不要为了通知而关闭一个还在被发送的通道**，会 panic；用专门的 `done <-chan struct{}` 通知。

## select 多路复用

```go
select {
case v := <-in:
    handle(v)
case out <- v:
    // 发送
case <-time.After(500 * time.Millisecond):
    // 超时
case <-ctx.Done():
    return ctx.Err()
default:
    // 所有 case 都没就绪时走 default（非阻塞探测）
}
```

要点：

- **多个 case 同时就绪时随机选一个**，避免饥饿。
- `nil` channel 在 select 中**永远阻塞**，可用此特性「关掉」某个 case：当不想再接收时把变量赋为 `nil`。
- `time.After` 每次都会分配一个 timer；高频循环里建议用 `time.NewTimer` + `Reset`，或直接用 `context.WithTimeout`。
- 没有 default 的 select **可以阻塞当前 goroutine**，是协调的常用手段。

## 推荐模式

### 1. 三段流水线（generator → stage → sink）

```go
nums := generate(ctx, 1, 2, 3)
sq := square(ctx, nums)
for v := range sq { fmt.Println(v) }
```

每个 stage 都接收 `ctx` 与上游 channel，自己 `defer close(out)`，下游 `range` 自然结束。看 [`internal/concurrency/pipeline.go`](../internal/concurrency/pipeline.go)。

### 2. 超时与取消

```go
ctx, cancel := context.WithTimeout(ctx, 200*time.Millisecond)
defer cancel()
select {
case res := <-call():
    use(res)
case <-ctx.Done():
    return ctx.Err()
}
```

### 3. 扇出 / 扇入（worker pool）

固定数量 worker 从 `tasks` 通道取任务，结果写入 `results` 通道；用 `sync.WaitGroup` 等所有 worker 退出后再 `close(results)`。看 [`internal/concurrency/workerpool.go`](../internal/concurrency/workerpool.go)。

## 常见坑

- **goroutine 泄漏**：忘了关闭上游或忘了消费下游，下游/上游永久阻塞。任何长期 goroutine 都应监听 `ctx.Done()`。
- **过早 close**：还有 goroutine 在写 → panic。close 应当只在「最后一个写者」之后。
- **for-select 死循环里 default 空转**：CPU 飙到 100%。如确实只是想轮询，加 `time.Sleep` 或换设计。
- **buffered channel 不是异步**：缓冲只是缓冲，满了照样阻塞，别拿它当队列扛峰。

## 验证

```bash
go run ./cmd/channel-pipeline
go run ./cmd/select-timeout
go run ./cmd/worker-pool
go test -race ./internal/concurrency/...
```
