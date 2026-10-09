# 代码说明

## 功能概述

`list_objects.py` 实现了一个遍历腾讯云 COS 存储桶文件的工具脚本。

### 做了什么

1. **初始化 COS 客户端**：从 `.env` 文件、`~/.cos/config` 或系统环境变量中读取 `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY`、`TENCENT_COS_REGION` 配置，创建 `CosS3Client` 实例。

2. **分页遍历文件**：使用 `list_objects` API，通过 `Marker` 参数实现分页循环。每次请求最多返回 1000 条记录，当 `IsTruncated` 为 `true` 时自动翻下一页，直到遍历完所有文件。

3. **打印文件信息**：对每个文件输出其 `Key`（对象路径名）和 `Size`（文件大小，单位 bytes），并在最后汇总文件总数和总大小。

4. **错误处理**：捕获 `CosServiceError`（服务端错误，如权限不足）和 `CosClientError`（客户端错误，如网络超时），打印详细错误信息后退出。

### 配置要求

运行前需配置以下环境变量（可通过项目根目录 `.env` 文件或系统环境变量设置）：

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `TENCENT_SECRET_ID` | 腾讯云 API 密钥 ID | `AKIDxxxxxxxx` |
| `TENCENT_SECRET_KEY` | 腾讯云 API 密钥 Key | `xxxxxxxx` |
| `TENCENT_COS_REGION` | 存储桶地域（可选，默认 ap-beijing） | `ap-guangzhou` |

### 依赖

- `cos-python-sdk-v5`
- `python-dotenv`

安装命令：`uv add cos-python-sdk-v5 python-dotenv`
