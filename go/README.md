# Go 子项目

`learning/go` 是 `learning` 仓库的 Go 部分，使用 Go modules 管理。重点放在 **并发原语**（goroutine、channel、select、sync）的语义复盘与最小可运行示例。

## 目录结构

```
go/
├── README.md
├── go.mod                      # module github.com/zevli/learning/go
├── docs/                       # 知识笔记，与 cmd/internal 中的代码相互对照
│   ├── README.md
│   ├── go-goroutine.md
│   ├── go-channel.md
│   └── go-sync.md
├── cmd/                        # 每个子目录是一个独立 main 包
│   ├── goroutine-demo/         # goroutine 启动开销 / GOMAXPROCS
│   ├── channel-pipeline/       # 经典 generator → square → print 三段流水线
│   ├── select-timeout/         # select + time.After / context 取消
│   ├── worker-pool/            # 固定 worker + 任务通道
│   └── sync-demo/              # Mutex / WaitGroup / Once / atomic
└── internal/                   # 可被 cmd 与测试复用的工具代码
    ├── concurrency/            # pipeline、worker pool 通用实现 + 单测
    └── syncx/                  # sync.Once / OnceFunc 演示 + 单测
```

`internal/` 目录的导入路径仅限本模块内部使用，符合 Go 的可见性约定。

## 环境

- Go ≥ 1.22（开发用 1.26）

```bash
go version
```

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 构建全部包 | `go build ./...` |
| 跑全部测试（含 race detector 强烈推荐） | `go test -race ./...` |
| 运行某个示例 | `go run ./cmd/channel-pipeline` |
| 静态检查 | `go vet ./...` |
| 跑基准（worker pool） | `go test -bench=. -benchmem ./internal/concurrency` |
| 看模块依赖图 | `go mod graph` |

## 与 docs 的对应关系

| 笔记 | 配套代码 |
| --- | --- |
| [`docs/go-goroutine.md`](./docs/go-goroutine.md) | `cmd/goroutine-demo` |
| [`docs/go-channel.md`](./docs/go-channel.md) | `cmd/channel-pipeline`、`cmd/select-timeout`、`cmd/worker-pool`、`internal/concurrency/` |
| [`docs/go-sync.md`](./docs/go-sync.md) | `cmd/sync-demo`、`internal/syncx/` |

## 添加新主题的建议

1. 在 `docs/` 写一篇短文，先回答「是什么 / 为什么 / 何时用 / 怎么验证」。
2. 在 `cmd/<topic>/main.go` 放一段 60–120 行内的最小可运行 demo。
3. 真正可复用的逻辑放进 `internal/<area>/` 并配上 `_test.go`，用 `go test -race` 跑过。
4. 在 `docs/README.md` 与 `README.md` 的索引里登记。
