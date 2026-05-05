package com.example.demo.concurrent.threadlocal;

import java.util.concurrent.CountDownLatch;

/**
 * Demo 1: ThreadLocal 基础用法 —— 线程隔离 + 用户上下文传递
 *
 * 演示要点：
 * 1. 同一个 ThreadLocal 实例，不同线程各自存值，互不干扰（无需加锁）
 * 2. 在调用链最深处也能直接 get()，不用一路传参
 * 3. try-finally remove() 是必须的标准姿势
 */
public class ThreadLocalBasicDemo {

    static class UserInfo {
        final long id;
        final String name;
        UserInfo(long id, String name) { this.id = id; this.name = name; }
        @Override public String toString() { return "User(" + id + "," + name + ")"; }
    }

    static class UserContext {
        private static final ThreadLocal<UserInfo> HOLDER = new ThreadLocal<>();

        static void set(UserInfo u) { HOLDER.set(u); }
        static UserInfo get() { return HOLDER.get(); }
        static void clear() { HOLDER.remove(); }
    }

    public static void main(String[] args) throws Exception {
        System.out.println("========== Demo 1: ThreadLocal 线程隔离 ==========\n");

        int reqs = 5;
        CountDownLatch done = new CountDownLatch(reqs);

        for (int i = 1; i <= reqs; i++) {
            final long uid = i;
            new Thread(() -> {
                try {
                    UserContext.set(new UserInfo(uid, "u-" + uid));
                    handleRequest();
                } finally {
                    UserContext.clear();
                    done.countDown();
                }
            }, "http-thread-" + i).start();
        }

        done.await();

        System.out.println("\n关键认知：");
        System.out.println("  1. 5 个线程共用同一个 ThreadLocal 实例，但 get() 出来各不相同");
        System.out.println("  2. Service / Mapper 层无需把 user 一路传参，直接 UserContext.get()");
        System.out.println("  3. finally 里调 remove() 是铁律 —— 否则线程池场景会内存泄漏");
    }

    private static void handleRequest() {
        log("controller 收到请求");
        orderService();
    }

    private static void orderService() {
        log("orderService 处理中");
        mapperLayer();
    }

    private static void mapperLayer() {
        UserInfo user = UserContext.get();
        try { Thread.sleep(50); } catch (InterruptedException ignore) {}
        log("mapper 落库, 当前用户=" + user);
    }

    private static void log(String msg) {
        System.out.printf("[%s] %s%n", Thread.currentThread().getName(), msg);
    }
}
