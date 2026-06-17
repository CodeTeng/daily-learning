# 《AI大模型Ragent项目》——Docker本地中间件部署

在开始正式使用 Ragent AI 之前，我们需要先准备好相关的中间件环境。本章节将详细介绍 PostgreSQL、Redis、RocketMQ 与 RustFS 的安装及配置流程，并附上客户端工具的使用指南，帮助大家快速搭建起完整的本地开发环境。

注意：本文件仅包含 2026-03-02 版本的中间件安装配置，旨在满足项目最小化启动需求。后续将持续集成 Nacos、Prometheus 及 Grafana 等组件，具体更新以马哥移除本提示为准。

Ragent AI 项目使用 Docker 安装中间件，如果电脑尚未安装 Docker 相关软件，请先完成安装。

## 公共云中间件

考虑到部分同学本地机器性能有限，以及部分中间件安装配置较为复杂，我们提供了公共云中间件的使用方式，方便大家快速上手。

如果选择使用公共云中间件，则无需在本地安装下方提到的 `Redis`、`RocketMQ`。在后续的项目启动环节中，会详细说明如何接入并使用云中间件。

后续还会逐步接入更多中间件（如 Nacos 等）。相关更新会在星球通知，届时参考本说明及项目启动文档即可完成配置。

## 中间件安装

### 1. PostgreSQL

Ragent AI 使用 PostgreSQL 作为关系数据库，并集成 pgvector 扩展支持向量存储。通过以下 Docker 命令启动 PostgreSQL 实例：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
docker run -d \ --name postgres \ -e POSTGRES_DB=ragent \ -e POSTGRES_USER=postgres \ -e POSTGRES_PASSWORD=postgres \ -p 5432:5432 \ -v pgdata:/var/lib/postgresql/data \ pgvector/pgvector:pg16
```

如果本地已安装 PostgreSQL 并可正常使用，跳过本小节即可。

Docker 启动配置参数说明：

- `-d`：以后台的方式运行。

- `--name postgres`：指定容器的名称为 postgres。

- `-e POSTGRES_DB=ragent`：创建名为 ragent 的数据库。

- `-e POSTGRES_USER=postgres`：设置数据库用户名为 postgres。

- `-e POSTGRES_PASSWORD=postgres`：设置数据库密码为 postgres。

- `-p 5432:5432`：将容器的 5432 端口挂载到宿主机的 5432 端口上。

- `-v pgdata:/var/lib/postgresql/data`：持久化数据到 Docker 卷。

⚠️ 注意事项，创建好本地 PostgreSQL 后，记得查看修改对应项目 bootstrap 模块下的 application.yaml 数据库配置文件，重点是关注 url、username 以及 password 字段。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
spring: datasource: driver-class-name: org.postgresql.Driver type: com.zaxxer.hikari.HikariDataSource username: postgres password: postgres url: jdbc:postgresql://127.0.0.1:5432/ragent?client_encoding=UTF8 hikari: connection-timeout: 5000 idle-timeout: 600000 max-lifetime: 1800000 maximum-pool-size: 10 minimum-idle: 5 pool-name: RagentHikariPool
```

### 2. Redis

通过简易方式安装 Redis，主打的就是“有问题铲了重装”：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
docker run \ -p 6379:6379 \ --name redis \ -d redis \ redis-server \ --requirepass "123456"
```

创建命令里默认密码为 123456，可根据需要修改。如果此处修改，项目的配置文件中也需要检查下。

### 3. RocketMQ

常规的 RocketMQ 部署本地是有一定复杂性的，为了节省大家的时间成本，特地把多个 Docker 容器合并成了一个组合容器。相关的启动脚本我放在项目的 `resources/docker` 目录下。

- Windows 和 Mac 英特尔芯片：rocketmq-stack-5.2.0.compose.yaml

- Mac AMD 芯片：rocketmq-stack-amd-5.2.0.compose.yaml

![无法获取该图片](https://oss.open8gu.com/image-20260328224408553.png)

实在无力吐槽，RocketMQ 想要最短平快安装太难了，尝试了大半天，最终结合 AI 试出来了。无视 Docker 版本，无视网络，安装必成功！

### 4. RustFS

在 Ragent AI 的整体架构设计中，引入了 RustFS 作为底层存储引擎。RustFS 具备高性能、低资源占用、强一致性以及良好的可扩展性等特点。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
docker run -d \ --name rustfs \ -p 9000:9000 \ -p 9001:9001 \ -v rustfs-data:/data \ -e RUSTFS_ACCESS_KEY=rustfsadmin \ -e RUSTFS_SECRET_KEY=rustfsadmin \ -e RUSTFS_CONSOLE_ENABLE=true \ rustfs/rustfs:1.0.0-alpha.72 \ --address :9000 \ --console-enable \ --access-key rustfsadmin \ --secret-key rustfsadmin \ /data
```

