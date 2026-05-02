package com.example.demo.concurrent;

/**
 * volatile 可见性 demo。
 *
 * 演示两个对比场景：
 *   1. 不加 volatile  → worker 线程读不到主线程的修改，死循环
 *   2. 加 volatile    → worker 线程立刻看到修改，正常退出
 *
 * 跑法（不需要 Spring Boot 启动）:
 *   mvn -q compile
 *   java -cp target/classes com.example.demo.concurrent.VisibilityDemo
 *
 * 注意：
 *   - 第一个 worker 设为 daemon，即使死循环也不会阻塞 JVM 退出
 *   - 必须在 -server 模式 / JIT 触发时才能复现死循环（默认就是 server 模式）
 *   - 如果你看到第一个测试 worker 也正常退出了，说明你的 JIT 还没来得及优化，
 *     可以把循环里的 count++ 改得更轻量，或加大 Thread.sleep 时间触发 JIT
 */
public class VisibilityDemo {

    private static boolean stopWithoutVolatile = false;
    private static volatile boolean stopWithVolatile = false;

    public static void main(String[] args) throws Exception {
        runWithoutVolatile();
        runWithVolatile();
    }

    /** 不加 volatile：worker 把 stop 缓存到自己的工作内存，永远看不到主线程的修改。 */
    private static void runWithoutVolatile() throws Exception {
        System.out.println("\n========== 测试 1: 不加 volatile ==========");

        Thread worker = new Thread(() -> {
            long count = 0;
            // JIT 会把这一行优化成"读寄存器"，永远不再去读主内存的 stopWithoutVolatile
            while (!stopWithoutVolatile) {
                count++;
            }
            System.out.println("[worker] 退出 count=" + count);
        }, "worker-no-volatile");
        worker.setDaemon(true); // 死循环也不会阻塞 JVM 退出
        worker.start();

        Thread.sleep(1500); // 留时间给 JIT 优化
        stopWithoutVolatile = true;
        System.out.println("[main] 已设置 stopWithoutVolatile=true");

        worker.join(3000); // 等最多 3 秒
        if (worker.isAlive()) {
            System.out.println("[main] ★ worker 仍在死循环 → 可见性失效（这就是要 volatile 的原因）");
        } else {
            System.out.println("[main] worker 已退出 → 该 JVM 上 JIT 没优化到，建议加大循环量重试");
        }
    }

    /** 加 volatile：worker 每次都从主内存重新读，主线程修改立即可见。 */
    private static void runWithVolatile() throws Exception {
        System.out.println("\n========== 测试 2: 加 volatile ==========");

        Thread worker = new Thread(() -> {
            long count = 0;
            while (!stopWithVolatile) {
                count++;
            }
            System.out.println("[worker] 退出 count=" + count);
        }, "worker-with-volatile");
        worker.setDaemon(true);
        worker.start();

        Thread.sleep(1500);
        stopWithVolatile = true;
        System.out.println("[main] 已设置 stopWithVolatile=true");

        worker.join(3000);
        if (worker.isAlive()) {
            System.out.println("[main] worker 仍在循环 → volatile 没生效（不应发生）");
        } else {
            System.out.println("[main] ★ worker 立刻退出 → volatile 保证了可见性");
        }
    }
}
