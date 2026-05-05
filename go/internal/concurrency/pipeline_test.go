package concurrency

import (
	"context"
	"testing"
)

func TestPipeline(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	got := Collect(Square(ctx, Generate(ctx, 1, 2, 3, 4)))
	want := []int{1, 4, 9, 16}

	if len(got) != len(want) {
		t.Fatalf("len mismatch: got %v, want %v", got, want)
	}
	for i := range got {
		if got[i] != want[i] {
			t.Errorf("idx=%d: got %d, want %d", i, got[i], want[i])
		}
	}
}

func TestPipelineCancellation(t *testing.T) {
	// 取消后 generator/square 都应该尽快退出，不再阻塞。
	ctx, cancel := context.WithCancel(context.Background())
	cancel() // 立刻取消

	out := Square(ctx, Generate(ctx, 1, 2, 3))
	// 不强制断言 len==0：取决于调度，可能已经送出 0 或 1 个值。
	// 关键是 channel 必须能被关闭，否则下面的 range 会永久阻塞，go test 超时。
	for range out { //nolint:revive
	}
}
