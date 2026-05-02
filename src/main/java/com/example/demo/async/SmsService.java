package com.example.demo.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class SmsService {

    private static final Logger log = LoggerFactory.getLogger(SmsService.class);

    public String sendWelcomeSms(String phone) throws InterruptedException {
        log.info("[sms] 开始发送 -> {}  ({})", phone, Thread.currentThread().getName());
        try {
            Thread.sleep(1000);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            log.warn("[sms] 收到 interrupt，立刻退出 -> {}", phone);
            throw ie;
        }

        String sid = "sms-" + System.currentTimeMillis();
        log.info("[sms] 发送成功 -> {}, sid={}", phone, sid);
        return sid;
    }
}
