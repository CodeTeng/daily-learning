# 《AI大模型Ragent项目》——Ragent为什么从Milvus换成Pgvector？

## 为什么从 Milvus 换成了 Pgvector

不少同学跟着 RAG 系列一路学下来，前面讲向量数据库的时候，花了挺大篇幅讲 Milvus——从 Docker Compose 启动、HNSW 索引参数到标量过滤，demo 代码一行一行跑完。结果翻开 Ragent 的源码，却发现项目里主力用的是 PostgreSQL 的 pgvector 扩展。

有同学在群里问我：“教程里用的 Milvus，怎么后面反而不用了？”

这个问题我必须得单独拎出来聊一聊，不然容易被误解 Milvus 不如 pgvector。

## 先把话说清楚：Milvus 没有被否定

在回答为什么换之前，先把一件事摆正：**Ragent 从 Milvus 换到 pgvector，不是因为 Milvus 不好**。

RAG 系列里写过的那些 Milvus 优势，放在现在依然成立：

- 专为向量检索而生，从存储布局到查询引擎都是围绕向量设计的

- HNSW、IVF_FLAT、IVF_SQ8、DISKANN……索引类型几乎一网打尽，不同数据规模都能找到合适的算法

- Java SDK 成熟，v2 API 设计清晰

- 数据规模覆盖广，Standalone 单机模式可以撑百万级，集群模式能扛到十亿级

- 支持标量字段过滤、Partition 分区、BM25 原生全文检索、混合检索 RRF 融合

所以在 RAG 教学里我依然推荐大家先用 Milvus 跑通一遍——它是一个**功能最全的专业向量库**，原理讲清楚了之后，换任何一个向量库都是变成另一个 API 的事。

但“最全”不等于“最合适”。Ragent 是一个真实要部署、要运维、要让读者能跑起来、要长期迭代的项目，选型的优先级和教学 demo 完全不一样。

> 一句话概括：教学上我推荐 Milvus，是因为它能把向量检索的原理和能力完整地展示出来；工程上 Ragent 选 pgvector，是因为在它要解决的问题上，pgvector 的综合成本更低。

## Milvus 在真实项目里的代价

Milvus 的能力是实打实的，但这些能力不是免费的。把它丢进一个真实项目里，有几个代价你绕不过去。

### 1. 部署组件多，运维成本不低

一个 Milvus Standalone，不是你 `docker run` 一个镜像就完事的。翻开我们之前教程里那份 `docker-compose.yml`，你会看到至少拉起来四个容器：

| 组件 | 作用 | 能省吗 |
| --- | --- | --- |
| milvus-standalone | Milvus 服务本体 | 不能 |
| etcd | 存储 Milvus 的集群元数据 | 不能 |
| minio / rustfs | 对象存储，放索引文件和日志 | 不能 |
| attu（可选） | 可视化管理面板 | 能，但你大概率会装 |

这还只是单机版。一旦上集群模式，还会多出 pulsar / kafka、proxy、query node、data node、index node 等一堆角色。每一个新组件，都是一份额外的运维负担：要加监控、要留日志、要考虑备份恢复、要做版本兼容。

对一个小团队或一个希望让读者能够快速跑起来的项目而言，拉起来四五个容器才能跑起来向量检索，心智成本真的不低。

### 2. 对部署环境有隐性要求

