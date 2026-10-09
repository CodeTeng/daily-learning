#!/usr/bin/env python3
"""
上传本地 Excel 文件到腾讯云 COS 存储桶。

功能：
- 从环境变量读取 SecretId / SecretKey
- 设置 ContentType 为 Excel 对应的 MIME 类型
- 开启 MD5 校验，确保上传完整性
- 完整的错误处理和友好的输出信息
"""

import os
import sys
from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosClientError, CosServiceError


def upload_file_to_cos() -> None:
    """
    将本地 Excel 文件上传到指定的 COS 存储桶目录下。
    """

    # ── 1. 从环境变量读取访问凭证 ──────────────────────────────────────────
    secret_id: str | None = os.environ.get("COS_SECRET_ID")
    secret_key: str | None = os.environ.get("COS_SECRET_KEY")

    if not secret_id or not secret_key:
        print("错误：请设置环境变量 COS_SECRET_ID 和 COS_SECRET_KEY")
        sys.exit(1)

    # ── 2. 配置参数 ────────────────────────────────────────────────────────
    region: str = "ap-guangzhou"                     # 存储桶所在地域，按实际情况修改
    bucket_name: str = "my-data-1250000000"          # 存储桶名称（含 APPID）
    local_file_path: str = "./data/sales-report-2026Q3.xlsx"  # 本地文件路径
    cos_object_key: str = "reports/sales-report-2026Q3.xlsx"  # COS 上的对象键（路径）

    # ── 3. 检查本地文件是否存在 ────────────────────────────────────────────
    if not os.path.isfile(local_file_path):
        print(f"错误：找不到本地文件 {local_file_path}")
        sys.exit(1)

    # ── 4. 初始化 COS 客户端 ───────────────────────────────────────────────
    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Scheme="https",       # 使用 HTTPS
    )
    client = CosS3Client(config)

    # ── 5. 上传文件（带 MD5 校验） ─────────────────────────────────────────
    try:
        response = client.upload_file(
            Bucket=bucket_name,
            Key=cos_object_key,
            LocalFilePath=local_file_path,
            EnableMD5=True,   # 开启 MD5 校验，确保数据完整性
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # 提取关键响应信息
        etag: str = response.get("ETag", "")
        request_id: str = response.get("x-cos-request-id", "")

        print("上传成功！")
        print(f"  本地文件 : {local_file_path}")
        print(f"  目标位置 : {bucket_name}/{cos_object_key}")
        print(f"  存储区域 : {region}")
        print(f"  ETag     : {etag}")
        print(f"  RequestId: {request_id}")

    except FileNotFoundError:
        print(f"错误：找不到本地文件 {local_file_path}")
        sys.exit(1)

    except CosClientError as e:
        # 客户端错误（如网络问题、参数错误）
        print(f"客户端错误：{e}")
        sys.exit(1)

    except CosServiceError as e:
        # 服务端错误（COS 返回的错误）
        print(f"服务端错误：")
        print(f"  错误码   : {e.get_error_code()}")
        print(f"  错误信息 : {e.get_error_msg()}")
        print(f"  RequestId: {e.get_request_id()}")
        print(f"  HTTP 状态: {e.get_status_code()}")
        sys.exit(1)

    except Exception as e:
        print(f"未知错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    upload_file_to_cos()
