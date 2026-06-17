# 《AI大模型Ragent项目》——项目启动指南

完成中间件环境搭建和数据库初始化后，就可以正式启动 RagentAI   项目了。本章节将详细介绍后端服务和前端应用的启动流程，包括 Java 后端、MCP Server 服务以及 Vue 前端的完整启动步骤。为了方便快速体验，我们还提供了基于 Nginx 的一键部署方案。

注意：随着项目功能的迭代，启动方式和配置项可能会发生变化。如遇到启动问题，请优先查看前两章是否引入了新的中间件和库表修改。

## 启动顺序说明

为确保 RagentAI   项目正常运行，建议按照以下顺序启动各个服务：

- 1.
中间件服务  ：PostgresSQL、Redis、RocketMQ、RustFS（参考上一章节）

- 2.
后端服务  ：启动 `RagentApplication` 主程序

- 3.
MCPServer  ：启动 `MCPServerApplication`（可选）

- 4.
前端应用  ：通过 Nginx 或 Node.js 启动前端界面

⚠️ 重要提示：   后端服务依赖中间件环境，必须先确保所有中间件正常运行后再启动后端。前端应用依赖后端服务提供的 API 接口，因此需要在后端启动成功后再启动前端。

## 配置 AI 平台密钥

Ragent AI 项目依赖外部 AI 平台提供大模型推理、Embedding 及 Rerank 能力。在启动后端服务之前，你需要分别在 阿里云百炼   和 硅基流动（SiliconFlow）   平台注册账号并获取 API Key，然后将其配置到项目中。

这两个平台均提供免费额度，注册后即可快速体验，无需付费。当然也可能过了活动期，往里面充 1 块钱即可。

### 1. 获取阿里云百炼 API Key

阿里云百炼（DashScope）提供通义系列大模型的 API 服务，Ragent AI 使用它进行对话补全和文本 Rerank。

步骤1：注册并登录

