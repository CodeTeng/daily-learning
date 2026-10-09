# COS 文件下载脚本说明

## 功能概述

本脚本用于从腾讯云 COS 存储桶 `data-backup-1250000000` 中下载 `backups/db-2026-07-25.tar.gz` 文件到本地 `./downloads/` 目录。

## 核心逻辑

1. **客户端初始化**：从 `.env` 文件或环境变量中读取 `TENCENT_SECRET_ID`、`TENCENT_SECRET_KEY`、`TENCENT_COS_REGION` 等配置，初始化 COS 客户端（使用 HTTPS、30 秒超时、连接池等参数）。

2. **文件大小检查**：通过 `head_object` API 查询远程文件元信息，获取 `Content-Length` 判断文件大小，避免盲目下载超大文件。

3. **智能下载策略**：
   - 文件小于等于 1GB：全量下载，保存原始文件名。
   - 文件大于 1GB：只下载前 512MB（通过 `Range: bytes=0-536870911` 范围下载），文件名添加 `.partial` 标识，用于快速校验。

4. **错误处理**：捕获两类异常 —— `CosServiceError`（服务端错误，含错误码、状态码、Request ID）和 `CosClientError`（客户端网络/超时错误），均输出详细错误信息后退出。

5. **结果校验**：下载完成后对比本地文件大小与预期大小，确认下载完整性。

## 使用方式

```bash
# 1. 确保已安装依赖
uv add cos-python-sdk-v5 python-dotenv

# 2. 配置密钥（.env 文件或环境变量）
# TENCENT_SECRET_ID=...
# TENCENT_SECRET_KEY=...
# TENCENT_COS_REGION=ap-beijing  # 可选

# 3. 运行脚本
python download_file.py
```
