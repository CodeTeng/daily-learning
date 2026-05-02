package com.example.demo.concurrent;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * volatile 不保证原子性 demo。
 *
 * 三种计数方式对比：10 线程 × 100000 次自增，期望最终 1,000,000：
 *   1. volatile int  ← 仅可见性，不原子，结果会少（更新丢失）
 *   2. AtomicInteger ← 基于 CAS 的原子操作，结果正确且无锁
 *   3. synchronized  ← 锁保护临界区，结果正确但有阻塞开销
 *
 * 跑法:
 *   mvn -q compile
 *   java -cp target/classes com.example.demo.concurrent.AtomicityDemo
 */
public class AtomicityDemo {

    private static volatile int volatileCounter = 0;
    private static final AtomicInteger atomicCounter = new AtomicInteger(0);
    private static int syncCounter = 0;
    private static final Object lock = new Object();

    private static final int THREADS = 10;
    private static final int LOOPS = 100_000;
    private static final int EXPECTED = THREADS * LOOPS;

    public static void main(String[] args) throws Exception {
        long t1 = run("volatile (不原子)", () -> volatileCounter++);
        long t2 = run("AtomicInteger (CAS 原子)", () -> atomicCounter.incrementAndGet());
        long t3 = run("synchronized (锁原子)", () -> {
            synchronized (lock) {
                syncCounter++;
            }
        });

        System.out.println("\n============ 结果 ============");
        System.out.printf("期望值:                 %,d%n", EXPECTED);
        System.out.printf("volatile counter:       %,d  (差 %,d)  耗时 %d ms ★ 不原子，更新丢失%n",
                volatileCounter, EXPECTED - volatileCounter, t1);
        System.out.printf("AtomicInteger counter:  %,d              耗时 %d ms ★ 原子且无锁%n",
                atomicCounter.get(), t2);
        System.out.printf("synchronized counter:   %,d              耗时 %d ms ★ 原子但有锁开销%n",
                syncCounter, t3);

        System.out.println("\n关键认知：");
        System.out.println("  volatile 保证读/写本身是原子的，但 i++ 是 [读, 改, 写] 三步");
        System.out.println("  线程切换可能发生在中间任意一步 → 更新丢失");
    }

    private static long run(String name, Runnable op) throws Exception {
        Thread[] threads = new Thread[THREADS];
        long t0 = System.currentTimeMillis();
        for (int i = 0; i < THREADS; i++) {
            threads[i] = new Thread(() -> {
                for (int j = 0; j < LOOPS; j++) op.run();
            }, name + "-" + i);
            threads[i].start();
        }
        for (Thread t : threads) t.join();
        long elapsed = System.currentTimeMillis() - t0;
        System.out.printf("[%s] 完成%n", name);
        return elapsed;
    }
}
