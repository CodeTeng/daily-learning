package com.example.demo.async;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicLong;

@Service
public class UserService {

    private static final Logger log = LoggerFactory.getLogger(UserService.class);

    private final AtomicLong idGen = new AtomicLong();
    private final EmailService emailService;
    private final SmsService smsService;
    private final TimedAsync timedAsync;

    public UserService(EmailService emailService, SmsService smsService, TimedAsync timedAsync) {
        this.emailService = emailService;
        this.smsService = smsService;
        this.timedAsync = timedAsync;
    }

    public User register(String name, String email, String phone) {
        User user = new User(idGen.incrementAndGet(), name, email, phone);
        log.info("[register] 用户已落库 id={} (耗时 ~50ms)", user.id());

        // 用 TimedAsync 提交：超时一到，工作线程会被 interrupt 并立刻释放。
        // 不再需要 orTimeout —— 因为 future 完成 + 线程释放在一次操作里都搞定了。
        CompletableFuture<String> emailFuture = timedAsync.submit(
                () -> emailService.sendWelcomeEmail(email),
                Duration.ofSeconds(2));

        CompletableFuture<String> smsFuture = timedAsync.submit(
                () -> smsService.sendWelcomeSms(phone),
                Duration.ofSeconds(2));

        emailFuture
                .thenAccept(messageId ->
                        log.info("[回调] 邮件发送成功 user={} messageId={}", user.id(), messageId))
                .exceptionally(ex -> {
                    Throwable cause = (ex.getCause() != null) ? ex.getCause() : ex;
                    if (cause instanceof TimeoutException) {
                        log.error("[回调] 邮件超时 user={}, 已 interrupt 工作线程并入延迟重试队列", user.id());
                    } else {
                        log.error("[回调] 邮件发送失败 user={}, 入立即重试队列", user.id(), cause);
                    }
                    return null;
                });

        smsFuture.whenComplete((sid, ex) -> {
            if (ex != null) {
                Throwable cause = (ex.getCause() != null) ? ex.getCause() : ex;
                log.error("[回调] 短信失败 user={}, cause={}", user.id(), cause.toString());
            } else {
                log.info("[回调] 短信发送成功 user={} sid={}", user.id(), sid);
            }
        });

        CompletableFuture
                .allOf(emailFuture, smsFuture)
                .whenComplete((v, ex) ->
                        log.info("[回调] 用户 {} 的所有通知任务已结束", user.id()));

        return user;
    }
}
