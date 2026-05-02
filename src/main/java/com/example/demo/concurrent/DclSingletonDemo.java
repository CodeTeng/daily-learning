package com.example.demo.concurrent;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * DCL（Double-Checked Locking）双重检查锁单例 demo。
 *
 * 演示点：
 *   1. INSTANCE 必须用 volatile 修饰 —— 否则 new Singleton() 的三步可能被重排序，
 *      其它线程可能拿到"半初始化"对象（instance != null 但构造未完成）。
 *   2. 双重检查：第一次无锁判断，避免每次都进 synchronized；第二次持锁判断，
 *      防止多个线程同时通过第一次检查后都创建实例。
 *   3. 200 个线程并发抢 getInstance，最终 createdAt 应该只有 1 个值。
 *
 * 跑法:
 *   mvn -q compile
 *   java -cp target/classes com.example.demo.concurrent.DclSingletonDemo
 */
public class DclSingletonDemo {

    /**
     * DCL 单例实现 —— 这是最经典的"必须 volatile"场景。
     */
    static class Singleton {
        // ★★★ 这个 volatile 不能省。
        // new Singleton() 在字节码层面是 3 步：
        //   1) 分配内存
        //   2) 初始化对象（执行构造函数）
        //   3) INSTANCE 引用指向新对象
        // 如果发生 2、3 重排序变成 1、3、2：
        //   - 线程 A 执行到 3 时，INSTANCE 已经不为 null，但对象还没初始化
        //   - 线程 B 在第一次 if 判断时看到 INSTANCE != null，直接返回
        //   - 线程 B 拿到一个"半初始化"的对象，使用时 NPE / 数据错乱
        // volatile 会插入 StoreStore 屏障，禁止 2、3 重排序。
        private static volatile Singleton INSTANCE;

        private final long createdAt;
        private final String createdBy;

        private Singleton() {
            this.createdAt = System.nanoTime();
            this.createdBy = Thread.currentThread().getName();
            // 故意 sleep 一下放大并发竞争窗口，更容易触发 race
            try { Thread.sleep(50); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
            System.out.printf("  [Singleton] 实例创建于 nanoTime=%d，by=%s%n", createdAt, createdBy);
        }

        public static Singleton getInstance() {
            if (INSTANCE == null) {                       // 第一次检查（无锁，快路径）
                synchronized (Singleton.class) {
                    if (INSTANCE == null) {               // 第二次检查（持锁，防止重复创建）
                        INSTANCE = new Singleton();
                    }
                }
            }
            return INSTANCE;
        }

        public long createdAt() { return createdAt; }
        public String createdBy() { return createdBy; }
    }

    public static void main(String[] args) throws Exception {
        int threads = 200;
        Set<Long> uniqueIds = ConcurrentHashMap.newKeySet();
        AtomicInteger ctorCallCount = new AtomicInteger();

        CountDownLatch startGate = new CountDownLatch(1);
        CountDownLatch doneGate = new CountDownLatch(threads);

        System.out.println("启动 " + threads + " 个线程并发抢 getInstance...");

        for (int i = 0; i < threads; i++) {
            new Thread(() -> {
                try {
                    startGate.await();        // 等待统一开闸，保证真正的并发
                    Singleton s = Singleton.getInstance();
                    uniqueIds.add(s.createdAt());
                    doneGate.countDown();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }, "racer-" + i).start();
        }

        long t0 = System.currentTimeMillis();
        startGate.countDown();   // 开闸 ★ 200 线程同时冲进 getInstance
        doneGate.await();
        long elapsed = System.currentTimeMillis() - t0;

        System.out.println("\n============ 结果 ============");
        System.out.println("线程总数:           " + threads);
        System.out.println("拿到的实例数:        " + uniqueIds.size() + "  ← 应为 1");
        System.out.println("耗时:              " + elapsed + " ms");
        System.out.println("\n说明：");
        System.out.println("  1. 所有线程拿到同一个实例 → 单例语义正确");
        System.out.println("  2. 即使有 200 个线程，构造函数也只执行 1 次（看上面只打印了 1 行 [Singleton]）");
        System.out.println("  3. 大部分线程走的是第一次 if 的快路径，不需要持锁，性能好");
    }
}
