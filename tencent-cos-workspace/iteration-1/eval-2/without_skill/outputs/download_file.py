"""
从腾讯云 COS 存储桶下载文件。

功能：
- 从环境变量读取 COS 凭证（SECRET_ID、SECRET_KEY、REGION）
- 先用 head_object 检查文件大小
- 若文件超过 1GB，仅下载前 512MB 用于校验
- 否则全量下载

用法：
    1. 设置环境变量：
       export COS_SECRET_ID="your-secret-id"
       export COS_SECRET_KEY="your-secret-key"
       export COS_REGION="ap-guangzhou"
    2. python download_file.py
"""

import os
import sys
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosClientError, CosServiceError

# ---- 配置 ----
BUCKET = "data-backup-1250000000"
OBJECT_KEY = "backups/db-2026-07-25.tar.gz"
LOCAL_DIR = Path("./downloads")
ONE_GB = 1024 * 1024 * 1024       # 1 GB
PARTIAL_LIMIT = 512 * 1024 * 1024  # 512 MB


def get_cos_client() -> CosS3Client:
    """从环境变量读取凭证，初始化并返回 COS 客户端。"""
    secret_id = os.getenv("COS_SECRET_ID")
    secret_key = os.getenv("COS_SECRET_KEY")
    region = os.getenv("COS_REGION")

    if not all([secret_id, secret_key, region]):
        print("错误：缺少必要的环境变量，请设置 COS_SECRET_ID、COS_SECRET_KEY、COS_REGION")
        sys.exit(1)

    config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
    return CosS3Client(config)


def get_file_size(client: CosS3Client) -> int:
    """通过 head_object 获取远端文件大小（字节）。"""
    try:
        resp = client.head_object(Bucket=BUCKET, Key=OBJECT_KEY)
        size = int(resp["Content-Length"])
        print(f"远端文件大小: {size} 字节 ({size / (1024**3):.2f} GB)")
        return size
    except CosServiceError as e:
        print(f"head_object 失败: {e.get_error_msg()}")
        sys.exit(1)
    except CosClientError as e:
        print(f"客户端错误: {e}")
        sys.exit(1)


def download_full(client: CosS3Client, local_path: Path) -> None:
    """全量下载文件到本地路径。"""
    try:
        print("文件小于 1GB，开始全量下载...")
        resp = client.get_object(Bucket=BUCKET, Key=OBJECT_KEY)
        resp["Body"].get_stream_to_file(str(local_path))
        print(f"下载完成 -> {local_path}")
    except (CosServiceError, CosClientError) as e:
        print(f"下载失败: {e}")
        sys.exit(1)


def download_partial(client: CosS3Client, local_path: Path, limit: int) -> None:
    """范围下载文件的前 limit 字节到本地路径。"""
    try:
        range_header = f"bytes=0-{limit - 1}"
        print(f"文件超过 1GB，仅下载前 {limit / (1024**2):.0f} MB（Range: {range_header}）...")
        resp = client.get_object(Bucket=BUCKET, Key=OBJECT_KEY, Range=range_header)
        resp["Body"].get_stream_to_file(str(local_path))
        print(f"下载完成 -> {local_path}")
    except (CosServiceError, CosClientError) as e:
        print(f"下载失败: {e}")
        sys.exit(1)


def main() -> None:
    client = get_cos_client()
    file_size = get_file_size(client)

    # 确保本地目录存在
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    local_file = LOCAL_DIR / OBJECT_KEY.split("/")[-1]

    if file_size > ONE_GB:
        download_partial(client, local_file, PARTIAL_LIMIT)
    else:
        download_full(client, local_file)


if __name__ == "__main__":
    main()
