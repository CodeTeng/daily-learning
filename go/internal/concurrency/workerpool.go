package concurrency

import (
	"context"
	"sync"
)

// WorkerPool 是固定大小的扇出/扇入 worker pool。
//
// 用法：
//
//	results := WorkerPool(ctx, 4, tasks, func(ctx context.Context, t Task) Result {
//	    return process(ctx, t)
//	})
//	for r := range results { ... }
//
// 当 tasks 关闭、所有 worker 退出后，results 会被关闭，调用方可以放心 range。
// ctx 被取消时，每个 worker 会停止从 tasks 取下一个任务（已在跑的回调由其自己尊重 ctx）。
func WorkerPool[T, R any](
	ctx context.Context,
	workers int,
	tasks <-chan T,
	fn func(context.Context, T) R,
) <-chan R {
	if workers < 1 {
		workers = 1
	}
	results := make(chan R)

	var wg sync.WaitGroup
	wg.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			defer wg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case t, ok := <-tasks:
					if !ok {
						return
					}
					r := fn(ctx, t)
					select {
					case results <- r:
					case <-ctx.Done():
						return
					}
				}
			}
		}()
	}

	go func() {
		wg.Wait()
		close(results)
	}()
	return results
}
