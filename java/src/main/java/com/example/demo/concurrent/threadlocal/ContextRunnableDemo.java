package com.example.demo.concurrent.threadlocal;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Demo 4: 手写简化版 TransmittableThreadLocal —— 解决线程池跨线程传值
 *
 * 核心思路（和阿里 TTL 一致）：
 *   1. 在【提交任务的线程】捕获当前 ThreadLocal 的值（capture）
 *   2. 在【worker 线程执行任务前】把捕获的值设到 worker 的 ThreadLocal（replay）
 *   3. 任务执行完恢复 worker 原本的值（restore）
 *
 * 这样每次提交都重新传递最新值，不像 InheritableThreadLocal 只在线程创建时 copy 一次
 *
 * 生产代码请直接用 com.alibaba.ttl.TransmittableThreadLocal
 */
public class ContextRunnableDemo {

    private static final ThreadLocal<String> TRACE_ID = new ThreadLocal<>();

    /**
     * 上下文感知的 Runnable 包装器
     * 提交时 capture，执行时 replay，结束时 restore
     */
    static class ContextRunnable implements Runnable {
        private final Runnable task;
        private final String capturedTraceId;   // ★ 在【提交线程】捕获

        ContextRunnable(Runnable task) {
            this.task = task;
            this.capturedTraceId = TRACE_ID.get();   // capture 发生在调用方线程！
        }

        @Override
        public void run() {
            String backup = TRACE_ID.get();        // worker 原本的值（一般是 null）
            try {
                TRACE_ID.set(capturedTraceId);     // ★ replay：注入捕获的值
                task.run();
            } finally {
                if (backup == null) {
                    TRACE_ID.remove();             // ★ restore（避免污染 worker）
                } else {
                    TRACE_ID.set(backup);
                }
            }
        }
    }

    public static void main(String[] args) throws Exception {
        System.out.println("========== Demo 4: 手写 ContextRunnable 解决线程池传值 ==========\n");

        ExecutorService pool = Executors.newFixedThreadPool(1);

        compareWithoutWrapper(pool);
        Thread.sleep(200);

        System.out.println();
        compareWithWrapper(pool);

        pool.shutdown();
        pool.awaitTermination(2, TimeUnit.SECONDS);

        System.out.println("\n关键结论：");
        System.out.println("  1. 直接 pool.submit() 时 worker 拿不到提交线程的 TRACE_ID（不同线程的 ThreadLocal 互相隔离）");
        System.out.println("  2. ContextRunnable 在【提交端线程】捕获，在【worker】replay → 实现传递");
        System.out.println("  3. 阿里 TTL 就是这个思路 + 包装 ExecutorService 让你无感使用");
        System.out.println("  4. 生产环境直接用 com.alibaba.ttl.TransmittableThreadLocal + TtlExecutors");
    }

    private static void compareWithoutWrapper(ExecutorService pool) throws Exception {
        System.out.println(">>> 对照组: 直接 submit Runnable（拿不到）");
        TRACE_ID.set("trace-AAAA");
        System.out.println("  [main] 设置 TRACE_ID=trace-AAAA");

        CountDownLatch l = new CountDownLatch(1);
        pool.submit(() -> {
            System.out.println("  [worker] get TRACE_ID = " + TRACE_ID.get()
                    + "  ★ null（worker 自己的 ThreadLocal 没值）");
            l.countDown();
        });
        l.await();
        TRACE_ID.remove();
    }

    private static void compareWithWrapper(ExecutorService pool) throws Exception {
        System.out.println(">>> 实验组: 用 ContextRunnable 包装");

        TRACE_ID.set("trace-BBBB");
        System.out.println("  [main] 设置 TRACE_ID=trace-BBBB");

        CountDownLatch l1 = new CountDownLatch(1);
        pool.submit(new ContextRunnable(() -> {
            System.out.println("  [worker] get TRACE_ID = " + TRACE_ID.get()
                    + "  ★ 拿到了 BBBB");
            l1.countDown();
        }));
        l1.await();

        TRACE_ID.set("trace-CCCC");
        System.out.println("  [main] 改设 TRACE_ID=trace-CCCC");

        CountDownLatch l2 = new CountDownLatch(1);
        pool.submit(new ContextRunnable(() -> {
            System.out.println("  [worker] get TRACE_ID = " + TRACE_ID.get()
                    + "  ★ 拿到了 CCCC（每次提交都重新捕获最新值）");
            l2.countDown();
        }));
        l2.await();

        TRACE_ID.remove();
    }
}
