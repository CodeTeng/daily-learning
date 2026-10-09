#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将本地 Excel 文件上传到腾讯云 COS 存储桶。

使用方式：
    python upload_file.py
"""

import os
import sys
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos import CosServiceError, CosClientError
from dotenv import load_dotenv


# ============================================================
# 1. 加载配置（按优先级：.env > ~/.cos/config > 环境变量）
# ============================================================
load_dotenv()

secret_id = os.getenv("TENCENT_SECRET_ID")
secret_key = os.getenv("TENCENT_SECRET_KEY")
region = os.getenv("TENCENT_COS_REGION", "ap-beijing")

if not secret_id or not secret_key:
    raise RuntimeError(
        "COS 密钥未配置。请设置环境变量 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY "
        "或创建 .env 文件。也可以运行: python scripts/init_config.py"
    )

# ============================================================
# 2. 初始化 COS 客户端
# ============================================================
config = CosConfig(
    Region=region,
    SecretId=secret_id,
    SecretKey=secret_key,
    Scheme="https",
    Timeout=30,
    PoolConnections=10,
    PoolMaxSize=10,
)
client = CosS3Client(config)

# ============================================================
# 3. 上传参数
# ============================================================
BUCKET = "my-data-1250000000"
LOCAL_FILE = Path(__file__).resolve().parents[3] / "data" / "sales-report-2026Q3.xlsx"
COS_KEY = "reports/sales-report-2026Q3.xlsx"
CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload_excel_file() -> None:
    """上传 Excel 文件到 COS，带 MD5 校验和完整的错误处理。"""
    # 检查本地文件是否存在
    if not LOCAL_FILE.exists():
        print(f"[错误] 本地文件不存在: {LOCAL_FILE}")
        sys.exit(1)

    file_size_mb = LOCAL_FILE.stat().st_size / (1024 * 1024)
    print(f"[信息] 本地文件: {LOCAL_FILE}")
    print(f"[信息] 文件大小: {file_size_mb:.2f} MB")
    print(f"[信息] 目标存储桶: {BUCKET}")
    print(f"[信息] COS 路径: {COS_KEY}")
    print(f"[信息] ContentType: {CONTENT_TYPE}")
    print(f"[信息] 开始上传...")

    try:
        response = client.put_object_from_local_file(
            Bucket=BUCKET,
            LocalFilePath=str(LOCAL_FILE),
            Key=COS_KEY,
            EnableMD5=True,
            ContentType=CONTENT_TYPE,
        )
        print(f"[成功] 文件上传完成！")
        print(f"[成功] ETag: {response['ETag']}")
        print(f"[成功] Request ID: {response.get('x-cos-request-id', 'N/A')}")

    except CosServiceError as e:
        # 服务端错误（如权限不足、存储桶不存在）
        print(f"[服务端错误] 错误码: {e.get_error_code()}")
        print(f"[服务端错误] 错误信息: {e.get_error_msg()}")
        print(f"[服务端错误] HTTP 状态码: {e.get_status_code()}")
        print(f"[服务端错误] Request ID: {e.get_request_id()}")
        print(f"[服务端错误] Resource: {e.get_resource_location()}")
        sys.exit(1)

    except CosClientError as e:
        # 客户端错误（如网络超时、DNS 解析失败）
        print(f"[客户端错误] {e}")
        sys.exit(1)

    except Exception as e:
        # 其他未预期的错误
        print(f"[未知错误] {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    upload_excel_file()
