package com.example.demo.concurrent.threadlocal;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Demo 3: InheritableThreadLocal 父子线程传值 + 线程池场景失效
 *
 * 演示要点：
 * 1. 普通 ThreadLocal 在子线程里取不到父线程的值
 * 2. InheritableThreadLocal 可以让子线程"继承"父线程的值
 *    原理：Thread 构造函数里复制父线程的 inheritableThreadLocals
 * 3. 但 InheritableThreadLocal 在线程池里失效！
 *    因为线程池只在第一次创建 worker 时复制，之后线程被复用，不再复制
 */
public class InheritableThreadLocalDemo {

    private static final ThreadLocal<String> NORMAL = new ThreadLocal<>();
    private static final InheritableThreadLocal<String> INHERIT = new InheritableThreadLocal<>();

    public static void main(String[] args) throws Exception {
        System.out.println("========== Demo 3: InheritableThreadLocal ==========\n");

        scenario1_NormalThreadLocalFails();
        Thread.sleep(200);

        scenario2_InheritableWorks();
        Thread.sleep(200);

        scenario3_InheritableFailsInThreadPool();

        System.out.println("\n关键结论：");
        System.out.println("  1. 普通 ThreadLocal 子线程拿不到父线程的值");
        System.out.println("  2. InheritableThreadLocal 通过 Thread 构造函数 copy 值，能传给子线程");
        System.out.println("  3. ★ 但只在线程创建瞬间 copy → 线程池复用 worker 时拿到的是旧值");
        System.out.println("  4. 线程池场景必须用 TransmittableThreadLocal（阿里 TTL）或手写 ContextRunnable");
    }

    private static void scenario1_NormalThreadLocalFails() throws Exception {
        System.out.println(">>> 场景 1: 普通 ThreadLocal 子线程取不到");
        NORMAL.set("parent-value");
        System.out.println("  父线程 set 了: " + NORMAL.get());

        Thread child = new Thread(() ->
                System.out.println("  子线程 get: " + NORMAL.get() + "  ★ null（拿不到）"));
        child.start();
        child.join();
        NORMAL.remove();
    }

    private static void scenario2_InheritableWorks() throws Exception {
        System.out.println("\n>>> 场景 2: InheritableThreadLocal 子线程能继承");
        INHERIT.set("parent-value");
        System.out.println("  父线程 set 了: " + INHERIT.get());

        Thread child = new Thread(() ->
                System.out.println("  子线程 get: " + INHERIT.get() + "  ★ 拿到了"));
        child.start();
        child.join();
        INHERIT.remove();
    }

    private static void scenario3_InheritableFailsInThreadPool() throws Exception {
        System.out.println("\n>>> 场景 3: 线程池场景下 InheritableThreadLocal 失效");

        ExecutorService pool = Executors.newFixedThreadPool(1);

        INHERIT.set("v1");
        System.out.println("  父线程 set v1");
        CountDownLatch l1 = new CountDownLatch(1);
        pool.submit(() -> {
            System.out.println("  worker 第 1 次 get: " + INHERIT.get()
                    + "  （首次创建 worker，copy 了父线程的 v1）");
            l1.countDown();
        });
        l1.await();

        INHERIT.set("v2");
        System.out.println("  父线程 set v2");
        CountDownLatch l2 = new CountDownLatch(1);
        pool.submit(() -> {
            System.out.println("  worker 第 2 次 get: " + INHERIT.get()
                    + "  ★ 还是 v1！worker 没重新创建，没 copy");
            l2.countDown();
        });
        l2.await();

        INHERIT.set("v3");
        System.out.println("  父线程 set v3");
        CountDownLatch l3 = new CountDownLatch(1);
        pool.submit(() -> {
            System.out.println("  worker 第 3 次 get: " + INHERIT.get()
                    + "  ★ 仍然是 v1");
            l3.countDown();
        });
        l3.await();

        pool.shutdown();
        pool.awaitTermination(2, TimeUnit.SECONDS);
        INHERIT.remove();
    }
}
