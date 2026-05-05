// Demo: Mutex / WaitGroup / Once / atomic 的对比。
//
//	go run ./cmd/sync-demo
//	go run -race ./cmd/sync-demo   // 推荐：开 race detector
package main

import (
	"fmt"
	"sync"
	"sync/atomic"

	"github.com/zevli/learning/go/internal/syncx"
)

func main() {
	mutexCounter()
	atomicCounter()
	onceInit()
}

// 用 Mutex 保护普通 int —— 通用、灵活，但有锁开销。
func mutexCounter() {
	var (
		mu  sync.Mutex
		n   int
		wg  sync.WaitGroup
		N   = 1000
		par = 10
	)

	wg.Add(par)
	for i := 0; i < par; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < N; j++ {
				mu.Lock()
				n++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	fmt.Printf("[mutex]  expected=%d got=%d\n", par*N, n)
}

// 用 atomic 做计数器 —— 单字段更新，无锁更快。
func atomicCounter() {
	var (
		n   atomic.Int64
		wg  sync.WaitGroup
		N   = 1000
		par = 10
	)
	wg.Add(par)
	for i := 0; i < par; i++ {
		go func() {
			defer wg.Done()
			for j := 0; j < N; j++ {
				n.Add(1)
			}
		}()
	}
	wg.Wait()
	fmt.Printf("[atomic] expected=%d got=%d\n", par*N, n.Load())
}

// 用 Memoizer（基于 sync.Once）保证「昂贵初始化」只发生一次。
func onceInit() {
	var built atomic.Int32
	m := syncx.NewMemoizer(func() (string, error) {
		built.Add(1)
		return "expensive-resource", nil
	})

	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = m.Get()
		}()
	}
	wg.Wait()
	fmt.Printf("[once]   built=%d (expected 1)\n", built.Load())
}
