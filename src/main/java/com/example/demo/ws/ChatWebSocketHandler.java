package com.example.demo.ws;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.net.URI;
import java.util.Collection;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 群聊 WebSocket 处理器 —— "长连复用" 的物理体现就在这个类里：
 *
 *   sessions Map 是所有"活着的"长连接的容器，每个 entry = 一条客户端 TCP socket
 *
 *   一个客户端的生命周期：
 *     afterConnectionEstablished  ── put 进 map（=连接建立，TCP+TLS+HTTP Upgrade 都做完了）
 *     handleTextMessage  × N      ── 发多少消息就调多少次，全部走同一个 session、同一根 TCP
 *     afterConnectionClosed       ── 从 map 移除（连接关闭）
 *
 *   服务端可以在任意时刻调 session.sendMessage(...) 主动 push —— HTTP 永远做不到这点。
 */
@Component
public class ChatWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(ChatWebSocketHandler.class);

    // sid -> session：所有活着的连接
    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();
    // user -> set of sids：一个用户可能同时有多条连接（多 tab / 多设备）
    private final Map<String, Set<String>> userSessions = new ConcurrentHashMap<>();
    private final AtomicLong messageCounter = new AtomicLong();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        WebSocketSession safe = new ConcurrentWebSocketSessionDecorator(
                session, 5_000, 1024 * 1024);
        sessions.put(session.getId(), safe);

        String user = userOf(session);
        Set<String> sids = userSessions.computeIfAbsent(user, k -> ConcurrentHashMap.newKeySet());
        sids.add(session.getId());

        log.info("[WS] 新连接建立 user={} sid={}, 该用户连接数={}, 总在线连接={}",
                user, shortId(session), sids.size(), sessions.size());
        broadcast(String.format("【系统】%s(%s) 加入聊天室 (该用户共 %d 条连接, 全场 %d 条)",
                user, shortId(session), sids.size(), sessions.size()));
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        long n = messageCounter.incrementAndGet();
        String payload = message.getPayload();
        // 注意 sid 始终一致 —— 这就是"同一连接复用"的证据
        log.info("[WS] 收到第 {} 条消息 (复用同一 sid={}): {}", n, shortId(session), payload);
        broadcast(String.format("[%s]: %s", shortId(session), payload));
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sessions.remove(session.getId());
        String user = userOf(session);
        Set<String> sids = userSessions.get(user);
        if (sids != null) {
            sids.remove(session.getId());
            if (sids.isEmpty()) userSessions.remove(user);
        }
        int userRemaining = (sids == null) ? 0 : sids.size();
        log.info("[WS] 连接关闭 user={} sid={}, 该用户剩余连接={}, 总在线={}",
                user, shortId(session), userRemaining, sessions.size());
        broadcast(String.format("【系统】%s(%s) 离开 (该用户剩余 %d 条, 全场 %d 条)",
                user, shortId(session), userRemaining, sessions.size()));
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        log.error("[WS] 传输错误 sid={}, 错误={}", shortId(session), exception.toString());
    }

    public void broadcast(String text) {
        TextMessage message = new TextMessage(text);
        for (WebSocketSession s : sessions.values()) {
            if (!s.isOpen()) continue;
            try {
                s.sendMessage(message);
            } catch (IOException e) {
                log.error("[WS] 推送失败 sid={}", shortId(s), e);
            }
        }
    }

    public Collection<WebSocketSession> sessions() {
        return sessions.values();
    }

    /** 从 ws://host/ws/chat?user=alice 中提取 user，没有则 anonymous。 */
    private static String userOf(WebSocketSession s) {
        URI uri = s.getUri();
        if (uri == null || uri.getQuery() == null) return "anonymous";
        for (String pair : uri.getQuery().split("&")) {
            String[] kv = pair.split("=", 2);
            if (kv.length == 2 && "user".equals(kv[0])) return kv[1];
        }
        return "anonymous";
    }

    private static String shortId(WebSocketSession s) {
        String id = s.getId();
        return id.length() > 8 ? id.substring(0, 8) : id;
    }
}