Milvus 的 Standalone 镜像对运行环境是挑食的。你去翻它的 `docker-compose.yml`，会看到这样一行：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
security_opt: - seccomp:unconfined
```

这不是随手加的——Milvus 里某些向量计算走的是比较底层的 SIMD 指令和内存映射，默认的 seccomp 策略会拦掉部分系统调用，必须放开才能正常跑。在一些受限的宿主环境（公司统一的 K8s 集群、企业内网服务器、某些云厂商的托管容器服务）里，放开 seccomp 需要走审批，这就是一道坎。

本地开发也有坑：Windows + WSL2 下挂载卷的路径有时候会让 etcd 起不来；Mac 下 arm64 架构对某些 Milvus 版本的镜像兼容性偶尔翻车；Linux 内核太老的机器上 pulsar / mmap 可能报奇怪的错。这些问题都能解决，但每一个都会消耗同学们不少时间。

> 我自己最初在 Linux 上跑 Milvus 也折腾过——一个容器起不来，查日志、翻 issue、改配置，花了一上午才搞定。最后发现是不兼容 Centos 的版本，如果有些同学线上服务器是这种，再换成本就很高了。

### 3. 资源占用大，尤其是内存

Milvus 的 HNSW 索引是常驻内存的。之前讲解里我给过一个粗估：100 万个 4096 维向量，HNSW（M=16）大约要 16~20 GB 内存。

这意味着——你的向量库数据一多，内存就得跟着涨。而且向量数据是和你的业务 MySQL、Redis 互相独占资源的，它不能和业务库共用那台 8 核 16G 的小机器，得单独规划机器预算。

对一个百万 chunk 以下的企业知识库项目来说，这笔预算是不是非花不可？其实未必。

### 4. 和业务数据库分离，事务一致性要自己兜底

这是 Ragent 换掉 Milvus 最根本的一个原因，单开一节讲。

## 跨库没有事务：一个真实场景

先看 Ragent 的知识库数据模型。删掉一篇文档的时候，要动的表有这些：

| 表 | 作用 |
| --- | --- |
| t_knowledge_document | 文档主表（标题、来源、状态） |
| t_knowledge_chunk | 分块表（chunk 文本、位置、hash） |
| t_knowledge_document_chunk_log | 分块日志表（审计用） |
| t_knowledge_vector | 向量存储表（embedding + metadata） |

在 Milvus 方案下，前三张表在 MySQL 里，最后一张向量数据在 Milvus。删除文档这个看似简单的操作，你会发现怎么写都别扭。

最直觉的写法是把 Milvus 调用放进 `@Transactional` 方法里：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
@Transactional(rollbackFor = Exception.class) public void deleteDocument(String docId) { // 1. 删 MySQL 里的文档主表 documentMapper.deleteById(docId); // 2. 删 MySQL 里的分块表（省略了日志表的删除） chunkMapper.deleteByDocId(docId); // 3. 删 Milvus 里的向量数据 milvusClient.delete(DeleteReq.builder() .collectionName("customer_service_chunks") .filter("doc_id == \"" + docId + "\"") .build()); }
```

但 Milvus 根本不参与 JDBC 事务——`@Transactional` 管得住 MySQL 那两条 delete，管不住第 3 步。如果 step 3 抛异常，MySQL 倒是会回滚（数据没丢），但你白调了前两步；更麻烦的是 step 3 **超时但实际 Milvus 侧已经执行了删除**这种不确定场景——客户端不知道向量到底删没删，后续是补删还是不补，全靠猜。

