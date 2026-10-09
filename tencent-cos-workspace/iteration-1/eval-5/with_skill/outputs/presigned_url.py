"""
生成腾讯云 COS 文件的预签名下载 URL。

功能：
- 从环境变量 / .env 文件读取密钥和配置
- 为指定文件生成预签名下载链接
- 链接有效期 2 小时（7200 秒）
- 通过 Content-Disposition 强制浏览器下载（而非预览）
"""

import os
from qcloud_cos import CosConfig, CosS3Client
from qcloud_cos import CosServiceError, CosClientError
from dotenv import load_dotenv


def init_cos_client() -> CosS3Client:
    """初始化 COS 客户端。

    按优先级从以下来源读取配置：
    1. 项目根目录的 .env 文件
    2. 系统环境变量

    Returns:
        CosS3Client: 已配置的 COS 客户端实例

    Raises:
        RuntimeError: 当密钥未配置时抛出
    """
    load_dotenv()

    secret_id = os.getenv("TENCENT_SECRET_ID")
    secret_key = os.getenv("TENCENT_SECRET_KEY")
    region = os.getenv("TENCENT_COS_REGION", "ap-beijing")

    if not secret_id or not secret_key:
        raise RuntimeError(
            "COS 密钥未配置。请在 .env 文件中设置 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY，"
            "或将其设为系统环境变量。"
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


def get_presigned_download_url(
    client: CosS3Client,
    bucket: str,
    key: str,
    expired: int = 7200,
    force_download: bool = True,
    download_filename: str | None = None,
) -> str:
    """生成 COS 文件的预签名下载 URL。

    Args:
        client: 已初始化的 COS 客户端实例
        bucket: 存储桶名称（含 APPID，如 my-bucket-1250000000）
        key: COS 上的文件路径（如 private/reports/audit-2026.pdf）
        expired: 链接有效期，单位秒，默认 7200（2 小时）
        force_download: 是否强制浏览器下载（而非预览），默认 True
        download_filename: 下载时的文件名，若为 None 则使用原始文件名

    Returns:
        str: 预签名下载 URL

    Raises:
        CosClientError: 客户端错误（如网络超时）
        CosServiceError: 服务端错误（如权限不足、文件不存在）
    """
    params: dict[str, str] = {}

    if force_download:
        # 设置 Content-Disposition 为 attachment，强制浏览器下载
        filename = download_filename or os.path.basename(key)
        params["response-content-disposition"] = (
            f"attachment; filename=\"{filename}\""
        )

    try:
        presigned_url = client.get_presigned_download_url(
            Bucket=bucket,
            Key=key,
            Expired=expired,
            Params=params if params else None,
        )
        return presigned_url
    except CosServiceError as e:
        print(f"[服务错误] 错误码: {e.get_error_code()}")
        print(f"[服务错误] 错误信息: {e.get_error_msg()}")
        print(f"[服务错误] HTTP 状态码: {e.get_status_code()}")
        print(f"[服务错误] Request ID: {e.get_request_id()}")
        raise
    except CosClientError as e:
        print(f"[客户端错误] {e}")
        raise


def main() -> None:
    """主函数：生成预签名下载 URL 并打印。"""
    # 初始化客户端
    try:
        client = init_cos_client()
    except RuntimeError as e:
        print(f"初始化失败: {e}")
        return

    # 目标文件配置
    BUCKET = "my-bucket-1250000000"
    KEY = "private/reports/audit-2026.pdf"
    EXPIRED = 7200  # 2 小时

    print(f"存储桶: {BUCKET}")
    print(f"文件路径: {KEY}")
    print(f"有效期: {EXPIRED} 秒（{EXPIRED // 3600} 小时）")
    print(f"强制下载: 是")
    print()

    # 生成预签名下载 URL
    try:
        presigned_url = get_presigned_download_url(
            client=client,
            bucket=BUCKET,
            key=KEY,
            expired=EXPIRED,
            force_download=True,
            download_filename="audit-2026.pdf",
        )
        print("预签名下载 URL 生成成功！")
        print(f"URL: {presigned_url}")
    except (CosServiceError, CosClientError) as e:
        print(f"生成预签名 URL 失败: {e}")


if __name__ == "__main__":
    main()
