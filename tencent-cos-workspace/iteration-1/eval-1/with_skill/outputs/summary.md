# 上传文件到腾讯云 COS

将本地 Excel 文件 `data/sales-report-2026Q3.xlsx` 上传到腾讯云 COS 存储桶 `my-data-1250000000` 的 `reports/` 目录下。

实现要点：

1. 从环境变量或 `.env` 文件读取腾讯云密钥和地域配置，初始化 `CosS3Client`
2. 使用 `put_object_from_local_file` 方法上传本地文件
3. 设置 `ContentType` 为 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
4. 开启 `EnableMD5=True` 进行 MD5 完整性校验
5. 捕获 `CosServiceError` 和 `CosClientError` 两类异常并输出详细信息
