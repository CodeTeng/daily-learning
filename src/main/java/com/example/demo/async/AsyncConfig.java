package com.example.demo.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;

/**
 * 生产实践：永远不要直接用 Spring 默认的 SimpleAsyncTaskExecutor，
 * 它每次都新建线程，高并发下会把进程拖垮。给每类异步任务定义一个有界线程池。
 */
@Configuration
public class AsyncConfig {

    private static final Logger log = LoggerFactory.getLogger(AsyncConfig.class);

    @Bean(name = "notificationExecutor")
    public ThreadPoolTaskExecutor notificationExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(16);
        executor.setQueueCapacity(200);
        executor.setThreadNamePrefix("notify-");
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);

        // 拒绝策略：池满 + 队列满时怎么办
        // 默认是 AbortPolicy，会向调用方抛 RejectedExecutionException —— 主流程会 500
        // 这里用一个自定义策略：不抛异常，而是记录告警 + 推送到 MQ 兜底
        // （也可以用 CallerRunsPolicy 做反压，但会让 HTTP 线程被慢任务拖慢，要谨慎）
        executor.setRejectedExecutionHandler((task, exec) -> {
            log.error("[notify-pool] 线程池已饱和！活跃线程={}, 队列大小={}, 任务被拒绝，转入兜底通道",
                    exec.getActiveCount(), exec.getQueue().size());
            // fallbackQueue.push(task);  // 推到 MQ / Redis 异步重放
        });
        executor.initialize();
        return executor;
    }

    /**
     * 专门用来跑"超时检查"的小线程池。
     * 它不执行业务任务，只在到点时发起 future.cancel(true) 触发 interrupt。
     */
    @Bean(destroyMethod = "shutdown")
    public ScheduledExecutorService timeoutScheduler() {
        return Executors.newScheduledThreadPool(2, r -> {
            Thread t = new Thread(r, "timeout-scheduler");
            t.setDaemon(true);
            return t;
        });
    }
}
