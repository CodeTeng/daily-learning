package com.example.demo.ws;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 用一次 HTTP 调用触发"长连复用"演示：
 *   1. 服务端自己当客户端，连到自己的 /ws/chat
 *   2. 在同一个 WS session 上连续发 N 条消息
 *   3. 看服务端日志 —— N 条消息全部是同一个 sid，证明复用
 */
@RestController
public class WsSelfTestController {

    private static final Logger log = LoggerFactory.getLogger(WsSelfTestController.class);

    @GetMapping("/ws-selftest")
    public Map<String, Object> selfTest(@RequestParam(defaultValue = "20") int count) throws Exception {
        StandardWebSocketClient client = new StandardWebSocketClient();
        URI uri = URI.create("ws://localhost:8080/ws/chat");

        WebSocketSession session = client.execute(new TextWebSocketHandler() {
            @Override
            protected void handleTextMessage(WebSocketSession s, TextMessage m) {
                // ignore broadcasts, only care that we send through one connection
            }
        }, null, uri).get();

        log.info("[selftest] 客户端 sid={} 已建立长连接，将发送 {} 条消息", session.getId(), count);
        long t0 = System.currentTimeMillis();
        for (int i = 1; i <= count; i++) {
            session.sendMessage(new TextMessage("self-test #" + i));
            Thread.sleep(20);
        }
        long elapsed = System.currentTimeMillis() - t0;
        session.close();
        log.info("[selftest] 完成：在同一连接上发送 {} 条消息，耗时 {} ms", count, elapsed);

        return Map.of(
                "messages", count,
                "elapsedMs", elapsed,
                "hint", "去看服务端日志：这 " + count + " 条消息的 sid 完全相同 —— 这就是长连复用"
        );
    }

    /**
     * 验证："同一个用户开 N 个 client（=N 次 new WebSocket()）" 是否复用？
     * 答案是不复用 —— N 个 client 会拿到 N 个不同的 sid。
     */
    @GetMapping("/ws-multiclient")
    public Map<String, Object> multiClient(
            @RequestParam(defaultValue = "alice") String user,
            @RequestParam(defaultValue = "3") int clients) throws Exception {

        StandardWebSocketClient client = new StandardWebSocketClient();
        URI uri = URI.create("ws://localhost:8080/ws/chat?user=" + user);

        List<WebSocketSession> sessions = new ArrayList<>();
        List<String> sids = new ArrayList<>();

        for (int i = 0; i < clients; i++) {
            WebSocketSession s = client.execute(new TextWebSocketHandler() {
            }, null, uri).get();
            sessions.add(s);
            sids.add(s.getId());
            log.info("[multiclient] user={} 第 {} 个 client 建立, sid={}", user, i + 1, s.getId());
            s.sendMessage(new TextMessage("hi from client #" + (i + 1)));
        }

        Thread.sleep(300);
        for (WebSocketSession s : sessions) s.close();

        long distinctSids = sids.stream().distinct().count();
        return Map.of(
                "user", user,
                "clientsOpened", clients,
                "sids", sids,
                "distinctSidCount", distinctSids,
                "hint", "user=" + user + " 开了 " + clients + " 个 client，得到 " + distinctSids
                        + " 个不同 sid —— 证明每个 new WebSocket() 都是独立 TCP，不复用"
        );
    }
}
