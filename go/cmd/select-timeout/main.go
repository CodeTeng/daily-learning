// Demo: select 同时处理结果、超时与取消。
//
//	go run ./cmd/select-timeout
package main

import (
	"context"
	"errors"
	"fmt"
	"math/rand/v2"
	"time"
)

// slowCall 模拟一个耗时 0~400ms 的远程调用。
func slowCall(ctx context.Context) <-chan string {
	out := make(chan string, 1)
	go func() {
		d := time.Duration(rand.IntN(400)) * time.Millisecond
		select {
		case <-time.After(d):
			out <- fmt.Sprintf("ok in %s", d)
		case <-ctx.Done():
			// 上游已经取消，没必要再交付结果
		}
		close(out)
	}()
	return out
}

func main() {
	for i := 1; i <= 5; i++ {
		ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
		fmt.Printf("[#%d] ", i)
		select {
		case res, ok := <-slowCall(ctx):
			if !ok {
				fmt.Println("被取消，无结果")
			} else {
				fmt.Println(res)
			}
		case <-ctx.Done():
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				fmt.Println("超时（>200ms）")
			} else {
				fmt.Println("ctx 已取消:", ctx.Err())
			}
		}
		cancel()
	}
}
