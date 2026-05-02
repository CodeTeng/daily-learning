package com.example.demo.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.task.AsyncTaskExecutor;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * "可中断超时"的异步执行器。
 *
 * 核心思路：
 *   1. 用 ExecutorService.submit() 拿到原生 Future（CompletableFuture 的 cancel 不会中断线程！）
 *   2. 调度器到点后调 future.cancel(true)，真正调用 thread.interrupt()
 *   3. 任务里所有响应中断的阻塞调用（Thread.sleep / wait / BlockingQueue.take / NIO Channel）
 *      会抛 InterruptedException，线程立刻返回到线程池，可以服务下一个任务
 *
 * 重要前提：
 *   任务里的阻塞操作必须"响应中断"。下面是常见对照：
 *     可中断  : Thread.sleep, Object.wait, BlockingQueue.take/put,
 *               LockSupport.park, NIO InterruptibleChannel, Future.get
 *     不可中断: 普通 Socket.read/write (BIO), URLConnection 默认实现,
 *               OkHttp 默认实现, 大部分 JDBC Driver, FileInputStream.read
 *   对于"不可中断"的阻塞，唯一办法是给 I/O 客户端配 readTimeout/connectTimeout。
 */
@Component
public class TimedAsync {

    private static final Logger log = LoggerFactory.getLogger(TimedAsync.class);

    private final AsyncTaskExecutor taskExecutor;
    private final ScheduledExecutorService scheduler;

    public TimedAsync(@Qualifier("notificationExecutor") AsyncTaskExecutor taskExecutor,
                      ScheduledExecutorService scheduler) {
        this.taskExecutor = taskExecutor;
        this.scheduler = scheduler;
    }

    public <T> CompletableFuture<T> submit(Callable<T> task, Duration timeout) {
        CompletableFuture<T> resultFuture = new CompletableFuture<>();

        Future<T> taskFuture = taskExecutor.submit(() -> {
            try {
                T value = task.call();
                resultFuture.complete(value);
                return value;
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                resultFuture.completeExceptionally(ie);
                throw ie;
            } catch (Throwable ex) {
                resultFuture.completeExceptionally(ex);
                throw ex;
            }
        });

        ScheduledFuture<?> timeoutHandle = scheduler.schedule(() -> {
            if (!resultFuture.isDone()) {
                // 先用 TimeoutException 完成 future，确保下游回调拿到的是超时语义；
                // 再 cancel(true) 把 interrupt 发给工作线程释放它。
                // 工作线程后续抛出的 InterruptedException 会尝试 completeExceptionally，
                // 但因为 future 已完成，是无害的 no-op。
                boolean completed = resultFuture.completeExceptionally(
                        new TimeoutException("Task timed out after " + timeout));
                boolean cancelled = taskFuture.cancel(true);
                log.warn("[TimedAsync] 触发超时 timeoutCompleted={}, cancel(true)={}", completed, cancelled);
            }
        }, timeout.toMillis(), TimeUnit.MILLISECONDS);

        resultFuture.whenComplete((r, ex) -> timeoutHandle.cancel(false));

        return resultFuture;
    }
}
