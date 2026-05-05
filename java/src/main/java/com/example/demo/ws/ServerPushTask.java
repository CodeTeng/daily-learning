package com.example.demo.ws;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalTime;
import java.time.format.DateTimeFormatter;

/**
 * 每 10 秒主动给所有在线客户端 push 一次服务器时间。
 * 这是 HTTP 永远做不到的事 —— 客户端没问，服务端也能说话。
 */
@Component
public class ServerPushTask {

    private static final Logger log = LoggerFactory.getLogger(ServerPushTask.class);
    private static final DateTimeFormatter FMT = DateTimeFormatter.ofPattern("HH:mm:ss");

    private final ChatWebSocketHandler handler;

    public ServerPushTask(ChatWebSocketHandler handler) {
        this.handler = handler;
    }

    @Scheduled(fixedRate = 10_000)
    public void tick() {
        int online = handler.sessions().size();
        if (online == 0) return;
        log.info("[push] 主动 push 时间给 {} 个长连客户端", online);
        handler.broadcast(String.format("【服务端 push】当前服务器时间 %s",
                LocalTime.now().format(FMT)));
    }
}
