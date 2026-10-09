"""
遍历腾讯云 COS 存储桶中指定前缀下的所有文件，打印文件名和文件大小。

功能：
- 从环境变量读取密钥初始化 COS 客户端
- 通过分页（Marker 机制）遍历所有对象，自动处理超过 1000 个文件的情况
- 打印每个文件的 Key 和 Size
- 包含完善的错误处理

环境变量要求：
    COS_SECRET_ID: 腾讯云 SecretId
    COS_SECRET_KEY: 腾讯云 SecretKey
"""

import os
import sys
from typing import Optional

from qcloud_cos import CosClientError, CosConfig, CosS3Client, CosServiceError


def init_cos_client(region: str = "ap-guangzhou") -> CosS3Client:
    """
    从环境变量读取密钥，初始化并返回 COS 客户端。

    Args:
        region: 存储桶所在地域，默认广州

    Returns:
        初始化好的 CosS3Client 实例

    Raises:
        ValueError: 缺少必要的环境变量时抛出
    """
    secret_id: Optional[str] = os.getenv("COS_SECRET_ID")
    secret_key: Optional[str] = os.getenv("COS_SECRET_KEY")

    if not secret_id or not secret_key:
        raise ValueError(
            "缺少必要的环境变量，请设置 COS_SECRET_ID 和 COS_SECRET_KEY。\n"
            "示例：\n"
            "  export COS_SECRET_ID=your-secret-id\n"
            "  export COS_SECRET_KEY=your-secret-key"
        )

    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
    )
    return CosS3Client(config)


def list_objects_with_pagination(
    client: CosS3Client,
    bucket: str,
    prefix: str,
    max_keys: int = 1000,
) -> list[dict]:
    """
    分页遍历 COS 存储桶中指定前缀下的所有文件。

    通过 Marker 机制实现分页：
    - 每次请求最多返回 max_keys 条记录
    - 如果 IsTruncated 为 True，则使用 NextMarker 继续请求
    - 循环直到所有文件遍历完毕

    Args:
        client: COS 客户端实例
        bucket: 存储桶名称（格式：bucketname-appid）
        prefix: 对象键前缀，用于过滤文件
        max_keys: 单次请求最多返回的对象数量（最大 1000）

    Returns:
        所有匹配文件的字典列表，每个字典包含 Key 和 Size 等字段
    """
    all_objects: list[dict] = []
    marker: str = ""
    page_num: int = 0

    while True:
        page_num += 1
        try:
            response = client.list_objects(
                Bucket=bucket,
                Prefix=prefix,
                Marker=marker,
                MaxKeys=max_keys,
            )
        except CosServiceError as e:
            print(f"[错误] COS 服务返回错误 (第 {page_num} 页): {e}", file=sys.stderr)
            break
        except CosClientError as e:
            print(f"[错误] COS 客户端错误 (第 {page_num} 页): {e}", file=sys.stderr)
            break

        contents = response.get("Contents", [])
        if not contents:
            print(f"[信息] 第 {page_num} 页返回 0 条记录，可能是前缀下没有更多文件。")
            break

        all_objects.extend(contents)
        print(
            f"[分页] 第 {page_num} 页获取 {len(contents)} 条记录 "
            f"(累计 {len(all_objects)} 条)"
        )

        # 检查是否还有更多记录
        if response.get("IsTruncated") == "true":
            marker = response.get("NextMarker", "")
            if not marker and contents:
                # 某些情况下 SDK 可能不返回 NextMarker，
                # 此时用本次返回的最后一条记录的 Key 作为下一页的 Marker
                marker = contents[-1]["Key"]
        else:
            print(f"[完成] 所有文件已遍历完毕，共 {len(all_objects)} 个文件。")
            break

    return all_objects


def print_file_list(objects: list[dict]) -> None:
    """
    打印文件列表，格式化输出 Key 和 Size。

    Args:
        objects: 文件对象字典列表，每个字典应包含 Key 和 Size 字段
    """
    if not objects:
        print("[结果] 未找到任何文件。")
        return

    # 计算 Key 列的最大宽度，用于对齐输出
    max_key_len = max((len(obj.get("Key", "")) for obj in objects), default=0)
    max_key_len = min(max_key_len, 80)  # 限制最大宽度

    print(f"\n{'Key':<{max_key_len}}  {'Size (Bytes)':>12}")
    print("-" * (max_key_len + 15))

    total_size: int = 0
    for obj in objects:
        key: str = obj.get("Key", "N/A")
        size: int = obj.get("Size", 0)
        total_size += size

        # 超过宽度的 Key 截断显示
        display_key = key if len(key) <= max_key_len else key[: max_key_len - 3] + "..."

        # 格式化文件大小（自动选择合适的单位）
        size_str = format_size(size)

        print(f"{display_key:<{max_key_len}}  {size_str:>12}")

    print("-" * (max_key_len + 15))
    print(f"{'总计':<{max_key_len}}  {format_size(total_size):>12}")
    print(f"共 {len(objects)} 个文件")


def format_size(size_bytes: int) -> str:
    """
    将字节数转换为可读的文件大小格式。

    Args:
        size_bytes: 文件大小（字节）

    Returns:
        格式化后的文件大小字符串，如 "1.50 KB"、"2.00 MB"
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def main() -> None:
    """
    主函数：初始化 COS 客户端，分页遍历指定前缀下的文件并打印。
    """
    # 配置参数
    BUCKET = "media-assets-1250000000"
    PREFIX = "images/"

    print(f"=" * 60)
    print(f"COS 文件列表工具")
    print(f"存储桶: {BUCKET}")
    print(f"前缀:   {PREFIX}")
    print(f"=" * 60)

    try:
        client = init_cos_client()
    except ValueError as e:
        print(f"[致命错误] 初始化失败: {e}", file=sys.stderr)
        sys.exit(1)

    print("[信息] COS 客户端初始化成功，开始遍历文件...\n")

    objects = list_objects_with_pagination(client, BUCKET, PREFIX)
    print_file_list(objects)


if __name__ == "__main__":
    main()
