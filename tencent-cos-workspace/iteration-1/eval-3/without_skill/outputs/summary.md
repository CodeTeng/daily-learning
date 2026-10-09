# COS 文件列表工具 -- 实现说明

## 功能概述

该脚本使用腾讯云 COS Python SDK (`cos-python-sdk-v5`) 遍历 COS 存储桶 `media-assets-1250000000` 中 `images/` 前缀下的所有文件，打印每个文件的名称（Key）和文件大小（Size），并自动处理分页以确保能遍历超过 1000 个文件的情况。

## 实现细节

### 1. 客户端初始化
- 从环境变量 `COS_SECRET_ID` 和 `COS_SECRET_KEY` 读取腾讯云 API 密钥
- 默认连接地域为 `ap-guangzhou`（广州）
- 密钥缺失时抛出明确的 `ValueError` 错误

### 2. 分页循环逻辑
- 使用 COS SDK 的 `list_objects` 方法，每次请求最多返回 1000 条记录
- 通过 **Marker 分页机制** 实现跨页遍历：SDK 响应中的 `IsTruncated` 字段为 `"true"` 时表示还有更多数据，使用 `NextMarker` 字段作为下一次请求的起始位置
- 如果 SDK 未返回 `NextMarker`（极端情况），自动用当前页最后一条记录的 Key 作为兜底
- 循环调用直到 `IsTruncated` 不为 `"true"` 或返回空结果

### 3. 输出格式化
- 对齐打印 Key 和 Size
- 文件大小自动转换为可读格式（B / KB / MB / GB）
- 末尾输出文件总数和总大小

### 4. 错误处理
- `CosServiceError`：捕获 COS 服务端返回的错误
- `CosClientError`：捕获客户端层面的错误（网络超时等）
- 初始化阶段的密钥校验，避免无意义的空请求

## 运行方式

```bash
# 设置环境变量
export COS_SECRET_ID=your-secret-id
export COS_SECRET_KEY=your-secret-key

# 运行脚本
python list_objects.py
```
