"""
遍历 COS 存储桶 media-assets-1250000000 中 images/ 前缀下的所有文件，
打印文件名（Key）和文件大小（Size），并支持分页处理（文件超过 1000 个时自动翻页）。
"""

import os
import sys
from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos import CosServiceError, CosClientError
from dotenv import load_dotenv


def init_client() -> CosS3Client:
    """初始化 COS 客户端，从环境变量/.env/.cos/config 读取密钥。"""
    load_dotenv()

    secret_id = os.getenv("TENCENT_SECRET_ID")
    secret_key = os.getenv("TENCENT_SECRET_KEY")
    region = os.getenv("TENCENT_COS_REGION", "ap-beijing")

    if not secret_id or not secret_key:
        raise RuntimeError(
            "COS 密钥未配置。请运行: python scripts/init_config.py\n"
            "或设置环境变量 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY"
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
    return CosS3Client(config)


def list_objects_by_prefix(
    client: CosS3Client,
    bucket: str,
    prefix: str,
    max_keys: int = 1000,
) -> None:
    """分页遍历指定前缀下的所有对象，打印 Key 和 Size。

    Args:
        client: COS 客户端实例。
        bucket: 存储桶名称（含 APPID，如 media-assets-1250000000）。
        prefix: 对象键前缀，如 images/。
        max_keys: 单次请求返回的最大条目数，默认 1000。
    """
    marker = ""
    page = 1
    total_count = 0
    total_size = 0

    while True:
        try:
            response = client.list_objects(
                Bucket=bucket,
                Prefix=prefix,
                Marker=marker,
                MaxKeys=max_keys,
            )
        except CosServiceError as e:
            print(f"服务端错误: {e.get_error_code()} - {e.get_error_msg()}")
            print(f"HTTP 状态码: {e.get_status_code()}")
            print(f"Request ID: {e.get_request_id()}")
            sys.exit(1)
        except CosClientError as e:
            print(f"客户端错误: {e}")
            sys.exit(1)

        if "Contents" in response:
            for obj in response["Contents"]:
                key = obj["Key"]
                size = obj["Size"]
                print(f"{key}  {size}")
                total_count += 1
                total_size += size
        else:
            print(f"前缀 '{prefix}' 下没有找到任何文件。")
            return

        # 检查是否还有更多数据
        if response["IsTruncated"] == "false":
            break

        marker = response["NextMarker"]
        page += 1

    print(f"\n总计: {total_count} 个文件, 总大小 {total_size} bytes "
          f"({total_size / 1024 / 1024:.2f} MB)")


def main() -> None:
    bucket = "media-assets-1250000000"
    prefix = "images/"

    print(f"正在遍历存储桶 {bucket} 中前缀为 '{prefix}' 的文件...\n")

    client = init_client()
    list_objects_by_prefix(client, bucket, prefix)


if __name__ == "__main__":
    main()