所以实际工程中更常见的做法是：**先提交 MySQL 事务，再异步删 Milvus**。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
@Transactional(rollbackFor = Exception.class) public void deleteDocument(String docId) { documentMapper.deleteById(docId); chunkMapper.deleteByDocId(docId); // MySQL 事务提交后，再异步删 Milvus TransactionSynchronizationManager.registerSynchronization( new TransactionSynchronization() { @Override public void afterCommit() { milvusClient.delete(DeleteReq.builder() .collectionName("customer_service_chunks") .filter("doc_id == \"" + docId + "\"") .build()); } }); }
```

这样保证了 MySQL 数据的完整性，但引入了一个新问题：**afterCommit 里的 Milvus 调用如果失败了怎么办？** MySQL 事务已经提交了不能回滚，Milvus 里的向量还留着——变成了**脏向量**，下次检索还会被捞出来，命中一堆内容已不存在的记录。

反过来也一样尴尬：如果你选择先删 Milvus 再提交 MySQL，Milvus 删成功了但 MySQL 提交失败回滚——业务上看文档还在，但向量没了，永远检索不到。

**不管你怎么编排顺序，只要数据分散在两个不参与同一事务的系统里，就必然存在中间状态不一致的窗口**。

解决方案当然有：本地消息表 + 补偿任务、分布式事务框架（Seata）、定时对账脚本。但每一个方案都在给项目增加复杂度——你要写消息表、要有后台 job 扫脏数据、要处理并发补偿、要考虑对账任务本身的幂等。这些都不是业务逻辑，但都是必须做的工程投入。

**对一个企业知识库场景来说，数据一致性的优先级是非常高的**——用户删掉一篇敏感文档，结果 5 秒后检索还能出来，这是很严重的合规问题。

## Pgvector 把这个问题变没了

Ragent 换到 pgvector 之后，上面那段代码变成了这样：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
@Transactional(rollbackFor = Exception.class) public void deleteDocument(String docId) { // 一切都在 PostgreSQL 里，同一个事务（省略了日志表的删除） documentMapper.deleteById(docId); chunkMapper.deleteByDocId(docId); jdbcTemplate.update( "DELETE FROM t_knowledge_vector WHERE metadata->>'doc_id' = ?", docId ); }
```

`t_knowledge_vector` 和 `t_knowledge_document`、`t_knowledge_chunk` 在同一个 PostgreSQL 实例里，共用一个连接、共用一个事务。任何一步失败，全部回滚；全部成功，一起提交。**没有跨库、没有分布式事务、没有对账脚本**。

这对一个知识库系统来说是质变级别的简化——你终于可以像写普通业务代码那样操作向量数据了。

Ragent 里 `t_knowledge_vector` 的定义长这样：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
CREATE EXTENSION IF NOT EXISTS vector; CREATE TABLE t_knowledge_vector ( id VARCHAR(64) PRIMARY KEY, content TEXT, metadata JSONB, embedding vector(1536) ); CREATE INDEX idx_kv_metadata ON t_knowledge_vector USING gin(metadata); CREATE INDEX idx_kv_embedding ON t_knowledge_vector USING hnsw (embedding vector_cosine_ops);
```

你会发现几件事：

- `embedding vector(1536)` 就是 pgvector 提供的向量列类型，本质上就是一个 PG 类型

- 向量索引用的还是 **HNSW**，pgvector 从 0.5 版本之后默认支持 HNSW，算法和 Milvus 是同一套

- 标量过滤是 PostgreSQL 原生的 `jsonb` + gin 索引，`metadata->>'doc_id' = 'xxx'` 就是一条普通 SQL

换句话说，pgvector 把向量检索变成了**一张带特殊列类型和特殊索引的 PostgreSQL 表**。你会写 SQL，就会用它。

## Pgvector 的几个甜头

除了事务一致性这张王牌，pgvector 在工程上还有几个实实在在的甜头。

### 1. 部署轻量到可以忽略

如果你的项目已经在用 PostgreSQL——Ragent 就是这样——你不需要再额外部署任何东西，只要在数据库里执行一句 `CREATE EXTENSION IF NOT EXISTS vector;`，完事。

没有 etcd，没有对象存储，没有 seccomp 配置，没有额外的监控和告警。一份 `docker-compose.yml` 搞定数据库 + 向量库，新人拉下代码 5 分钟就能把环境跑起来。

### 2. 检索就是一条 SQL

在 pgvector 里做一次向量检索 + 标量过滤，是这样的：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
SELECT id, content, metadata, 1 - (embedding <=> $1) AS similarity FROM t_knowledge_vector WHERE metadata->>'kb_id' = 'kb_001' AND metadata->>'category' = 'return_policy' ORDER BY embedding <=> $1 LIMIT 5;
```

`<=>` 是 pgvector 提供的余弦距离运算符（还有 `<->` 是 L2 距离，`<#>` 是负内积）。pgvector 的结构性优势在于：**标量过滤和向量检索被 PG 优化器统一调度在同一个查询计划里**——优化器自动决定是先走 HNSW 索引拿 topK 再过滤（post-filter），还是先按 metadata 缩小范围再做向量检索（pre-filter）。这种决策在 Milvus 里需要你自己通过参数和分区策略来调控，在 pgvector 里优化器帮你做了。

### 3. 运维和监控复用 PG 那一套

PostgreSQL 经过 30 多年的积累，运维生态成熟得让人放心：

- 备份恢复：`pg_dump` / `pg_basebackup` / WAL 归档，向量数据和业务数据一起备份

- 监控：`pg_stat_statements`、pgBadger、Prometheus exporter 一应俱全

- 高可用：流复制、Patroni、Citus 的方案都能直接套用

- 运维人员：会 PostgreSQL DBA 的人，比会 Milvus 的人多得多

对一个需要长期维护的项目来说，这套成熟生态的价值是指数级的。

## Pgvector 也有它的短板

当然，pgvector 不是银弹。它不如 Milvus 的地方也得老老实实讲清楚，不然就是在忽悠人了。

| 维度 | pgvector | Milvus |
| --- | --- | --- |
| 支持的索引类型 | HNSW、IVFFlat | HNSW、IVF_FLAT、IVF_SQ8、IVF_PQ、DISKANN、SCANN…… |
| 最大向量维度 | 2000（HNSW 索引下，0.7.x 版本）、16000（无索引） | 32768 |
| 大数据量检索性能 | 百万级良好，千万级开始吃力 | 百万到数十亿级都能撑 |
| 水平扩展能力 | 依赖 Citus 等外部方案 | 原生分布式架构 |
| 针对向量的专项优化 | 作为 PG 扩展，受限于 PG 查询引擎 | 专用引擎，GPU 加速、异步刷盘、列存 |
| 混合检索（稠密+稀疏） | 需要自己拼装 | 原生支持 BM25 + 向量 RRF 融合 |
| 内存占用 | HNSW 索引利用 OS 页缓存按需加载，不要求全量常驻内存 | HNSW 索引默认要求全量 mmap 或 load 到内存 |

几个点具体展开一下：

- **大数据量下的性能差距**：Milvus 的查询引擎是为高并发向量检索从零设计的——批处理、SIMD、异步 I/O、GPU 支持都有，亿级向量下依然能把 p99 压在 100ms 以内。pgvector 跑在 PG 的执行器里，百万级没问题，到了三五千万量级，QPS 和延迟都会明显退化。

- **索引算法的丰富度**：pgvector 目前主力就是 HNSW 和 IVFFlat 两种。Milvus 的 DISKANN、IVF_PQ 这些针对超大规模、内存受限场景的算法，pgvector 暂时没有对标物。

- **分布式能力**：PG 本身的水平扩展依赖 Citus 这类方案，而 pgvector + Citus 的组合成熟度远不如 Milvus 原生的 cluster 模式。十亿级向量场景下，Milvus 几乎没有对手。

- **维度限制**：pgvector 0.7.x 版本下 HNSW 索引最大支持 2000 维（0.8.0+ 版本有所提升，具体取决于编译参数），你用 Qwen3-Embedding-8B 的 4096 维默认输出就直接超标了，必须降维到 2000 维以内或者不建 HNSW 索引。Ragent 选用 1536 维的 Embedding 模型，也是在做这个权衡。

> 这几条短板对应的都是数据量很大或极致性能场景。对大多数企业 RAG 项目来说，这些短板其实碰不到——你的知识库真的会超过一千万 chunk 吗？

## Ragent 为什么最终选 pgvector

把上面的权衡串起来，Ragent 的选型理由其实很清楚：

- **数据量评估**：企业知识库场景，chunk 数量通常在几万到几百万之间，pgvector 的 HNSW 性能完全够用

- **事务一致性优先**：企业知识库对文档删除、更新的一致性有强要求，跨库方案的复杂度收益不划算

- **部署门槛**：希望读者拉下代码就能跑起来，不要为向量库折腾半天环境。企业里也能少一个中间件维护

- **维护成本**：Ragent 后续还要持续迭代，少一个组件就少一份维护压力

- **Embedding 维度适配**：选用 1536 维的 Embedding 模型，绝大部分向量场景够用了

这几条加起来，pgvector 就是当下最合适的选择。

> 需要额外说明的是：Ragent 代码里 **Milvus 的实现并没有被删掉**。`MilvusVectorStoreService`、`MilvusRetrieverService`、`MilvusVectorStoreAdmin` 这几个类依然保留在仓库里，作为另一条可选的向量存储实现。项目通过配置开关来切换底层向量库——这也是工程上的一个小讲究，不要因为选了 A 就把 B 的代码全删掉，给未来留个后门。

## 一个简单的决策建议

讲了这么多，最后给一个简单的决策建议，方便你自己项目做选型的时候参考：

- **向量数据量 < 100 万，且项目已经在用 PostgreSQL**：闭眼选 pgvector

- **向量数据量 100 万~500 万，对成本敏感**：pgvector 依然够用，升级 PG 机器规格即可

- **向量数据量 500 万~3000 万，对检索延迟有严格要求**：开始认真对比 pgvector 和 Milvus，看 QPS 和 p99

- **向量数据量 > 3000 万，或者要做 GPU 加速 / 亿级分布式**：换 Milvus，不犹豫

- **有强事务一致性要求的知识库系统**：优先 pgvector

- **纯向量检索服务、数据和业务系统可以独立**：Milvus 的专业能力值得投入

迁移成本其实也没你想的那么高——只要你项目里的向量存取接口做了抽象层（像 Ragent 那样有 `VectorStoreService` 接口），换底层实现就是换一个 Bean 的事。

## 一句话收尾

技术选型从来没有标准答案。RAG 系列里我推 Milvus，是因为它能把向量检索的完整能力讲明白；Ragent 里我用 pgvector，是因为在企业知识库这个具体场景下，它的综合成本最低、复杂度最低、一致性最强。

选 A 不否定 B，用 B 不代表放弃 A。**工程上最值钱的是对场景的判断力，不是对某个技术栈的站队**。

> Source: https://t.zsxq.com/fpIYO
> Resolved: https://articles.zsxq.com/id_jh3c814w1ixn.html
