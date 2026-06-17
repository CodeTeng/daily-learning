# 《AI大模型Ragent项目》——PostgreSQL数据库初始化

完成 PostgreSQL 的安装与配置后，接下来需要对数据库进行初始化，包括创建数据库、导入表结构以及初始化基础数据。这一步骤是 RagentAI  项目正常运行的前提，确保了应用启动时能够正确访问和操作数据。

注意：本文档基于 2026-03-22 版本的数据库脚本编写。随着项目功能的迭代，数据库表结构和初始数据可能会持续演进。如项目运行 SQL 报错，请访问项目仓库的 `/resources/database` 目录，或关注版本更新说明。

## SQL 脚本文件说明

在项目的 `/resources/database` 目录下，包含以下两个核心 SQL 脚本文件：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
~/workspace/nageoffer/ragent/resources/database git:[main] ls init_data_pg.sql schema_pg.sql
```

文件说明：

文件名

功能描述

执行顺序

schema_pg.sql

包含数据库创建语句、表结构定义、索引配置以及 pgvector 扩展

1

init_data_pg.sql

包含业务初始化数据，如系统配置、角色权限等

2

⚠️ 重要提示：  必须按照上述顺序依次执行 SQL 脚本，否则可能因表不存在而导致数据插入失败。

## 初始化方式

考虑到不同开发者使用的 PostgreSQL 客户端工具各不相同，本章节将提供两种通用的数据初始化方式，你可以根据实际情况选择其中任意一种：

- 1.
图形化客户端工具 （如 TablePlus、Navicat、pgAdmin 等）

- 2.
IDE内置工具 （如 IntelliJ IDEA、DataGrip 等）

### 方式一：图形化客户端工具（推荐）

图形化工具提供了更直观的操作界面，适合不熟悉命令行的开发者。以下以 TablePlus  为例进行演示，其他工具（如 Navicat、pgAdmin）的操作流程类似。

由于我平时习惯使用 TablePlus ，因此本次演示将基于该工具进行操作。如果你使用的是 Navicat ，可以参考下方对应章节。

步骤1：连接到PostgreSQL数据库

打开 TablePlus，点击 新建连接 ，选择 PostgreSQL ，填入连接信息：

- Host ：127.0.0.1

- Port ：5432

- User ：postgres

- Password ：postgres

- Database ：ragent

点击 连接  按钮，成功连接到 PostgreSQL 服务器。

因为创建 postgres 数据库时，已经初始化了 Ragent，所以不需要再创建数据库。直接选择 `ragent` 数据库进入就好。

步骤2：导入建表脚本

在 TablePlus 界面中，依次点击顶部菜单 文件→导入→FromSQLdump... ，选择 `schema_pg.sql` 文件，点击 执行  按钮。或者按照下图形式：

![无法获取该图片](https://oss.open8gu.com/image-20260303145515267.png)

执行成功后，可在左侧数据库列表中看到 `ragent` 数据库及其下的所有表结构，包括向量表 `t_knowledge_vector`。

步骤3：导入初始化数据

重复上述步骤，导入 `init_data_pg.sql` 文件。执行成功后，可打开 `t_user` 表查看是否有初始数据。

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
select * from t_user;
```

### 方式二：其他常见工具

Navicat：

- 1.
连接到 PostgreSQL 进入 `ragent` 数据库

- 2.
右键点击连接，选择 运行SQL文件

- 3.
依次选择 `schema_pg.sql` 和 `init_data.sql` 执行

DBeaver：

- 1.
连接到 PostgreSQL 数据库

- 2.
右键点击连接，选择 SQL编辑器→打开SQL脚本

- 3.
依次选择 `schema_pg.sql` 和 `init_data.sql`，按 `Ctrl + Enter` 执行

## 检查项目配置文件

确认项目配置文件 `application.yaml` 中的数据库连接信息与实际环境一致：

textjavascripttypescriptcsshtmlbashjsonmarkdownpythonjavaccpprubygorustphpsqlyaml Copy

```
spring: datasource: driver-class-name: org.postgresql.Driver username: postgres password: postgres url: jdbc:postgresql://127.0.0.1:5432/ragent?client_encoding=UTF8
```

⚠️ 注意事项：  如果你在安装 PostgreSQL 时使用了不同的端口或密码，请务必在配置文件中进行相应调整。

## 版本更新说明

随着 RagentAI  项目的持续迭代，数据库表结构和初始数据可能会发生变化。为了保证系统的稳定性和功能的完整性，建议定期关注以下内容：

- 1.
SQL脚本版本 ：每次项目版本更新时，请检查 `/resources/database` 目录下的 SQL 脚本是否有更新。

- 2.
增量更新脚本 ：对于已有环境，我们会提供增量更新脚本（如 `upgrade_v1.0_to_v1.1.sql`），避免重新初始化导致数据丢失。

- 3.
变更日志 ：重大数据库变更会在项目的 CHANGELOG.md 文件中说明，包括新增表、字段变更、索引优化等。

提示：如果你是首次部署，只需执行最新版本的 `schema_pg.sql` 和 `init_data_pg.sql` 即可。如果是从旧版本升级，请查阅版本间的增量更新脚本。

> Source: https://t.zsxq.com/Ynima
> Resolved: https://articles.zsxq.com/id_k8wb8mdzwt12.html
