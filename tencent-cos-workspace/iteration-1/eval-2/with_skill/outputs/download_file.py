"""
从腾讯云 COS 下载文件，支持大文件范围下载校验。

需求：
- 从存储桶 data-backup-1250000000 下载 backups/db-2026-07-25.tar.gz
- 保存到本地 ./downloads/ 目录
- 如果文件超过 1GB，只下载前 512MB 用于校验
"""

import os
import sys
from pathlib import Path

from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos import CosServiceError, CosClientError
from dotenv import load_dotenv

# ============================================================
# 配置常量
# ============================================================

BUCKET = "data-backup-1250000000"
KEY = "backups/db-2026-07-25.tar.gz"
LOCAL_DIR = Path("./downloads")

# 阈值：超过 1GB 则只下载前 512MB
SIZE_THRESHOLD = 1 * 1024 * 1024 * 1024  # 1 GB
PARTIAL_SIZE = 512 * 1024 * 1024          # 512 MB

# ============================================================
# 1. 客户端初始化（按照 skill 模式）
# ============================================================

load_dotenv()

secret_id = os.getenv("TENCENT_SECRET_ID")
secret_key = os.getenv("TENCENT_SECRET_KEY")
region = os.getenv("TENCENT_COS_REGION", "ap-beijing")

if not secret_id or not secret_key:
    raise RuntimeError(
        "COS 密钥未配置。请在 .env 文件、~/.cos/config 文件或环境变量中设置 "
        "TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY。\n"
        "也可以运行: python scripts/init_config.py"
    )

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

print(f"[INFO] COS 客户端已初始化，地域: {region}")

# ============================================================
# 2. 检查文件大小（head_object）
# ============================================================

print(f"[INFO] 正在查询文件信息: {KEY}")
print(f"[INFO] 存储桶: {BUCKET}")

try:
    head_response = client.head_object(Bucket=BUCKET, Key=KEY)
except CosServiceError as e:
    print(f"[ERROR] 查询文件失败 - 服务端错误")
    print(f"  错误码: {e.get_error_code()}")
    print(f"  错误信息: {e.get_error_msg()}")
    print(f"  HTTP 状态码: {e.get_status_code()}")
    print(f"  Request ID: {e.get_request_id()}")
    sys.exit(1)
except CosClientError as e:
    print(f"[ERROR] 查询文件失败 - 客户端错误: {e}")
    sys.exit(1)

file_size = int(head_response.get("Content-Length", 0))
print(f"[INFO] 文件大小: {file_size:,} bytes ({file_size / (1024**3):.2f} GB)")

# ============================================================
# 3. 决定下载策略
# ============================================================

if file_size > SIZE_THRESHOLD:
    print(
        f"[INFO] 文件大小超过 {SIZE_THRESHOLD / (1024**3):.0f}GB 阈值，"
        f"将只下载前 {PARTIAL_SIZE / (1024**2):.0f}MB 用于校验"
    )
    range_header = f"bytes=0-{PARTIAL_SIZE - 1}"
    download_mode = "partial"
    target_filename = f"{Path(KEY).stem}.partial{Path(KEY).suffix}"
else:
    print("[INFO] 文件大小在阈值以下，将进行全量下载")
    range_header = None
    download_mode = "full"
    target_filename = Path(KEY).name

# ============================================================
# 4. 执行下载
# ============================================================

LOCAL_DIR.mkdir(parents=True, exist_ok=True)
local_path = LOCAL_DIR / target_filename

print(f"[INFO] 下载模式: {download_mode}")
print(f"[INFO] 保存路径: {local_path}")

try:
    if range_header:
        response = client.get_object(
            Bucket=BUCKET,
            Key=KEY,
            Range=range_header,
        )
    else:
        response = client.get_object(
            Bucket=BUCKET,
            Key=KEY,
        )

    response["Body"].get_stream_to_file(str(local_path))

except CosServiceError as e:
    print(f"[ERROR] 下载失败 - 服务端错误")
    print(f"  错误码: {e.get_error_code()}")
    print(f"  错误信息: {e.get_error_msg()}")
    print(f"  HTTP 状态码: {e.get_status_code()}")
    print(f"  Request ID: {e.get_request_id()}")
    sys.exit(1)
except CosClientError as e:
    print(f"[ERROR] 下载失败 - 客户端错误: {e}")
    sys.exit(1)

# ============================================================
# 5. 校验下载结果
# ============================================================

downloaded_size = local_path.stat().st_size
print(f"[INFO] 下载完成")
print(f"  本地文件大小: {downloaded_size:,} bytes ({downloaded_size / (1024**2):.2f} MB)")

if download_mode == "partial":
    expected = PARTIAL_SIZE
    if downloaded_size == expected:
        print(f"[OK] 校验通过: 下载大小 ({downloaded_size:,}) 与预期 ({expected:,}) 一致")
    else:
        print(
            f"[WARN] 大小不匹配: 预期 {expected:,} bytes，实际 {downloaded_size:,} bytes"
        )
else:
    if downloaded_size == file_size:
        print(f"[OK] 校验通过: 下载大小与远程文件大小一致 ({file_size:,} bytes)")
    else:
        print(
            f"[WARN] 大小不匹配: 远程 {file_size:,} bytes，本地 {downloaded_size:,} bytes"
        )

print(f"[INFO] 文件已保存至: {local_path.resolve()}")
