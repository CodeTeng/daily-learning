// Demo: 启动若干 goroutine，观察 NumGoroutine 与 GOMAXPROCS。
//
//	go run ./cmd/goroutine-demo
package main

import (
	"fmt"
	"runtime"
	"sync"
	"time"
)

func main() {
	fmt.Printf("GOMAXPROCS = %d, NumCPU = %d\n", runtime.GOMAXPROCS(0), runtime.NumCPU())
	fmt.Printf("启动前 NumGoroutine = %d\n", runtime.NumGoroutine())

	const N = 10_000
	var wg sync.WaitGroup
	wg.Add(N)

	start := time.Now()
	for i := 0; i < N; i++ {
		go func(i int) {
			defer wg.Done()
			// 模拟一点点工作 + 主动让出
			if i%1000 == 0 {
				runtime.Gosched()
			}
		}(i)
	}

	// 在它们都退出前快照一下，能看到运行中的 goroutine 数远超 OS 线程
	time.Sleep(5 * time.Millisecond)
	fmt.Printf("运行中 NumGoroutine ≈ %d\n", runtime.NumGoroutine())

	wg.Wait()
	fmt.Printf("结束 NumGoroutine = %d，启动 %d 个 goroutine 耗时 %s\n",
		runtime.NumGoroutine(), N, time.Since(start))
}
