# COS 文件下载脚本说明

## 实现了什么

该脚本从腾讯云 COS 存储桶 `data-backup-1250000000` 下载对象 `backups/db-2026-07-25.tar.gz` 到本地 `./downloads/` 目录。

## 核心逻辑

1. **凭证管理**：通过环境变量 `COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_REGION` 初始化 COS 客户端，避免将密钥硬编码在代码中。
2. **文件大小检查**：使用 `head_object` 接口获取远端文件的 `Content-Length`，无需实际下载即可判断大小。
3. **条件下载**：
   - 若文件 **小于等于 1GB**，调用 `get_object` 全量下载。
   - 若文件 **超过 1GB**，通过设置 `Range: bytes=0-524287999` 请求头，仅下载前 **512MB** 数据用于校验。
4. **错误处理**：捕获 `CosServiceError`（服务端错误）和 `CosClientError`（客户端错误），输出错误信息并退出。

## 依赖

- `cos-python-sdk-v5`（qcloud_cos 包）
