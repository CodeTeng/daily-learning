"""
腾讯云 COS 创建存储桶示例

功能：在指定地域创建一个 public-read 的存储桶，并验证创建结果。

要求：
- 从环境变量或 .env 文件读取腾讯云密钥
- 创建前检查必要配置是否存在
- 创建存储桶并设置访问权限
- 通过 head_bucket 验证创建是否成功
- 完整的错误处理
"""

import os
import sys

from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos import CosServiceError, CosClientError
from dotenv import load_dotenv


# ── 配置加载 ──────────────────────────────────────────────

# 加载 .env 文件（如果存在）
load_dotenv()

secret_id = os.getenv("TENCENT_SECRET_ID")
secret_key = os.getenv("TENCENT_SECRET_KEY")
default_region = os.getenv("TENCENT_COS_REGION", "ap-beijing")

if not secret_id or not secret_key:
    print("[ERROR] 未配置腾讯云密钥。")
    print("请将密钥写入 .env 文件或设置系统环境变量：")
    print("  TENCENT_SECRET_ID=AKIDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    print("  TENCENT_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    sys.exit(1)


# ── 客户端初始化 ──────────────────────────────────────────

config = CosConfig(
    Region=default_region,          # 默认地域（创建桶时会覆盖）
    SecretId=secret_id,
    SecretKey=secret_key,
    Scheme="https",
    Timeout=30,
    PoolConnections=10,
    PoolMaxSize=10,
)
client = CosS3Client(config)


# ── 参数 ───────────────────────────────────────────────────

BUCKET_NAME = "my-app-static-1250000000"
REGION = "ap-shanghai"
ACL = "public-read"  # 用于静态网站托管


# ── 创建存储桶 ────────────────────────────────────────────

print(f"[INFO] 正在创建存储桶: {BUCKET_NAME}")
print(f"       地域: {REGION}")
print(f"       访问权限: {ACL}")

try:
    response = client.create_bucket(
        Bucket=BUCKET_NAME,
        Region=REGION,
        ACL=ACL,
    )
    print(f"[OK] 创建请求已发送，Location: {response.get('Location', 'N/A')}")
except CosServiceError as e:
    print(f"[ERROR] COS 服务错误: {e.get_error_code()} - {e.get_error_msg()}")
    print(f"        HTTP 状态码: {e.get_status_code()}")
    print(f"        Request ID: {e.get_request_id()}")
    print("\n可能原因：")
    print("  - 存储桶名称已被占用（全局唯一）")
    print("  - 密钥权限不足（需要 PutBucket 权限）")
    print("  - 地域名称拼写错误")
    sys.exit(1)
except CosClientError as e:
    print(f"[ERROR] 客户端错误: {e}")
    print("\n可能原因：")
    print("  - 网络连接失败")
    print("  - DNS 解析失败")
    print("  - 请求超时")
    sys.exit(1)


# ── 验证存储桶 ────────────────────────────────────────────

print(f"\n[INFO] 正在验证存储桶是否存在...")

try:
    head_response = client.head_bucket(Bucket=BUCKET_NAME)
    status = head_response.get("x-cos-bucket-region", "unknown")
    print(f"[OK] 存储桶 {BUCKET_NAME} 已成功创建！")
    print(f"     所在区域: {status}")
except CosServiceError as e:
    if e.get_status_code() == 404:
        print(f"[WARN] 存储桶 {BUCKET_NAME} 不存在（可能需要等待传播）")
    elif e.get_status_code() == 403:
        print(f"[OK] 存储桶 {BUCKET_NAME} 存在但无访问权限（对于 public-read 桶，head_bucket 可能需要 s3:ListBucket 权限）")
    else:
        print(f"[ERROR] 查询失败: {e.get_error_code()} - {e.get_error_msg()}")
        print(f"        HTTP 状态码: {e.get_status_code()}")
        sys.exit(1)
except CosClientError as e:
    print(f"[ERROR] 客户端错误: {e}")
    sys.exit(1)
