// Demo: 用 internal/concurrency.WorkerPool 跑一个扇出/扇入示例。
//
//	go run ./cmd/worker-pool
package main

import (
	"context"
	"fmt"
	"time"

	"github.com/zevli/learning/go/internal/concurrency"
)

type job struct {
	id  int
	dur time.Duration
}

func main() {
	ctx := context.Background()

	tasks := make(chan job)
	go func() {
		defer close(tasks)
		for i := 1; i <= 8; i++ {
			tasks <- job{id: i, dur: 50 * time.Millisecond}
		}
	}()

	const workers = 4
	start := time.Now()
	results := concurrency.WorkerPool(ctx, workers, tasks, func(_ context.Context, j job) string {
		time.Sleep(j.dur) // 模拟工作
		return fmt.Sprintf("job#%d done", j.id)
	})

	for r := range results {
		fmt.Println(r)
	}
	// 8 个任务、每个 50ms、4 个 worker → 串行需 400ms，并行约 100ms
	fmt.Printf("总耗时 %s（workers=%d）\n", time.Since(start).Round(time.Millisecond), workers)
}
