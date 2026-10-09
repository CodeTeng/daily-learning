"""
腾讯云 COS 预签名下载 URL 生成工具

功能：为 COS 中的文件生成带有效期的预签名下载 URL，
      并通过 response-content-disposition 参数强制浏览器下载（而非预览）。
"""

import os
import sys
from qcloud_cos import CosConfig, CosS3Client


def get_presigned_download_url(
    bucket: str,
    key: str,
    expired: int = 7200,
    region: str = "ap-guangzhou",
    download_filename: str | None = None,
) -> str:
    """
    为 COS 文件生成预签名下载 URL，强制浏览器触发下载。

    Args:
        bucket: 存储桶名称，格式为 <BucketName>-<APPID>，如 my-bucket-1250000000
        key:    COS 中的对象键（文件路径），如 private/reports/audit-2026.pdf
        expired: 签名有效期，单位秒，默认 7200（2 小时）
        region: 存储桶所在地域，默认 ap-guangzhou
        download_filename: 浏览器下载时显示的文件名，默认为 key 的文件名部分

    Returns:
        预签名下载 URL 字符串

    Raises:
        ValueError: 缺少必要的环境变量时抛出
        CosClientError / CosServiceError: COS SDK 异常
    """

    # 1. 从环境变量读取密钥
    secret_id = os.getenv("COS_SECRET_ID")
    secret_key = os.getenv("COS_SECRET_KEY")

    if not secret_id or not secret_key:
        raise ValueError(
            "缺少必要的环境变量，请设置 COS_SECRET_ID 和 COS_SECRET_KEY"
        )

    # 2. 初始化 COS 客户端
    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
    )
    client = CosS3Client(config)

    # 3. 确定下载文件名
    if download_filename is None:
        download_filename = os.path.basename(key)

    # 4. 构造强制下载参数
    params = {
        "response-content-disposition": f'attachment; filename="{download_filename}"',
    }

    # 5. 生成预签名 URL
    url = client.get_presigned_download_url(
        Bucket=bucket,
        Key=key,
        Expired=expired,
        Params=params,
    )

    return url


def main() -> None:
    """主函数：演示如何生成预签名下载 URL。"""

    # ======================== 配置区域 ========================
    BUCKET = "my-bucket-1250000000"
    KEY = "private/reports/audit-2026.pdf"
    EXPIRED = 7200  # 2 小时
    REGION = "ap-guangzhou"
    DOWNLOAD_FILENAME = "audit-2026.pdf"  # 浏览器下载时显示的文件名
    # =========================================================

    print("=" * 60)
    print("腾讯云 COS 预签名下载 URL 生成工具")
    print("=" * 60)

    try:
        url = get_presigned_download_url(
            bucket=BUCKET,
            key=KEY,
            expired=EXPIRED,
            region=REGION,
            download_filename=DOWNLOAD_FILENAME,
        )

        print(f"\n存储桶 : {BUCKET}")
        print(f"文件路径 : {KEY}")
        print(f"有效期 : {EXPIRED} 秒（{EXPIRED / 3600:.0f} 小时）")
        print(f"强制下载 : 是（Content-Disposition: attachment）")
        print(f"\n预签名 URL：\n{url}\n")

    except ValueError as e:
        print(f"\n[错误] 配置问题：{e}", file=sys.stderr)
        print("请确保已设置以下环境变量：", file=sys.stderr)
        print("  COS_SECRET_ID  - 腾讯云 SecretId", file=sys.stderr)
        print("  COS_SECRET_KEY - 腾讯云 SecretKey", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"\n[错误] 生成预签名 URL 失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
