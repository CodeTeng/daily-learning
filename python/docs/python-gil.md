# Python GIL 速记

## 是什么

GIL（Global Interpreter Lock，全局解释器锁）是 CPython 解释器层面的一把互斥锁：**同一时刻只允许一个线程执行 Python 字节码**。它保护的是解释器内部的数据结构（如引用计数），不是用户代码的线程安全。

## 为什么存在

- CPython 用引用计数做内存管理，多线程同时增减引用计数会损坏对象；GIL 让引用计数操作天然原子化。
- 让单线程程序、C 扩展开发更简单；移除 GIL 在历史上多次尝试，都因为单线程性能回退而搁置（PEP 703 在 3.13 引入了可选的 free-threaded 构建，但仍是实验性）。

## 影响

| 场景 | 多线程是否能加速 | 推荐方案 |
| --- | --- | --- |
| CPU 密集（数值计算、解析） | ❌ 几乎无收益 | `multiprocessing` / C 扩展（NumPy）/ `concurrent.futures.ProcessPoolExecutor` |
| IO 密集（网络、磁盘） | ✅ 能加速 | `threading` / `asyncio` |
| 混合型 | 视瓶颈而定 | 进程池 + 协程组合 |

阻塞式系统调用（`time.sleep`、socket recv 等）会**释放 GIL**，所以 IO 密集型多线程仍然有效。

## 验证

参考 `src/learning_py/concurrent/gil_demo.py`：

```bash
uv run python -m learning_py.concurrent.gil_demo
```

预期看到：CPU 密集任务从 1 线程到 4 线程几乎没有加速；IO 密集任务（`sleep`）从 4 秒压缩到约 1 秒。

## 进一步阅读

- PEP 703 — Making the Global Interpreter Lock Optional in CPython
- David Beazley, *Understanding the Python GIL* (PyCon 2010)
