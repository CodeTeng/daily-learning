# Linux 线上排查命令大全

> 本文整理生产环境最常用的 Linux 排查命令，按"排查思路 → 资源维度 → 真实事故 case → 命令速查"组织。
> 每个命令都标注**什么场景用、看哪一列、什么值算异常**，可直接复制使用。

## 目录

- [一、排查思路：USE 方法](#一排查思路use-方法)
- [二、按资源维度的命令](#二按资源维度的命令)
  - [2.1 系统整体（30 秒快速诊断）](#21-系统整体30-秒快速诊断)
  - [2.2 CPU](#22-cpu)
  - [2.3 内存](#23-内存)
  - [2.4 磁盘 I/O](#24-磁盘-io)
  - [2.5 网络（事故重灾区）](#25-网络事故重灾区)
  - [2.6 进程](#26-进程)
  - [2.7 日志](#27-日志)
- [三、常见线上事故 Case Study](#三常见线上事故-case-study)
  - [Case 1：服务响应慢，CPU 100%](#case-1服务响应慢cpu-100)
  - [Case 2：磁盘满，但 du 找不到大文件](#case-2磁盘满但-du-找不到大文件--经典陷阱)
  - [Case 3：OOM Killer 杀了我的进程](#case-3oom-killer-杀了我的进程)
  - [Case 4：大量 CLOSE_WAIT，连接打满](#case-4大量-close_wait连接打满)
  - [Case 5：TIME_WAIT 大量堆积，新连接建立失败](#case-5time_wait-大量堆积新连接建立失败)
  - [Case 6：Load 飙升但 CPU 不高（D 状态进程）](#case-6load-飙升但-cpu-不高d-状态进程)
  - [Case 7：Too Many Open Files](#case-7too-many-open-files)
  - [Case 8：跨服务调用慢（"是下游的问题"）](#case-8跨服务调用慢是下游的问题)
  - [Case 9：DNS 解析慢导致全站 P99 暴涨](#case-9dns-解析慢导致全站-p99-暴涨)
  - [Case 10：网卡丢包](#case-10网卡丢包)
- [四、命令速查表（按场景查）](#四命令速查表按场景查)
- [五、进阶 / Java 专用工具](#五进阶--java-专用工具)
- [六、工程经验](#六工程经验)

---

## 一、排查思路：USE 方法

碰到问题先别乱敲命令。Brendan Gregg（Netflix 性能架构师）的 **USE 方法**是工业级标准心法：

- **U**tilization 利用率（CPU / 内存 / 磁盘 / 网卡 是不是跑满了）
- **S**aturation 饱和度（有没有排队、等待）
- **E**rrors 错误数（系统调用失败、丢包、重传）

按这个顺序：先 `top` 看整体 → 锁定瓶颈资源 → 用专项工具深挖 → 找进程 → 看代码。

> **黄金 60 秒诊断脚本**（Netflix 官方推荐）：
>
> ```bash
> uptime; dmesg | tail; vmstat 1 5; mpstat -P ALL 1 5; pidstat 1 5;
> iostat -xz 1 5; free -m; sar -n DEV 1 5; sar -n TCP,ETCP 1 5; top
> ```

---

## 二、按资源维度的命令

### 2.1 系统整体（30 秒快速诊断）

```bash
uptime                    # 看 load average，1分钟/5分钟/15分钟
                          # 经验：load > CPU核数 = 有压力；持续 > 2倍 = 严重

top                       # 交互式，按 1 看每核 CPU，按 M 按内存排序，按 P 按 CPU 排序
                          # 关键列：%us 用户态 %sy 内核态 %wa IO等待 %st 被宿主机抢走

htop                      # top 的彩色升级版，强烈推荐装

vmstat 1                  # 每秒打印一行系统状态（最常用诊断命令之一）
                          # 关键列：r 运行队列长度 b D状态进程数 si/so 换页 wa IO等待

dstat -tcdngyl --top-cpu --top-io   # 一屏看 CPU/磁盘/网络/IO + TOP 进程

sar -u 1 10               # 历史 + 实时，10 秒 CPU 采样
sar -r 1 10               # 内存
sar -n DEV 1 10           # 网卡
sar -q 1 10               # 队列、load
                          # sar 神在能查历史：sar -u -f /var/log/sa/sa15 = 看本月 15 号
```

### 2.2 CPU

```bash
top -H -p <pid>           # 看进程内的所有线程 CPU 占用（Java 排查必备）
                          # 拿到高 CPU 线程的 TID，转成 16 进制后去 jstack 找

mpstat -P ALL 1           # 每核 CPU 单独看，能发现"只有一个核被打满"的死循环

pidstat 1                 # 每秒每个进程的 CPU 用量

perf top                  # 实时看哪个函数最热（需要 root）
perf record -g -p <pid> -- sleep 30 && perf report
                          # 录制 30 秒火焰图
```

### 2.3 内存

```bash
free -h                   # 关键列：available（真正可用内存，不要看 free！）
                          # buff/cache 是可回收的，OS 会自动让出来

cat /proc/meminfo         # 详细内存状态
                          # 关注：MemAvailable, Cached, Slab, SwapFree

vmstat 1                  # si/so 列：每秒换入/换出页数
                          # 不为 0 就说明在 swap，性能会断崖式下跌

ps aux --sort=-%mem | head    # 按内存排序找大户

pmap -x <pid>             # 进程的内存映射详情

dmesg | grep -i "killed process"     # 找 OOM Killer 杀过谁（极常用！）
dmesg -T | tail -50                  # 最近的内核日志（-T 显示人类时间）
```

### 2.4 磁盘 I/O

```bash
df -h                     # 各分区使用率
df -i                     # inode 使用率（小文件多容易爆 inode，df -h 还显示空闲！）

du -sh /var/* | sort -h   # 找哪个目录最大
du -h --max-depth=1 /     # 一层一层往下找

iostat -xz 1              # 每秒打印（最常用 IO 诊断命令）
                          # 关键列：
                          #   %util 设备繁忙度，>80% = 瓶颈
                          #   await 平均 IO 等待 ms，HDD>20 / SSD>1 异常
                          #   r/s w/s IOPS
                          #   rkB/s wkB/s 吞吐

iotop                     # top 的 IO 版，按 IO 排序找凶手（需要 root）

lsof | grep deleted       # 找"已删除但仍被进程持有"的文件 ★ 经典陷阱
                          # 这种文件 du 找不到，但磁盘空间不释放！

lsof <file>               # 谁在用这个文件
fuser -mv <dir>           # 谁在用这个目录/挂载点

ncdu /                    # 交互式磁盘空间分析（强烈推荐装，比 du 直观 100 倍）
```

### 2.5 网络（事故重灾区）

#### 连接与端口

```bash
ss -tlnp                  # 看所有监听端口（替代老的 netstat -tlnp）
                          # t=tcp l=listen n=不解析dns p=显示进程

ss -tnp                   # 所有 tcp 已建立连接 + 进程
ss -ant | awk '{print $1}' | sort | uniq -c    # 各种连接状态计数 ★ 必背
                          # ESTABLISHED = 正常连接
                          # TIME_WAIT  = 等待 2MSL，主动关闭方留下的（多了会耗尽端口）
                          # CLOSE_WAIT = 对方关了你没关 ★ 几乎都是程序 bug

ss -i                     # 看 socket 详情（rtt、cwnd、丢包）

netstat -s                # 协议层统计（重传、丢包、拒绝），排查"看似正常但慢"
                          # 关键看：retransmitted, listen drops, syn cookies sent
```

#### 抓包

```bash
tcpdump -i any -nn port 8080 -w /tmp/cap.pcap     # 抓 8080 端口，落盘后用 Wireshark 看
tcpdump -i any -nn -A 'host 1.2.3.4 and port 80'  # 实时看 ascii 内容
                          # 生产慎用，量大时丢包并耗 CPU。加 -c 1000 限量

tshark -i any -Y "http.request" -T fields -e http.host -e http.request.uri
                          # tshark = wireshark CLI，过滤更强
```

#### 连通性 & 路由

```bash
ping -c 4 host            # 基础联通性 + 延迟
                          # 注意：ICMP 经常被运营商限速/屏蔽，不通不一定就是断了

traceroute host           # 看每一跳路由
mtr host                  # ★★ 持续 ping + traceroute，排查链路丢包神器
                          # 关注哪一跳开始 Loss% 飙升

dig example.com           # DNS 查询（替代 nslookup，更详细）
dig +trace example.com    # 完整解析过程，从根域名开始
dig @8.8.8.8 example.com  # 指定 DNS server，对比公司 DNS 是不是有问题

curl -v -o /dev/null -w \
  "DNS:%{time_namelookup}s  TCP:%{time_connect}s  TLS:%{time_appconnect}s  TTFB:%{time_starttransfer}s  Total:%{time_total}s\n" \
  https://example.com
                          # ★★★ 一行命令拆解 HTTP 请求各阶段耗时
                          # 慢在哪一步一目了然

nc -zv host 8080          # 测试端口能不能连（telnet 替代品）
nc -l 8080                # 起一个监听用来测试
```

#### 网卡 & 流量

```bash
ip -s link                # 网卡统计：errors、dropped、collisions
ifconfig                  # 老命令，看 RX/TX errors

iftop -i eth0             # 按连接显示实时带宽（top 风格）
nethogs                   # 按"进程"显示流量 ★ 找哪个进程在跑流量

sar -n DEV 1              # 网卡历史流量
ethtool eth0              # 网卡硬件信息（速率、双工、链路状态）
ethtool -S eth0           # 网卡硬件层面统计（drops、errors）
```

### 2.6 进程

```bash
ps -ef | grep app                # 经典查进程
ps -eo pid,ppid,user,%cpu,%mem,stat,start,time,cmd --sort=-%cpu | head
                                 # 详细排序，看 STAT 列特别重要：
                                 #   R 运行  S 睡眠  D 不可中断（IO等待）★
                                 #   Z 僵尸  T 停止  + 前台

pstree -p <pid>                  # 进程树
strace -p <pid>                  # 看进程在调什么系统调用 ★ 卡住时神器
strace -c -p <pid>               # 统计 30 秒内系统调用次数和耗时
strace -e trace=network -p <pid> # 只看网络相关
                                 # 注意：strace 会让目标进程慢 10-100 倍

cat /proc/<pid>/stack            # 内核态调用栈（D 状态进程必看）
cat /proc/<pid>/status           # 进程详细信息
cat /proc/<pid>/limits           # 进程的 ulimit ★ 排查 too many open files
ls /proc/<pid>/fd | wc -l        # 进程当前打开的 fd 数

lsof -p <pid>                    # 进程打开的所有文件/socket
lsof -p <pid> | wc -l            # fd 总数
lsof -i :8080                    # 谁在用 8080 端口
```

### 2.7 日志

```bash
tail -f /var/log/app.log
tail -f -n 1000 file | grep ERROR    # 经典组合

journalctl -u myservice -f       # systemd 服务日志（实时跟）
journalctl -u myservice --since "1 hour ago"
journalctl -p err -b             # 本次启动以来的 error 级别日志
journalctl --disk-usage          # 日志占了多少空间

dmesg -T | tail -100             # 内核日志（OOM、磁盘错误、网卡 down 都在这）

zgrep ERROR /var/log/app.log.*.gz       # 直接查压缩日志
grep -A 3 -B 3 "Exception" log          # 上下文 3 行
awk '/2026-05-02 14:00/,/2026-05-02 14:30/' log    # 时间段过滤
```

---

## 三、常见线上事故 Case Study

### Case 1：服务响应慢，CPU 100%

```bash
# 1) 找到高 CPU 进程
top                                              # 比如发现 Java 进程 PID=1234 100% CPU

# 2) 找到具体哪个线程
top -H -p 1234                                   # 找到线程 TID=5678

# 3) 转 16 进制
printf '%x\n' 5678                               # = 162e

# 4) 抓 Java 线程栈，搜这个 nid
jstack 1234 | grep -A 20 'nid=0x162e'
# → 通常能看到"死循环"或"GC 线程一直在跑"

# 5) 如果是 GC，看 GC 状态
jstat -gcutil 1234 1s                            # 看 YGC/FGC 频率
jmap -heap 1234                                  # 堆内存使用
```

**典型原因**：死循环、正则灾难（catastrophic backtracking）、Full GC 频繁、HashMap 多线程死循环。

### Case 2：磁盘满，但 du 找不到大文件 ★ 经典陷阱

```bash
df -h                                            # /  100% used
du -sh /* | sort -h                              # 加起来才 30G... 但分区显示满了？

# 凶手：被进程持有的"已删除"文件
lsof | grep deleted | sort -k7 -rh | head        # 按 size 排序
# 例如：java  1234  user  3w  REG  8,1  90G  /var/log/app.log (deleted)
#                                              ↑ 90G 文件被删了但 java 还开着

# 解决方案：
# 方案A: 重启进程（最干脆）
# 方案B: 截断 fd 不重启（不停服）
> /proc/1234/fd/3                                # 把 fd 3 内容清零

# 根因修复：log 配置正确滚动，或加 logrotate 的 copytruncate
```

### Case 3：OOM Killer 杀了我的进程

```bash
dmesg -T | grep -i "killed process"              # 找 OOM 记录
# Out of memory: Killed process 1234 (java) total-vm:8GB ...

# 看系统内存历史
sar -r -f /var/log/sa/sa$(date +%d) | tail -20

# Java 应用的话，导出 heap 看泄漏点（最好提前配置 OOM 自动 dump）
# JVM 参数：-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump
jmap -dump:format=b,file=/tmp/heap.hprof <pid>   # 在线 dump（会卡几秒）
# 用 MAT/JProfiler 分析

# 临时止血：
# - 关闭 swap 后内核会更快 OOM 杀进程，加 swap 反而能扛一下
# - 给关键进程加 oom_score_adj，让 OOM Killer 少杀它
echo -1000 > /proc/<pid>/oom_score_adj
```

### Case 4：大量 CLOSE_WAIT，连接打满

```bash
ss -ant | awk '{print $1}' | sort | uniq -c
#   3 LISTEN
# 1834 CLOSE_WAIT     ← 异常！
#  234 ESTABLISHED

# CLOSE_WAIT = 对方已经发了 FIN，我方应用层没调 close()
# → 几乎 100% 是程序 bug：连接没关、try-with-resources 没用、连接池泄漏

# 找是哪个进程
ss -antp | grep CLOSE_WAIT | awk '{print $6}' | sort | uniq -c

# 程序排查方向：
# - HTTP client 没关 response body
# - JDBC connection 没关
# - try 块里有异常导致 close 没执行
```

### Case 5：TIME_WAIT 大量堆积，新连接建立失败

```bash
ss -ant | grep TIME_WAIT | wc -l                 # 几万 +
# 错误现象：connect: Cannot assign requested address

# TIME_WAIT 是主动关闭方留下的，等 2MSL (60s) 才释放
# 高并发短连接（比如 RPC client）会大量产生

# 看本机端口占用
sysctl net.ipv4.ip_local_port_range              # 默认 32768-60999，约 28K 个

# 调优（机器层面）
sysctl -w net.ipv4.tcp_tw_reuse=1                # 重用 TIME_WAIT socket（推荐）
sysctl -w net.ipv4.ip_local_port_range="10000 65535"   # 扩大端口范围
# 不要开 tcp_tw_recycle，NAT 环境会出诡异 bug，4.12 内核已删除

# 应用层修复：用长连接 / 连接池！这才是根治
```

### Case 6：Load 飙升但 CPU 不高（D 状态进程）

```bash
uptime                                           # load 50，但 top 看 CPU 才 20%
                                                 # → 经典 D 状态进程过多

# 找 D 状态进程
ps -eo state,pid,cmd | awk '$1 ~ /^D/'

# D = Uninterruptible Sleep，通常在等 IO（磁盘/NFS/网络存储）
# 看进程内核调用栈
cat /proc/<pid>/stack
# 例如看到 nfs_wait_on_request 就是 NFS 卡住了

# 验证 IO 瓶颈
iostat -xz 1                                     # %util 是不是 100%
```

### Case 7：Too Many Open Files

```bash
# 现象：Java 报 java.net.SocketException: Too many open files

# 看进程当前 fd 数
ls /proc/<pid>/fd | wc -l                        # 比如 65530
cat /proc/<pid>/limits | grep "open files"       # max = 65536，逼近上限

# fd 都用在哪了
lsof -p <pid> | awk '{print $5}' | sort | uniq -c | sort -rn
# REG=普通文件 IPv4=网络连接 sock=unix socket DIR=目录

# 是连接泄漏还是文件泄漏？
lsof -p <pid> | grep IPv4 | head                 # 大量 CLOSE_WAIT？看 Case 4
lsof -p <pid> | grep deleted                     # 有大量已删除的临时文件？

# 临时止血：调大 limit
ulimit -n 1048576                                # 当前 shell
# 永久：/etc/security/limits.conf 加 "* soft nofile 1048576"

# 根因：找代码里没关闭的资源
```

### Case 8：跨服务调用慢（"是下游的问题"）

```bash
# 用 curl 拆解每一阶段
curl -v -o /dev/null -w \
  "DNS:%{time_namelookup}s  TCP连接:%{time_connect}s  TLS握手:%{time_appconnect}s  服务端处理:%{time_starttransfer}s  总计:%{time_total}s\n" \
  https://api.downstream.com/path

# 输出例子：
# DNS:0.005s  TCP连接:0.020s  TLS握手:0.150s  服务端处理:3.200s  总计:3.205s
#                                              ↑ 锁定问题：服务端处理慢，不是网络

# 如果是网络问题：
mtr -rwzbc 100 api.downstream.com                # 100 个包看丢包和延迟
ping -c 100 api.downstream.com                   # 看延迟分布
traceroute api.downstream.com                    # 看路由变化

# 如果是 DNS 慢：
dig api.downstream.com                           # 看 Query time
dig @8.8.8.8 api.downstream.com                  # 对比公网 DNS

# 抓个包看看到底卡在哪
tcpdump -i any -nn -w /tmp/x.pcap host api.downstream.com
# 用 wireshark 看 RTT、重传、TLS 握手时间
```

### Case 9：DNS 解析慢导致全站 P99 暴涨

```bash
# 现象：偶发请求慢 5 秒（5s 是 DNS 默认超时）

dig www.api.com                                  # Query time: 5234 msec ★
strace -tt -p <pid> -e trace=network 2>&1 | grep -i dns

# 解决：
# 1) 配本地 dns cache：nscd / dnsmasq / systemd-resolved
# 2) 应用层 DNS 缓存（JVM: networkaddress.cache.ttl=60）
# 3) /etc/hosts 写死关键域名（应急用）
# 4) 调超时：/etc/resolv.conf 加 options timeout:1 attempts:2
```

### Case 10：网卡丢包

```bash
# 现象：高频丢包，RTT 抖动，重传率上升

# 网卡硬件层
ethtool -S eth0 | grep -i "drop\|err\|discard"
ip -s link show eth0                             # rx/tx errors, dropped

# 软件层（中断/队列）
cat /proc/net/softnet_stat                       # 第 2 列 drops 是 backlog 满了
                                                 # → 调大 net.core.netdev_max_backlog

# TCP 层重传
netstat -s | grep -i "retransmit\|drop"
ss -ti                                           # 看具体连接的 retrans
sar -n ETCP 1                                    # 每秒 TCP 错误统计

# 链路层
mtr target                                       # 看哪一跳丢
```

---

## 四、命令速查表（按场景查）

| 场景 | 一行命令 |
|---|---|
| 系统总体快速看一眼 | `uptime; free -h; df -h; ss -s` |
| 找最耗 CPU 的进程 | `top -o %CPU` |
| 找最耗内存的进程 | `top -o %MEM` 或 `ps aux --sort=-%mem \| head` |
| Java 找高 CPU 线程栈 | `top -H -p <pid>` → `printf '%x\n' <tid>` → `jstack <pid> \| grep -A20 'nid=0x<hex>'` |
| 看磁盘哪满了 | `du -h --max-depth=1 / \| sort -h` 或 `ncdu /` |
| 找已删除但被持有的大文件 | `lsof \| grep deleted \| sort -k7 -rh \| head` |
| 看 IO 瓶颈 | `iostat -xz 1` 看 `%util` 和 `await` |
| 看网络连接状态分布 | `ss -ant \| awk '{print $1}' \| sort \| uniq -c` |
| 看哪个进程在跑流量 | `nethogs` |
| 拆解 HTTP 请求各阶段耗时 | `curl -v -o /dev/null -w "%{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{time_total}\n" URL` |
| 链路丢包排查 | `mtr -rwzbc 100 host` |
| 看 OOM Killer 杀过谁 | `dmesg -T \| grep -i "killed process"` |
| 看进程系统调用 | `strace -tt -p <pid>` 或 `strace -c -p <pid>` 30s 后 Ctrl-C |
| D 状态进程内核栈 | `cat /proc/<pid>/stack` |
| 进程 fd 数和上限 | `ls /proc/<pid>/fd \| wc -l; cat /proc/<pid>/limits` |
| 端口被谁占了 | `lsof -i :<port>` 或 `ss -tlnp \| grep <port>` |
| 测端口连通性 | `nc -zv host port` |

---

## 五、进阶 / Java 专用工具

| 工具 | 用途 |
|---|---|
| `arthas`（阿里开源） | 在线 attach Java 进程，看方法调用栈/参数/返回值，trace 一行命令搞定 |
| `async-profiler` | 火焰图神器，CPU + 内存分配 + lock，几乎零开销 |
| `bcc-tools` / `bpftrace` | 现代内核排查瑞士军刀（基于 eBPF），看 syscall/blockio/tcpconnect 不影响生产 |
| `perf` | Linux 内置，火焰图原始数据来源 |
| `wrk` / `ab` / `vegeta` | 压测工具，复现性能问题 |
| `tcpkill` | 强制断开某条 TCP 连接（应急隔离故障客户端） |

---

## 六、工程经验

1. **不要等出事才学命令** —— 在测试环境用 `stress`、`tc` 等工具人为制造问题（CPU 满、磁盘慢、网络丢包），跑一遍上面所有 case，肌肉记忆才稳。
2. **该装就装** —— 上线机器默认装好 `htop ncdu mtr iotop iftop nethogs strace lsof tcpdump dstat sysstat`，事故时再 yum/apt 装就晚了。
3. **保留历史** —— 装 `sysstat`，`sar` 自动每 10 分钟采样保存 28 天，事后能回溯。
4. **抓现场比修复重要** —— 重启之前先抓：`jstack`、`jmap`、`tcpdump 30秒`、`top/ss 输出` 都存到 `/tmp/<时间戳>/`，事后慢慢分析。否则重启完啥都没了。
5. **永远先怀疑应用，再怀疑 OS，最后怀疑硬件** —— 顺序反了排查方向就错了。
6. **建立"事故 Runbook"** —— 每次事故复盘后把"现象 + 排查步骤 + 修复命令"沉淀成 markdown 进知识库（就像本文这样），下次同样问题 5 分钟解决。

---

## 附录：测试环境制造故障的命令

复习上面所有 case 的方法 —— 在测试机上人为造故障，用排查命令实战：

```bash
# 1. 制造 CPU 100%
stress-ng --cpu 4 --timeout 60s
yes > /dev/null &                                # 单核打满

# 2. 制造内存吃满 + OOM
stress-ng --vm 2 --vm-bytes 4G --timeout 60s

# 3. 制造磁盘 IO 满
stress-ng --io 4 --hdd 2 --hdd-bytes 1G --timeout 60s
dd if=/dev/zero of=/tmp/big bs=1M count=10000    # 写大文件

# 4. 制造磁盘满
fallocate -l 100G /tmp/fill                      # 瞬间占满
truncate -s 0 /tmp/fill                          # 清掉

# 5. 制造网络延迟和丢包（tc 神器）
tc qdisc add dev eth0 root netem delay 200ms loss 5%
tc qdisc del dev eth0 root                       # 恢复

# 6. 制造大量 TIME_WAIT
for i in {1..10000}; do curl -s http://baidu.com > /dev/null; done

# 7. 制造 D 状态进程（NFS 模拟）
# 拔掉 NFS server 网线，client 上访问挂载点的进程会立刻进 D 状态
```

---

## 参考

- [Brendan Gregg — Linux Performance](https://www.brendangregg.com/linuxperf.html)
- [Brendan Gregg — USE Method](https://www.brendangregg.com/usemethod.html)
- [Linux Performance Analysis in 60 seconds (Netflix Tech Blog)](https://netflixtechblog.com/linux-performance-analysis-in-60-000-milliseconds-accc10403c55)
- [TCP/IP 详解卷一](https://book.douban.com/subject/1088054/) — TCP 状态机和异常的根本来源
