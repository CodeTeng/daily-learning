// Demo: generator → square → sink 三段流水线，复用 internal/concurrency。
//
//	go run ./cmd/channel-pipeline
package main

import (
	"context"
	"fmt"

	"github.com/zevli/learning/go/internal/concurrency"
)

func main() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	nums := concurrency.Generate(ctx, 1, 2, 3, 4, 5)
	sq := concurrency.Square(ctx, nums)

	for v := range sq {
		fmt.Printf("got %d\n", v)
	}
	fmt.Println("pipeline done")
}
