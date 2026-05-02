# HTTP/2 深入讲解（含 HOL Blocking 前置知识）

> 本文整理 HTTP/2 的核心机制、与 HTTP/1.1 的差异、它解决和未解决的问题，以及 HTTP/3 (QUIC) 的演进。
> 阅读前置：了解 HTTP/1.1 的基本请求-响应模型、TCP 三次握手。

## 目录

- [一、HOL Blocking（队头阻塞）](#一hol-blocking队头阻塞)
  - [1.1 概念与餐厅类比](#11-概念与餐厅类比)
  - [1.2 HTTP/1.1 中的 HOL Blocking](#12-http11-中的-hol-blocking)
  - [1.3 浏览器的妥协方案](#13-浏览器的妥协方案)
- [二、HTTP/2 的 5 个核心设计](#二http2-的-5-个核心设计)
  - [2.1 二进制帧 (Binary Framing)](#21-二进制帧-binary-framing)
  - [2.2 流 + 多路复用 (Streams & Multiplexing)](#22-流--多路复用-streams--multiplexing--最核心)
  - [2.3 头部压缩 (HPACK)](#23-头部压缩-hpack)
  - [2.4 服务端推送 (Server Push) — 已废弃](#24-服务端推送-server-push--已废弃)
  - [2.5 流优先级 (Priority)](#25-流优先级-priority)
- [三、HTTP/1.1 vs HTTP/2 对照表](#三http11-vs-http2-对照表)
- [四、HTTP/2 的硬伤：TCP 层 HOL Blocking](#四http2-的硬伤tcp-层-hol-blocking)
- [五、HTTP/3 (QUIC) 如何彻底解决](#五http3-quic-如何彻底解决)
- [六、三代 HTTP 在 HOL Blocking 上的进化](#六三代-http-在-hol-blocking-上的进化)
- [七、与 WebSocket 的关系](#七与-websocket-的关系)
- [八、一句话总结](#八一句话总结)

---

## 一、HOL Blocking（队头阻塞）

### 1.1 概念与餐厅类比

**Head-of-Line Blocking** 字面意思就是"队头阻塞"：一队人按顺序排着，**队头那个卡住，后面所有人即使早就准备好，也只能干等**。

```
餐厅一个传菜员，订单按顺序出餐：

订单 1：佛跳墙        (要 30 分钟煮)
订单 2：白米饭        (1 分钟就好)
订单 3：拍黄瓜        (30 秒就好)
订单 4：可乐          (5 秒就好)

规则：必须按订单号顺序送
结果：佛跳墙没出锅，米饭/黄瓜/可乐就算早做好了也只能堆在窗口
      30 分钟后 4 个订单一起到桌
```

订单 1 = "head"（队头），它的延迟阻塞了后面所有人。

### 1.2 HTTP/1.1 中的 HOL Blocking

HTTP/1.1 的 **pipelining**（管道化）想让你不等响应就连续发请求：

```
不用 pipelining（默认行为）：           用 pipelining：
  → req1                                → req1 → req2 → req3
       ← resp1                                              ← resp1
  → req2                                                    ← resp2
       ← resp2                                              ← resp3
  → req3
       ← resp3
```

看起来很美，但 **RFC 强制响应必须按请求顺序返回**。问题就来了：

```
  → req1 (重 SQL 查询，30 秒)  → req2 (秒回)  → req3 (秒回)

  服务端：
    req1 处理中...
    req2 1ms 就处理完了，但被强制憋着等 resp1 先发
    req3 同理

  30 秒后：
  ← resp1 ← resp2 ← resp3   全部堆到一起回来
```

req2/req3 明明可以瞬间返回，**被 req1 这个"队头"堵了 30 秒** —— 这就是应用层 HOL blocking。

更糟的是：各种代理（Nginx、Apache、CDN）实现 pipelining 经常出错，会响应错位，bug 多到没法修。所以 **所有主流浏览器（Chrome、Firefox、Safari）都关闭了 pipelining**。

### 1.3 浏览器的妥协方案

既然 1 根 TCP 不能并发，浏览器就对同一个域名同时开 **6 根 TCP** 来并行下载资源：

```
访问 example.com 的 30 个资源：
  TCP1: req1 → resp1 → req7  → resp7  → req13 → ...
  TCP2: req2 → resp2 → req8  → resp8  → req14 → ...
  TCP3: req3 → resp3 → req9  → resp9  → req15 → ...
  TCP4: req4 → resp4 → req10 → ...
  TCP5: req5 → resp5 → req11 → ...
  TCP6: req6 → resp6 → req12 → ...
```

任何一个网页打开，浏览器底下都开着 6 根 TCP 在抢着下载资源。这也是为什么大型网站会用 `a.cdn.com` / `b.cdn.com` 这种"分域名"trick（**domain sharding**）—— 强行突破 6 连接限制。

---

## 二、HTTP/2 的 5 个核心设计

HTTP/2 (RFC 7540, 2015) 最核心的目标：**在 1 根 TCP 上消除应用层 HOL blocking**。

### 2.1 二进制帧 (Binary Framing)

HTTP/1.1 是文本协议：

```
GET /api HTTP/1.1\r\n
Host: example.com\r\n
Content-Length: 12\r\n
\r\n
hello world!
```

文本协议可读但**解析慢、易出错**（大小写、CRLF、长度字段、字符串切分）。HTTP/2 改成二进制帧：

```
 +-----------------------------------------------+
 |                 Length (24 bits)              |
 +---------------+---------------+---------------+
 |   Type (8)    |   Flags (8)   |
 +-+-------------+---------------+---------------+
 |R|              Stream Identifier (31 bits)    |
 +=+=============================================+
 |                Frame Payload                ...
 +-----------------------------------------------+
```

每帧固定结构：长度、类型、标志、stream ID、payload。机器解析极快。

常见帧类型：


| 帧类型             | 作用                  |
| --------------- | ------------------- |
| `HEADERS`       | 携带 HTTP 请求/响应头      |
| `DATA`          | 携带 body             |
| `SETTINGS`      | 双方协商参数（窗口大小、最大并发流等） |
| `PING`          | 心跳保活                |
| `PRIORITY`      | 设置 stream 优先级       |
| `RST_STREAM`    | 终止单个 stream         |
| `GOAWAY`        | 优雅关闭整个连接            |
| `WINDOW_UPDATE` | 流控窗口更新              |
| `PUSH_PROMISE`  | 服务端推送通知（已废弃）        |


### 2.2 流 + 多路复用 (Streams & Multiplexing) ← 最核心

HTTP/2 在一根 TCP 上引入"**流**"的概念。每个请求 = 一条 stream，有唯一 stream ID。多条 stream 的帧可以**任意交错**在 TCP 上传输：

```
HTTP/1.1 keep-alive (串行):
  TCP: [req1][resp1   ][req2][resp2 ][req3][resp3]
  时间 ─────────────────────────────────────────→

HTTP/2 multiplexing (并发):
  TCP: [s1:HEADER][s2:HEADER][s3:HEADER][s2:DATA][s1:DATA片段1][s3:DATA][s1:DATA片段2]
                                          ↑ s2 先返回也行，顺序无关
  时间 ─────────────────────────────────────────────────────────────────→
```

每帧带 stream ID，接收方根据 ID 重新组装到对应的逻辑请求里。这就是多路复用。

回到 30 秒重查询的例子：

```
HTTP/2:
  client: → s1:HEADERS (重查询) → s2:HEADERS (秒回) → s3:HEADERS (秒回)

  服务端 s1 处理中... 同时 s2/s3 早就完成：
  server: ← s2:HEADERS+DATA   (1ms 后到达)   ← 不用等 s1
  server: ← s3:HEADERS+DATA   (2ms 后到达)   ← 不用等 s1
  server: ← s1:HEADERS+DATA   (30 秒后到达)
```

s2、s3 不再被 s1 阻塞 —— **应用层 HOL blocking 被消除了**。

### 2.3 头部压缩 (HPACK)

HTTP/1.1 每个请求都重发完整 header，非常冗余：

```
GET /api/posts HTTP/1.1
Host: example.com                 ← 每次都一样
User-Agent: Mozilla/5.0 ...        ← 每次都一样 (~120 字节)
Accept: text/html...
Cookie: sessionId=abc123, ...      ← 每次都一样 (~200 字节)
```

100 个请求 = 100 次重复发同样的 cookie。

**HPACK** 用了双方维护的两张表：


| 表类型               | 内容                                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------------------- |
| **静态表** (61 项，固定) | 最常见的 header，例如：索引 2 = `:method GET`，索引 7 = `:scheme https`，索引 16 = `accept-encoding: gzip, deflate` |
| **动态表** (运行时增长)   | 本次连接出现过的自定义 header，双方同步维护                                                                           |


```
第一次请求 cookie:
  完整发送 "cookie: sessionId=abc123"  (~30 字节)
  → 双方都把它登记到动态表的索引 [62]

后续请求 cookie:
  只发 "用索引 62"  (1 字节)
```

100 个请求的 header 总开销从几十 KB 压缩到几百字节。

### 2.4 服务端推送 (Server Push) — 已废弃

**设计意图**：客户端请求 `index.html`，服务端预测客户端马上会要 `style.css`、`app.js`，主动推过去，省一个 RTT：

```
client: → GET /index.html
server: ← PUSH_PROMISE /style.css    (我马上要给你推 style.css)
server: ← PUSH_PROMISE /app.js
server: ← /index.html 的内容
server: ← /style.css 的内容
server: ← /app.js 的内容
```

**实际表现很差**：

- 服务端不知道客户端缓存里已经有什么，经常推已缓存过的资源（浪费）
- 实现复杂、难调试
- 实测收益小于其它优化

**Chrome 在 2022 年移除了支持**，Firefox 也跟进。**所以"HTTP/2 解决了 server push"是错的** —— 真要 server push 现在还得用 WebSocket 或 SSE (Server-Sent Events)。

### 2.5 流优先级 (Priority)

客户端可以告诉服务端哪个 stream 更重要（CSS 比图片重要、首屏比下方重要），服务端尽量优先处理高优先级 stream。

例如浏览器渲染时：


| 资源            | 优先级     |
| ------------- | ------- |
| HTML          | 最高      |
| CSS / 字体      | 高（阻塞渲染） |
| 同步 JS         | 高       |
| 图片（首屏）        | 中       |
| 图片（下方）/ 异步 JS | 低       |


---

## 三、HTTP/1.1 vs HTTP/2 对照表


| 维度               | HTTP/1.1 keep-alive | HTTP/2                           |
| ---------------- | ------------------- | -------------------------------- |
| 协议格式             | 文本                  | 二进制帧                             |
| 同 TCP 内并发        | ❌ 串行                | ✅ 多路复用                           |
| 应用层 HOL blocking | ✅ 严重                | ❌ 消除                             |
| Header 压缩        | 无（body 可 gzip）      | HPACK                            |
| 浏览器对同域开几根 TCP    | 6 根                 | 1 根                              |
| Server push      | ❌                   | ⚠️ 名义支持，实际废弃                     |
| 浏览器是否要求 HTTPS    | 否                   | **是**（h2 over TLS；h2c 明文版浏览器不支持） |
| 协议版本号            | `HTTP/1.1`          | `HTTP/2.0`                       |
| ALPN 协议标识        | `http/1.1`          | `h2` (TLS) / `h2c` (明文)          |


---

## 四、HTTP/2 的硬伤：TCP 层 HOL Blocking

HTTP/2 消除了**应用层** HOL，但还有一个更底层的 HOL blocking 它**根本无法解决**：

> **TCP 是一根字节流，丢包必须按顺序重传。**

```
HTTP/2 把 4 个 stream 塞进 1 根 TCP：

  TCP 字节流：[s1 frame][s2 frame][s3 frame][s2 frame][s1 frame]
                          ↑ 这个 IP 包丢了

TCP 协议规定：丢的包没补回来之前，后续字节都不交给应用层
  → s3、s4 的帧早就到达内核缓冲区了，但 TCP 不放它们上去
  → 4 个 stream 全部停下等丢包重传
```

讽刺的事实：**HTTP/2 在弱网下反而比 HTTP/1.1 更糟**：

- HTTP/1.1 用 6 根独立 TCP，丢一个包只影响 1 根
- HTTP/2 用 1 根 TCP 把所有 stream 装进去，丢一个包**所有 stream 都卡住**

---

## 五、HTTP/3 (QUIC) 如何彻底解决

HTTP/3 (RFC 9114, 2022) 直接把 TCP 换掉了，跑在 **QUIC** 协议上。

QUIC 是基于 UDP 的可靠传输协议（Google 主导，2021 年成为 IETF 标准）。

**关键设计**：每个 stream 独立维护接收顺序

```
QUIC 的设计：
  s1 的字节流  ←  独立的滑动窗口、独立的丢包重传
  s2 的字节流  ←  独立的
  s3 的字节流  ←  独立的
  s4 的字节流  ←  独立的
        ↓
       UDP 包

  s1 丢一个包：只有 s1 卡住，s2/s3/s4 继续上交应用层
```

加上 QUIC 的 **0-RTT / 1-RTT 握手**（普通 TLS 1.3 over TCP 是 2-RTT），HTTP/3 在弱网/高丢包/移动场景下显著优于 HTTP/2。

**部署现状**（截至 2026）：Cloudflare、Google、Meta、字节、阿里云等都已全面部署 HTTP/3。

---

## 六、三代 HTTP 在 HOL Blocking 上的进化


| 协议                     | 应用层 HOL            | TCP 层 HOL     |
| ---------------------- | ------------------ | ------------- |
| HTTP/1.1（关 pipelining） | ✅ 严重，但用 6 TCP 部分缓解 | ✅ 6 TCP 影响有限  |
| HTTP/1.1（开 pipelining） | ✅ 极严重，已废弃          | ✅             |
| HTTP/2                 | ❌ **消除**           | ✅ **还在，且更严重** |
| HTTP/3 (QUIC)          | ❌ 消除               | ❌ 消除          |


---

## 七、与 WebSocket 的关系

WebSocket 也是建立在 TCP 上的，所以**也吃 TCP 层 HOL blocking** —— 一个 frame 的 IP 包丢了，后续 frame 都卡住。

不同场景下的影响：


| 场景             | TCP 层 HOL 影响    | 推荐方案                                 |
| -------------- | --------------- | ------------------------------------ |
| 聊天 / IM        | 极小（消息频率 << 丢包率） | **WebSocket 完全够用**                   |
| 在线协作（文档、白板）    | 小               | WebSocket                            |
| 实时行情           | 小～中             | WebSocket                            |
| 多人 FPS 游戏      | 大（丢包卡顿不可接受）     | UDP 自定义协议                            |
| 实时音视频          | 大               | WebRTC (over UDP)                    |
| 浏览器内需要 QUIC 性能 | 大               | **WebTransport** (基于 HTTP/3 的浏览器新标准) |


---

## 八、一句话总结

> **HOL blocking 就是"队头阻塞"：一个慢操作让整个队列的后续操作干等。HTTP/1.1 的 pipelining 在应用层有这个问题（已废弃），HTTP/2 用 stream + multiplexing 消除了应用层 HOL，但 TCP 层 HOL 还在；HTTP/3 用 QUIC（UDP 上自建可靠传输）才彻底消除。WebSocket 没改变 TCP 层这件事，所以高丢包率场景下也会有同样的限制。**

---

## 附录：在 Spring Boot 3 中启用 HTTP/2

只需一行配置（Tomcat / Undertow / Netty 都支持）：

```properties
# application.properties
server.http2.enabled=true

# 浏览器要求 HTTP/2 必须 HTTPS，所以也要开 SSL
server.ssl.enabled=true
server.ssl.key-store=classpath:keystore.p12
server.ssl.key-store-password=changeit
server.ssl.key-store-type=PKCS12
```

验证：

```bash
# 用 curl 强制 HTTP/2，看响应头里的协议版本
curl -v --http2 https://localhost:8443/api/foo

# 应该能看到：
# * Using HTTP2, server supports multiplexing
# * h2 [:method: GET]
```

注意 ALPN（Application-Layer Protocol Negotiation）：浏览器和服务端在 TLS 握手阶段通过 ALPN 字段协商使用 `h2` 还是 `http/1.1`。如果服务端不支持 ALPN（旧 JDK），HTTP/2 就降级回 HTTP/1.1。Java 9+ 原生支持 ALPN，无需额外配置。

---

## 参考

- [RFC 7540 — HTTP/2](https://datatracker.ietf.org/doc/html/rfc7540)
- [RFC 7541 — HPACK: Header Compression for HTTP/2](https://datatracker.ietf.org/doc/html/rfc7541)
- [RFC 9114 — HTTP/3](https://datatracker.ietf.org/doc/html/rfc9114)
- [RFC 9000 — QUIC: A UDP-Based Multiplexed and Secure Transport](https://datatracker.ietf.org/doc/html/rfc9000)

