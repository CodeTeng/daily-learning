"""GIL 简单演示：CPU 密集 vs IO 密集场景下多线程的表现差异。

运行：
    uv run python -m learning_py.concurrent.gil_demo
"""

from __future__ import annotations

import threading
import time


def cpu_bound(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total


def io_bound(seconds: float) -> None:
    time.sleep(seconds)


def run_threads(target, args, n_threads: int) -> float:
    threads = [threading.Thread(target=target, args=args) for _ in range(n_threads)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - start


def main() -> None:
    n = 5_000_000
    print(f"[CPU bound] single: {run_threads(cpu_bound, (n,), 1):.3f}s")
    print(f"[CPU bound]   x4  : {run_threads(cpu_bound, (n,), 4):.3f}s   (受 GIL 影响，几乎无加速)")
    print(f"[IO  bound] single: {run_threads(io_bound, (1.0,), 1):.3f}s")
    print(f"[IO  bound]   x4  : {run_threads(io_bound, (1.0,), 4):.3f}s   (IO 等待时释放 GIL)")


if __name__ == "__main__":
    main()
