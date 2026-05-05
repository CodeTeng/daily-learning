// Package concurrency 提供 channel 流水线与 worker pool 的通用工具，
// 用来配合 docs/go-channel.md 中的概念。
package concurrency

import "context"

// Generate 把任意数量的整数发送到一个新 channel，并在结束 / ctx 取消时关闭它。
//
// 调用方负责 range 读取。返回的 channel 由本函数关闭。
func Generate(ctx context.Context, nums ...int) <-chan int {
	out := make(chan int)
	go func() {
		defer close(out)
		for _, n := range nums {
			select {
			case out <- n:
			case <-ctx.Done():
				return
			}
		}
	}()
	return out
}

// Square 读取 in，将每个值平方后发送到返回的 channel。
//
// in 关闭或 ctx 取消时，返回 channel 也会被关闭，形成自然的级联退出。
func Square(ctx context.Context, in <-chan int) <-chan int {
	out := make(chan int)
	go func() {
		defer close(out)
		for v := range in {
			select {
			case out <- v * v:
			case <-ctx.Done():
				return
			}
		}
	}()
	return out
}

// Collect 把 channel 内剩余元素读到 slice 中，便于测试断言。
func Collect[T any](ch <-chan T) []T {
	var out []T
	for v := range ch {
		out = append(out, v)
	}
	return out
}
