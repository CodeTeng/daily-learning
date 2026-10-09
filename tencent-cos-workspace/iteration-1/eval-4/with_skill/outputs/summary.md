# 创建 COS 存储桶脚本说明

## 功能概述

本脚本用于在腾讯云 COS（对象存储）上创建一个新的存储桶，用于静态网站托管场景。

## 实现内容

1. **密钥加载**：从 `.env` 文件或系统环境变量中读取 `TENCENT_SECRET_ID` 和 `TENCENT_SECRET_KEY`，缺少任一密钥时报错退出。

2. **客户端初始化**：按 skill 文件中的标准模式，创建 `CosConfig` 配置对象并初始化 `CosS3Client`，使用 HTTPS 协议、30 秒超时、连接池大小为 10。

3. **创建存储桶**：
   - 桶名：`my-app-static-1250000000`
   - 地域：`ap-shanghai`（上海）
   - 访问权限：`public-read`（公开读，适合静态网站托管）

4. **验证创建结果**：通过 `head_bucket` 方法检查存储桶是否存在及是否可访问。

5. **错误处理**：
   - `CosServiceError`：处理 COS 服务端返回的错误（如桶名冲突、权限不足）
   - `CosClientError`：处理客户端侧错误（如网络超时、DNS 问题）
   - 404 和 403 状态码的特殊处理逻辑

## 注意事项

- 存储桶名称必须以 APPID 结尾（格式为 `<name>-<APPID>`）
- `public-read` 权限意味着任何人可以读取桶内的对象，上传和删除仍需要密钥认证
- `create_bucket` 中的 `Region` 参数用于指定数据中心的物理位置