继 MinIO 闭源后，RustFS 作为“接力棒”展现了活跃的社区和可持续版本迭代能力。

运行完成后，可通过以下命令查看正在运行的 Docker 容器：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
docker ps
```

正常情况下，会看到包括但不限于以下容器实例正在运行：

- `rustfs`

- `redis`

- `postgres`

如果上述容器均已启动，说明当前阶段部署成功。在接下来的章节中，我们将登录各中间件后台管理页面，对功能进行验证。

## 客户端工具

### 1. Redis Desktop

Redis 客户端连接工具使用 [AnotherRedisDesktopManager](https://github.com/qishibo/AnotherRedisDesktopManager/releases)，大家点击链接可跳转 GitHub 下载最新版本。

![无法获取该图片](https://oss.open8gu.com/image-20240810145916449.png)

下载安装成功后，点击左上角新建连接即可。如果按照咱们上面 Redis 安装的教程，密码填入 123456，用户名默认可忽略。

![无法获取该图片](https://oss.open8gu.com/image-20260302182233329.png)

注意，大家使用 Redis 云公共组件时，默认打开链接考虑内存问题，是不会加载全部 Key 的，所以大家如果想查询，可以按照 Key 全称搜索。

### 2. RocketMQ DashBoard

如果本地安装的，访问 `http://127.0.0.1:8082` 即可进入 RocketMQ 控制台，默认是看不到消息的。只有在后面业务功能操作后，Topic 才会被创建。

![无法获取该图片](https://oss.open8gu.com/image-20260329115152218.png)

最新版本的 RocketMQ DashBoard 实在无力吐槽，中英文切换，你选了中文后，刷新页面后，默认还是英文。

然后还搞了个配色，选了死亡芭比粉后，我整个眉头拧成了川字！来吧，一起见识下。

![无法获取该图片](https://oss.open8gu.com/image-20260329115546800.png)

插个眼，后面有时间了得去好好重构下 UI，简直没法看。重构后，推送到 nageoffer 的官方 Docker 仓库。因为 RocketMQ 官方现在对于这个的仓库，基本上属于爱答不理程度了。

如果使用公共云中间件，访问 [http://common-rocketmq-dev.magestack.cn:8088](http://common-rocketmq-dev.magestack.cn:8088/#/) 即可查看。

### 3. RustFS

RustFS 提供了 Web 控制台，用于管理对象存储、创建存储桶（Bucket）、上传下载文件以及配置访问策略。登录控制台后，可在 Buckets 页面创建存储桶，设置访问权限和生命周期策略，并直接进行文件的上传、下载和管理操作。

登录信息

项目

值

控制台地址

[http://localhost:9001](http://localhost:9001/)

API 地址（代码中使用）

[http://localhost:9000](http://localhost:9000/)

账号

rustfsadmin

密钥

rustfsadmin

打开控制台地址后，输入账号和密钥，点击 登录 按钮即可登录。

![无法获取该图片](https://oss.open8gu.com/image-20260302200708584.png)

登录成功后进入默认的 Dashboard 页面，可尝试创建 Bucket 并上传文件以验证服务是否正常运行。

![无法获取该图片](https://oss.open8gu.com/image-20260322233153654.png)

## 文末小结

至此，本地中间件环境及客户端工具已完成安装与基本配置。

大家可以通过各自的 Web 控制台和客户端工具验证服务是否正常运行，并进行初步操作。后续章节将带你启动 Ragent 项目，并深入了解 Ragent AI 的核心功能、向量检索策略以及项目实战演示。

> Source: https://t.zsxq.com/QnBXt
> Resolved: https://articles.zsxq.com/id_b0q0xwojkirm.html
