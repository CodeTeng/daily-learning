package com.example.demo.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class EmailService {

    private static final Logger log = LoggerFactory.getLogger(EmailService.class);

    /**
     * 同步实现。异步 + 超时 + 中断都交给 TimedAsync 在外层处理，
     * 这里只关心一件事：让阻塞操作"响应中断"，被 interrupt 时立刻退出。
     */
    public String sendWelcomeEmail(String email) throws InterruptedException {
        log.info("[email] 开始发送 -> {}  ({})", email, Thread.currentThread().getName());

        long sleepMs = (email != null && email.contains("slow")) ? 10_000 : 1500;
        try {
            Thread.sleep(sleepMs);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            log.warn("[email] 收到 interrupt，立刻退出 -> {}  ({})",
                    email, Thread.currentThread().getName());
            throw ie;
        }

        if (email != null && email.endsWith("@bad.com")) {
            throw new RuntimeException("SMTP rejected: " + email);
        }

        String messageId = "msg-" + System.currentTimeMillis();
        log.info("[email] 发送成功 -> {}, messageId={}", email, messageId);
        return messageId;
    }
}
