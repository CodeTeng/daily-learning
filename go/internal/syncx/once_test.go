package syncx

import (
	"errors"
	"sync"
	"sync/atomic"
	"testing"
)

func TestMemoizerOnlyRunsOnce(t *testing.T) {
	var calls atomic.Int32
	m := NewMemoizer(func() (int, error) {
		calls.Add(1)
		return 42, nil
	})

	const N = 50
	var wg sync.WaitGroup
	wg.Add(N)
	for i := 0; i < N; i++ {
		go func() {
			defer wg.Done()
			v, err := m.Get()
			if err != nil || v != 42 {
				t.Errorf("unexpected: v=%d err=%v", v, err)
			}
		}()
	}
	wg.Wait()

	if got := calls.Load(); got != 1 {
		t.Fatalf("fn should run once, got %d", got)
	}
}

func TestMemoizerCachesError(t *testing.T) {
	want := errors.New("boom")
	var calls atomic.Int32
	m := NewMemoizer(func() (int, error) {
		calls.Add(1)
		return 0, want
	})

	for i := 0; i < 3; i++ {
		if _, err := m.Get(); !errors.Is(err, want) {
			t.Fatalf("expected wrapped err, got %v", err)
		}
	}
	if got := calls.Load(); got != 1 {
		t.Fatalf("fn should still run only once on error, got %d", got)
	}
}

func TestLazyValue(t *testing.T) {
	var calls atomic.Int32
	get := LazyValue(func() string {
		calls.Add(1)
		return "hello"
	})

	for i := 0; i < 5; i++ {
		if got := get(); got != "hello" {
			t.Fatalf("got %q", got)
		}
	}
	if got := calls.Load(); got != 1 {
		t.Fatalf("fn should run once, got %d", got)
	}
}
