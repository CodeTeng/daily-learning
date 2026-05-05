package com.example.demo.concurrent.threadlocal;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Demo 2: ThreadLocal 内存泄漏对比
 *
 * 真实工程场景：
 *   ThreadLocal 一般是 static final（业务里几乎都这么用），同时服务跑在线程池里
 *   场景 A：不 remove → ThreadLocalMap.Entry.value 被 worker 线程一直强引用 → 泄漏
 *   场景 B：try-finally remove → worker 处理完任务立即清，无泄漏
 *
 * 引用链：
 *   Thread (worker，长生不死)
 *     ↓ 强引用
 *   Thread.threadLocals (ThreadLocalMap)
 *     ↓ 强引用
 *   Entry { key: WeakRef<ThreadLocal>, value: 强引用 }
 *                                       ↑ 这里就是泄漏点
 *
 * 运行后观察：
 *   场景 A 跑完 GC 后堆占用 ≈ worker 数 × 单个 value 大小（每个 worker 留一份）
 *   场景 B 跑完 GC 后堆占用 ≈ 0
 */
public class ThreadLocalLeakDemo {

    /** 静态字段，模拟生产环境（如 UserContext.HOLDER） —— 自身永远不会被 GC */
    private static final ThreadLocal<byte[]> BIG_OBJECT = new ThreadLocal<>();

    private static final int WORKERS = 4;
    private static final int LOOPS = 8;
    private static final int OBJ_SIZE_MB = 30;

    public static void main(String[] args) throws Exception {
        System.out.println("========== Demo 2: ThreadLocal 内存泄漏对比 ==========");
        System.out.println("JVM 最大堆: " + Runtime.getRuntime().maxMemory() / 1024 / 1024 + " MB");
        System.out.println("worker 数=" + WORKERS + ", 任务数=" + LOOPS + ", 单个对象=" + OBJ_SIZE_MB + "MB");
        System.out.println("（理论泄漏量 ≈ " + (WORKERS * OBJ_SIZE_MB) + "MB —— 每个 worker 各留一份）\n");

        baseline();
        Thread.sleep(500);

        long leakedMB = scenarioA_NoRemove();
        Thread.sleep(500);

        long cleanMB = scenarioB_WithRemove();

        System.out.println("\n============ 对比结果 ============");
        System.out.printf("场景 A（不 remove）  GC 后剩余: %3d MB  ★ 泄漏%n", leakedMB);
        System.out.printf("场景 B（有 remove）  GC 后剩余: %3d MB  ★ 干净%n", cleanMB);

        System.out.println("\n关键结论：");
        System.out.println("  1. ThreadLocal 静态实例本身不会被 GC（key 被静态字段强引用）");
        System.out.println("  2. value 被 Thread.threadLocals 强引用 → 不 remove 永远不释放");
        System.out.println("  3. 线程池 worker 长生不死 → 每个 worker 都泄漏一份");
        System.out.println("  4. 解药唯一：try-finally { tl.remove(); }");
    }

    /** 基线：测一下空跑 + GC 之后的堆占用，作为参考 */
    private static void baseline() throws Exception {
        forceGc();
        System.out.printf(">>> 基线（启动后 + GC）: %d MB%n%n", usedMemoryMB());
    }

    private static long scenarioA_NoRemove() throws Exception {
        System.out.println(">>> 场景 A: 静态 ThreadLocal + 线程池 + 不 remove");

        ExecutorService pool = Executors.newFixedThreadPool(WORKERS);
        CountDownLatch done = new CountDownLatch(LOOPS);

        for (int i = 0; i < LOOPS; i++) {
            final int round = i;
            pool.submit(() -> {
                BIG_OBJECT.set(new byte[OBJ_SIZE_MB * 1024 * 1024]);
                System.out.printf("  [%s] 第 %d 轮 set %dMB（不 remove）%n",
                        Thread.currentThread().getName(), round, OBJ_SIZE_MB);
                // ★ 故意不调 BIG_OBJECT.remove()
                done.countDown();
            });
        }
        done.await();

        forceGc();
        long used = usedMemoryMB();
        System.out.printf("  >> GC 后堆占用: %d MB（理论泄漏 ~%d MB —— 每个 worker 留最后一份）%n",
                used, WORKERS * OBJ_SIZE_MB);

        // 关闭 worker → 线程死掉，泄漏的 value 才会随线程被回收
        pool.shutdownNow();
        pool.awaitTermination(2, TimeUnit.SECONDS);
        return used;
    }

    private static long scenarioB_WithRemove() throws Exception {
        System.out.println("\n>>> 场景 B: 同样静态 ThreadLocal，但 try-finally remove()");

        ExecutorService pool = Executors.newFixedThreadPool(WORKERS);
        CountDownLatch done = new CountDownLatch(LOOPS);

        for (int i = 0; i < LOOPS; i++) {
            final int round = i;
            pool.submit(() -> {
                try {
                    BIG_OBJECT.set(new byte[OBJ_SIZE_MB * 1024 * 1024]);
                    System.out.printf("  [%s] 第 %d 轮 set %dMB%n",
                            Thread.currentThread().getName(), round, OBJ_SIZE_MB);
                } finally {
                    BIG_OBJECT.remove();   // ★ 关键
                }
                done.countDown();
            });
        }
        done.await();

        forceGc();
        long used = usedMemoryMB();
        System.out.printf("  >> GC 后堆占用: %d MB%n", used);

        pool.shutdownNow();
        pool.awaitTermination(2, TimeUnit.SECONDS);
        return used;
    }

    private static void forceGc() throws InterruptedException {
        for (int i = 0; i < 3; i++) {
            System.gc();
            System.runFinalization();
            Thread.sleep(300);
        }
    }

    private static long usedMemoryMB() {
        Runtime r = Runtime.getRuntime();
        return (r.totalMemory() - r.freeMemory()) / 1024 / 1024;
    }
}
