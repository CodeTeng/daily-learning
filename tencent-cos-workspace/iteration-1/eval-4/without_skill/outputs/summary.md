# 代码说明

## 功能概述

本脚本使用腾讯云 COS Python SDK (`cos-python-sdk-v5`) 实现了以下功能：

1. **客户端初始化**：从 `TENCENT_SECRET_ID` 和 `TENCENT_SECRET_KEY` 环境变量读取腾讯云 API 密钥，构建 `CosS3Client` 客户端实例。
2. **创建存储桶**：调用 `create_bucket` API，在 `ap-shanghai` 地域创建一个名为 `my-app-static-1250000000` 的存储桶，并设置访问权限为 `public-read`（公共读，适用于静态网站托管场景）。
3. **验证创建结果**：通过 `head_bucket` API 确认存储桶已成功创建且可正常访问。
4. **错误处理**：捕获 `CosServiceError`（服务端错误，如桶已存在）和 `CosClientError`（客户端错误，如网络异常）两类异常，并输出清晰的错误日志。

## 运行方式

```bash
# 1. 安装依赖
pip install cos-python-sdk-v5

# 2. 设置环境变量
export TENCENT_SECRET_ID="your-secret-id"
export TENCENT_SECRET_KEY="your-secret-key"

# 3. 运行脚本
python create_bucket.py
```