访问阿里云百炼控制台：[https://bailian.console.aliyun.com](https://bailian.console.aliyun.com/)

如果没有阿里云账号，按照页面提示完成注册（支持支付宝快捷注册）。已有账号则直接登录。

步骤2：创建并复制APIKey

登录后，点击右上角头像，选择 「API-KEY」   进入密钥管理页面，也可直接访问：[https://bailian.console.aliyun.com/cn-beijing/?tab=model#/api-key](https://bailian.console.aliyun.com/cn-beijing/?tab=model#/api-key)

点击 「创建新的API-KEY」  ，选择默认的业务空间，创建成功后点击 「复制」   按钮保存 API Key。

### 2. 获取硅基流动 API Key

硅基流动（SiliconFlow）提供多种开源大模型的 API 服务，Ragent AI 使用它进行对话补全和文本 Embedding。

步骤1：注册并登录

访问硅基流动官网：[https://siliconflow.cn](https://siliconflow.cn/)

点击右上角 「登录」  ，支持手机号、GitHub、Google 等多种方式注册登录。

步骤2：创建并复制APIKey

登录后，进入 「API密钥」   管理页面，也可直接访问：[https://cloud.siliconflow.cn/me/account/ak](https://cloud.siliconflow.cn/me/account/ak)

点击 「创建新API密钥」  ，输入密钥名称（如 `ragent`），创建成功后点击 「复制」   按钮保存 API Key。

### 3. 配置 API Key 到项目

获取两个平台的 API Key 后，你需要将它们配置到项目中。推荐通过 环境变量   的方式注入，避免将密钥硬编码在配置文件中。

如果仅用于本地开发测试，可以直接将 API Key 写入 `application.yaml` 配置文件中：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
ai: providers: bailian: api-key: sk-xxxxxxxxxxxxx # 替换为你的阿里云百炼 API Key siliconflow: api-key: sk-xxxxxxxxxxxxx # 替换为你的硅基流动 API Key
```

⚠️ 安全提示：   直接将密钥写入配置文件存在泄露风险，请勿将包含真实密钥的配置文件提交到 Git 仓库。如果需要提交 Git 仓库，可以选择通过环境变量注入方式。

## 配置 VM 参数

接下来我会以牛券的项目截图讲解 VM 参数配置，主要是流程一样，马哥就懒得再重复截图说明了。大家体谅一下下。

在 Idea 中打开关于应用程序启动配置页面，配置相关的 VM 参数。

![无法获取该图片](https://oss.open8gu.com/image-20240810143120510.png)

如果大家刚拉下来项目，有可能是没有服务列表的，大家将所有服务的应用程序类启动下即可。下述应用最好都设置上相同的 VM 参数，毕竟加上没坏处，万一以后用上了，省得大家再折腾了。

- RagentApplication

- MCPServerApplication

报错也无所谓，只要能出现配置类执行下述流程就好。

![无法获取该图片](https://oss.open8gu.com/image-20240810150713715.png)

打开编辑应用配置程序之后，点击 `Modify options` 添加 `Add VM options` 选项，将 VM 参数选项打开即可。

![无法获取该图片](https://oss.open8gu.com/image-20240810144114866.png)

添加以下 VM 参数到新增加的 `VM options` 输入框中，点击 OK 即可完成启动。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
-Dunique-name=-dingma -Dframework.cache.redis.prefix=dingma: -Dspring.data.redis.host=common-redis-dev.magestack.cn -Dspring.data.redis.password=Sm9sVXBOYJjI030b5tz0trjpzvZzRhtZmEbv0uOImcD1wEDOPfeaqNU4PxHob/Wp -Dspring.data.redis.port=19389 -Drocketmq.name-server=common-rocketmq-dev.magestack.cn:9876 -Dspring.cloud.nacos.discovery.server-addr=common-nacos-dev.magestack.cn:8848
```

`unique-name` 参数指的是什么呢？我们都使用同一个 RocketMQ，如果不使用 `unique-name` 区分，大家的 RocketMQ 消费者和消费者组是一致的，那么就会出现消息调用错乱的情况。各自改个不会和别人冲突的，比如自己名称英文加数字之类的。

除了 RocketMQ 用到了这个参数，Redis 中同样也使用到了这个参数，同理。

`framework.cache.redis.prefix` 参数是给大家使用 Redis 操作 Kye 时添加统一前缀，避免大家使用同一个 Redis 被互相影响。

![无法获取该图片](https://oss.open8gu.com/image-20240810155649669.png)

## 启动后端项目

Ragent AI 项目提供了两个后端启动类，分别承担不同的职责：

启动类

功能描述

是否必需

默认端口

RagentApplication

主服务启动类，提供核心 API 接口和业务逻辑

✅ 必需

9090

MCPServerApplication

MCP Server 端启动类，提供 MCP 协议服务

❌ 可选

9091

### 1. 启动主服务（必需）

在 IDE 中找到 `RagentApplication` 类，右键点击运行 `Run 'RagentApplication'`。

启动成功后，控制台会输出类似以下日志：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
. ____ _ __ _ _ /\\ / ___'_ __ _ _(_)_ __ __ _ \ \ \ \ ( ( )\___ | '_ | '_| | '_ \/ _` | \ \ \ \ \\/ ___)| |_)| | | | | || (_| | ) ) ) ) ' |____| .__|_| |_|_| |_\__, | / / / / =========|_|==============|___/=/_/_/_/ :: Spring Boot :: (v3.5.7) // ...... 省略 2026-03-03T20:04:37.044+08:00 INFO 59339 --- [ragent-service] [ main] c.nageoffer.ai.ragent.RagentApplication : Started RagentApplication in 4.393 seconds (process running for 5.001)
```

看到 `Started RagentApplication` 字样，表示后端主服务启动成功。

### 2. 启动 MCP Server（可选）

MCP Server 是 Model Context Protocol 的服务端实现，用于扩展 AI 模型的能力边界。如果你暂时不需要使用 MCP 相关功能，可以跳过此步骤。

在 IDE 中找到 `MCPServerApplication` 类，右键点击运行 `Run 'MCPServerApplication'`。

如果不启动MCPServer：

主服务启动时会尝试连接 MCP Server，如果连接失败，控制台会输出以下 Error 级别日志，这是正常现象，可以忽略：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
2026-03-03T20:04:36.551+08:00 ERROR 59339 --- [ragent-service] [main] c.n.a.r.r.core.mcp.client.HttpMCPClient : MCP 请求异常，method=initialize, url=http://localhost:8081/mcp, 原因=Failed to connect to localhost/[0:0:0:0:0:0:0:1]:8081 2026-03-03T20:04:36.551+08:00 ERROR 59339 --- [ragent-service] [main] c.n.a.r.r.core.mcp.client.HttpMCPClient : MCP 初始化失败，跳过 initialized 通知发送 2026-03-03T20:04:36.551+08:00 ERROR 59339 --- [ragent-service] [main] n.a.r.r.c.m.c.MCPClientAutoConfiguration : MCP Server [default] 初始化失败，跳过工具注册
```

这些日志不会影响 Ragent AI 的核心功能，系统会自动降级运行。待后续需要使用 MCP 功能时，再单独启动 MCP Server 即可。

## 启动前端项目

Ragent AI 前端基于 Vue3   构建，提供了两种启动方式：

- 1.
Nginx一键部署  （推荐，适合快速体验）

- 2.
Node.js开发环境  （适合二次开发和调试）

你可以根据实际需求选择其中一种方式启动前端应用。

### 方式一：Nginx 一键部署（推荐）

如果你是 Windows   用户，或希望快速体验系统功能而不进行前端代码修改，推荐使用 Nginx 方式部署。该方式无需安装 Node.js 环境，下载即用。

步骤1：下载前端压缩包

通过以下网盘链接下载预编译的前端静态资源：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
通过网盘分享的文件：nageoffer-nginx-2.0.2.zip 链接: https://pan.baidu.com/s/1aCHXhnGaBFYBE4HDmBFDMw?pwd=6688 提取码: 6688
```

步骤2：解压并启动Nginx

下载完成后，解压 `nageoffer-nginx-2.0.0.zip` 文件到任意目录。进入解压后的文件夹，双击 `nginx.exe` 图标启动 Nginx 服务。

![无法获取该图片](https://oss.open8gu.com/image-20250628211040288.png)

注意：Windows 系统可能会弹出防火墙提示，请选择“允许访问”。

步骤3：验证Nginx启动

在浏览器中访问：[http://localhost](http://localhost/)

如果显示 Nginx 默认页面，表示 Nginx 已成功启动。

![无法获取该图片](https://oss.open8gu.com/image-20250628211106129.png)

步骤4：访问RagentAI前端

在浏览器中访问：[http://localhost:5177](http://localhost:5177/)

如果跳转到 Ragent AI 登录页面，则表示前端部署成功。

停止Nginx：

如需停止 Nginx 服务，在解压目录下打开命令行，执行：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
nginx.exe -s stop
```

或直接在任务管理器中结束 `nginx.exe` 进程。

### 方式二：Node.js 开发环境

如果你需要修改前端代码或进行二次开发，建议使用 Node.js 方式启动。该方式支持热重载，代码修改后会自动刷新页面。

#### 2.1 环境要求

Ragent AI 前端项目要求 Node.js20.15.0   版本。使用其他版本可能会遇到依赖包不兼容、编译失败等问题。

#### 2.2 全新安装 Node.js

如果你的电脑中尚未安装 Node.js，请按照以下步骤进行安装：

步骤1：下载安装包

访问 Node.js 官方下载页面：[https://nodejs.org/download/release/v20.15.0](https://nodejs.org/download/release/v20.15.0)

根据你的操作系统选择对应的安装包：

- Windows用户  ：下载 `node-v20.15.0-win-x64.zip`（64 位）

- Mac用户  ：下载 `node-v20.15.0.pkg`

步骤2：安装Node.js

- Windows  ：解压后将 `node.exe` 所在目录添加到系统环境变量 `PATH` 中

- Mac  ：双击 `.pkg` 文件，按照向导完成安装

步骤3：验证安装

打开终端（命令行），执行以下命令：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
node -v
```

如果输出 `v20.15.0`，表示安装成功。

![无法获取该图片](https://oss.open8gu.com/image-20260303180843097.png)

#### 2.3 已有 Node.js 环境

如果你的电脑中已安装 Node.js，但版本不是 20.15.0，可通过以下两种方式处理：

选项1：卸载重装  （简单粗暴）

卸载当前 Node.js 版本，按照上述步骤重新安装 20.15.0 版本。

选项2：使用多版本管理工具  （推荐）

通过 `n`（Mac/Linux）或 `nvm-windows`（Windows）管理多个 Node.js 版本，实现版本切换。

##### Mac/Linux 用户

步骤1：安装n工具

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
npm install -g n
```

步骤2：验证安装

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
n -V
```

注意，这里的 `-V` 是大写字母。如果输出版本号，表示安装成功。

![无法获取该图片](https://oss.open8gu.com/image-20260303183007223.png)

步骤3：安装并切换到20.15.0

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
# 下载 20.15.0 版本 n 20.15.0 # 切换到 20.15.0 版本 sudo n 20.15.0 # 验证当前版本 node -v
```

##### Windows 用户

步骤1：安装nvm-windows

访问 [nvm-windows 官方仓库](https://github.com/coreybutler/nvm-windows/releases)，下载最新版本的 `nvm-setup.exe`，按照向导完成安装。

步骤2：安装并切换版本

打开命令行（以管理员身份运行），执行以下命令：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
# 安装 20.15.0 版本 nvm install 20.15.0 # 切换到 20.15.0 版本 nvm use 20.15.0 # 验证当前版本 node -v
```

更多详细教程可参考：[Windows 电脑切换 Node.js 多版本参考链接](https://blog.csdn.net/qq_38405436/article/details/132279098)

#### 2.4 启动前端项目

完成 Node.js 环境配置后，进入 Ragent AI 项目的 `/frontend` 目录，依次执行以下命令：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
# 安装项目依赖（首次启动或依赖更新后执行） npm install # 启动开发服务器 npm run dev
```

提示：如果 `npm install` 速度较慢，可以切换到国内镜像源：`npm config set registry https://registry.npmmirror.com`

启动成功后，控制台会输出类似以下信息：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
VITE v5.0.0 ready in 1234 ms ➜ Local: http://localhost:5173/ ➜ Network: use --host to expose ➜ press h + enter to show help
```

![无法获取该图片](https://oss.open8gu.com/image-20260303181504938.png)

在浏览器中访问：[http://localhost:5173](http://localhost:5173/)

如果看到 Ragent AI 登录页面，表示前端启动成功。

## 登录与验证

前端启动成功后，访问登录页面：[http://localhost:5173](http://localhost:5173/) 或 [http://localhost:5177](http://localhost:5177/)（Nginx 方式）

![无法获取该图片](https://oss.open8gu.com/image-20260303181638998.png)

使用以下默认账号登录：

- 用户名  ：admin

- 密码  ：admin

登录成功后，会进入 Ragent AI 主界面，至此项目启动流程全部完成，可以开始探索系统功能。

![无法获取该图片](https://oss.open8gu.com/iShot_2026-02-04_22.08.50.png)

## 常见问题排查

### 问题 1：后端启动失败，提示数据库连接异常

错误信息：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
Communications link failure. The last packet sent successfully to the server was 0 milliseconds ago.
```

原因：   PostgresSQL 服务未启动，或配置文件中的数据库连接信息不正确。

解决方案：

- 1.
确认 PostgresSQL 服务已启动：`docker ps | grep postgres`

- 2.
检查 `application.yaml` 中的数据库配置（地址、端口、用户名、密码）

- 3.
尝试使用客户端工具连接 PostgresSQL，验证连接信息是否正确

### 问题 2：前端页面空白或显示异常

原因：   后端服务未启动，或前端请求的 API 地址不正确。

解决方案：

- 1.
确认后端服务已启动并正常运行

- 2.
打开浏览器开发者工具（F12），查看 Console 和 Network 选项卡中的错误信息

- 3.
检查前端配置文件中的 API 地址是否指向正确的后端服务

### 问题 3：npm install 报错或速度过慢

原因：   网络问题或 npm 源速度慢。

解决方案：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
# 切换到国内镜像源 npm config set registry https://registry.npmmirror.com # 清除缓存后重新安装 npm cache clean --force npm install
```

### 问题 4：Node.js 版本切换后仍然显示旧版本

原因：   环境变量未生效，或存在多个 Node.js 安装路径。

解决方案：

- 1.
关闭并重新打开终端

- 2.
检查系统环境变量 `PATH` 中是否存在多个 Node.js 路径

- 3.
使用 `which node`（Mac/Linux）或 `where node`（Windows）确认当前生效的 Node.js 路径

### 问题 5：MCP Server 启动失败

原因：   端口被占用，或依赖服务未启动。

解决方案：

- 1.
检查 9091 端口是否被占用：`lsof -i:9091`（Mac/Linux）或 `netstat -ano | findstr 9091`（Windows）

- 2.
确认所有中间件服务（MySQL、Redis、Milvus 等）已正常启动

- 3.
查看完整的错误日志，根据具体错误信息进行排查

## 版本更新说明

随着 RagentAI   项目的持续迭代，启动方式和配置项可能会发生变化。建议定期关注以下内容：

- 1.
启动类变更  ：新版本可能会新增或移除启动类，请以最新代码为准

- 2.
端口调整  ：如果默认端口发生变化，会在版本更新说明中注明

- 3.
依赖版本升级  ：Node.js、数据库驱动等依赖版本可能会升级，请及时更新本地环境

- 4.
配置文件变更  ：新增的配置项会在 `application.yaml` 示例文件中提供默认值

提示：建议在每次更新代码后，查阅项目根目录下的 `CHANGELOG.md` 文件，了解最新的变更内容。

## 文末小结

至此，RagentAI   项目的启动流程已全部完成。

本章节详细介绍了后端服务和前端应用的多种启动方式，包括基于 Nginx 的一键部署方案和基于 Node.js 的开发环境配置。通过本章节的学习，你应该能够成功启动 Ragent AI 系统，并完成基本的登录验证。

> Source: https://t.zsxq.com/Hkh2u
> Resolved: https://articles.zsxq.com/id_0jiolkoxpc99.html
