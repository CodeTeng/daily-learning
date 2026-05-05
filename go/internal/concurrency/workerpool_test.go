package concurrency

import (
	"context"
	"sort"
	"testing"
)

func TestWorkerPool(t *testing.T) {
	ctx := context.Background()

	tasks := make(chan int)
	go func() {
		defer close(tasks)
		for i := 1; i <= 10; i++ {
			tasks <- i
		}
	}()

	results := WorkerPool(ctx, 4, tasks, func(_ context.Context, n int) int {
		return n * n
	})

	got := Collect(results)
	if len(got) != 10 {
		t.Fatalf("expected 10 results, got %d", len(got))
	}

	sort.Ints(got)
	for i, v := range got {
		want := (i + 1) * (i + 1)
		if v != want {
			t.Errorf("idx=%d: got %d, want %d", i, v, want)
		}
	}
}

func TestWorkerPoolCancel(t *testing.T) {
	// 验证 ctx 取消后 results 会被关闭，避免泄漏。
	ctx, cancel := context.WithCancel(context.Background())

	tasks := make(chan int)
	results := WorkerPool(ctx, 2, tasks, func(_ context.Context, n int) int { return n })

	cancel()
	close(tasks) // 让 worker 也能从 range 路径退出

	for range results { //nolint:revive
	}
}
