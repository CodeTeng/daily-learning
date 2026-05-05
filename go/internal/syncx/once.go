// Package syncx 演示 sync.Once 与 1.21 起引入的 sync.OnceFunc / OnceValue。
package syncx

import "sync"

// Memoizer 用 sync.Once 把第一次调用的结果记下来，后续调用直接返回缓存。
//
// 这是经典的「初始化只发生一次」的模式；并发安全且零额外锁开销（除了第一次）。
type Memoizer[T any] struct {
	once sync.Once
	val  T
	err  error
	fn   func() (T, error)
}

func NewMemoizer[T any](fn func() (T, error)) *Memoizer[T] {
	return &Memoizer[T]{fn: fn}
}

func (m *Memoizer[T]) Get() (T, error) {
	m.once.Do(func() {
		m.val, m.err = m.fn()
	})
	return m.val, m.err
}

// LazyValue 是基于 sync.OnceValue 的更简洁版本（Go 1.21+），不带 error。
//
// 与 Memoizer 比较，可以看到标准库 OnceValue 把 once + 局部变量封成了一个闭包。
func LazyValue[T any](fn func() T) func() T {
	return sync.OnceValue(fn)
}
