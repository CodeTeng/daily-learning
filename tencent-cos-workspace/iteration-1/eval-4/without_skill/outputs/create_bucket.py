"""
腾讯云 COS 存储桶创建与验证脚本

功能：
  1. 从环境变量读取腾讯云密钥
  2. 在指定地域创建 COS 存储桶，并设置公共读访问权限（适用于静态网站托管）
  3. 通过 head_bucket 验证存储桶是否创建成功

环境变量要求：
  - TENCENT_SECRET_ID: 腾讯云 SecretId
  - TENCENT_SECRET_KEY: 腾讯云 SecretKey

依赖：
  pip install cos-python-sdk-v5
"""

import os
import sys
import logging

from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos.cos_exception import CosServiceError, CosClientError


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
BUCKET_NAME = "my-app-static-1250000000"
REGION = "ap-shanghai"
ACL = "public-read"  # 公共读，适用于静态网站托管

# 为 SDK 内部日志和自定义日志配置级别
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 客户端初始化
# ---------------------------------------------------------------------------
def build_client() -> CosS3Client:
    """从环境变量读取密钥，初始化并返回 COS 客户端。"""
    secret_id = os.getenv("TENCENT_SECRET_ID")
    secret_key = os.getenv("TENCENT_SECRET_KEY")

    if not secret_id or not secret_key:
        logger.error(
            "缺少必要的环境变量。请设置 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY。"
        )
        sys.exit(1)

    config = CosConfig(
        Region=REGION,
        SecretId=secret_id,
        SecretKey=secret_key,
    )
    return CosS3Client(config)


# ---------------------------------------------------------------------------
# 创建存储桶
# ---------------------------------------------------------------------------
def create_bucket(client: CosS3Client) -> None:
    """创建指定名称、地域和 ACL 的 COS 存储桶。"""
    logger.info(
        "正在创建存储桶: %s（地域: %s，访问权限: %s）...",
        BUCKET_NAME,
        REGION,
        ACL,
    )
    try:
        response = client.create_bucket(
            Bucket=BUCKET_NAME,
            Region=REGION,
            ACL=ACL,
        )
        logger.info("存储桶创建请求已发送。响应: %s", response)
    except CosServiceError as e:
        # 例如桶已存在（BucketAlreadyExists / BucketAlreadyOwnedByYou）等情况
        logger.error(
            "创建存储桶时 COS 服务返回错误。"
            "HTTP 状态码: %s, 错误码: %s, 错误信息: %s",
            e.get_status_code(),
            e.get_error_code(),
            e.get_error_msg(),
        )
        raise
    except CosClientError as e:
        logger.error("创建存储桶时客户端发生错误: %s", e)
        raise


# ---------------------------------------------------------------------------
# 验证存储桶
# ---------------------------------------------------------------------------
def verify_bucket(client: CosS3Client) -> None:
    """通过 head_bucket 确认存储桶是否存在且可访问。"""
    logger.info("正在验证存储桶是否可访问: %s...", BUCKET_NAME)
    try:
        response = client.head_bucket(Bucket=BUCKET_NAME)
        logger.info("存储桶验证成功！存储桶 %s 已存在且可正常访问。", BUCKET_NAME)
        logger.info("响应头: %s", response)
    except CosServiceError as e:
        logger.error(
            "验证存储桶时 COS 服务返回错误。"
            "HTTP 状态码: %s, 错误码: %s, 错误信息: %s",
            e.get_status_code(),
            e.get_error_code(),
            e.get_error_msg(),
        )
        raise
    except CosClientError as e:
        logger.error("验证存储桶时客户端发生错误: %s", e)
        raise


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("===== 腾讯云 COS 存储桶创建工具 =====")

    client = build_client()

    try:
        create_bucket(client)
    except (CosServiceError, CosClientError):
        logger.warning("存储桶可能已存在，继续尝试验证...")

    try:
        verify_bucket(client)
    except (CosServiceError, CosClientError):
        logger.critical("存储桶验证失败，请检查配置和网络。")
        sys.exit(1)

    logger.info("===== 完成 =====")


if __name__ == "__main__":
    main()
