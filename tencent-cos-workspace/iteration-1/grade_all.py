#!/usr/bin/env python3
"""自动评分脚本 — 对 with_skill 和 without_skill 输出进行断言检查。"""

from __future__ import annotations

import json
import re
from pathlib import Path

WORKSPACE = Path(__file__).parent


def read_code(path: Path) -> str:
    """读取生成的 Python 代码文件。"""
    py_files = list(path.glob("*.py"))
    if not py_files:
        return ""
    return py_files[0].read_text(encoding="utf-8")


def check_assertion(code: str, assertion_id: str) -> tuple[bool, str]:
    """检查单个断言是否通过。返回 (passed, evidence)。"""
    c = code

    # ---- Eval 1: Upload ----
    if assertion_id == "has-upload-call":
        ok = "put_object_from_local_file" in c or "put_object(" in c
        return ok, f"找到上传方法调用" if ok else "未找到 put_object_from_local_file 或 put_object 调用"

    if assertion_id == "correct-bucket":
        ok = "my-data-1250000000" in c
        return ok, f"Bucket 名称正确" if ok else "未找到正确的 Bucket 名称"

    if assertion_id == "correct-key":
        ok = "reports/" in c and "xlsx" in c
        return ok, f"Key 路径包含 reports/ 目录" if ok else "Key 路径不正确"

    if assertion_id == "content-type-set":
        ok = re.search(r'ContentType.*openxmlformats', c, re.IGNORECASE) is not None
        return ok, f"设置了正确的 ContentType" if ok else "未设置 .xlsx 的 ContentType"

    if assertion_id == "md5-enabled":
        ok = "EnableMD5" in c and ("True" in c or "true" in c)
        return ok, f"开启了 MD5 校验" if ok else "未开启 EnableMD5"

    if assertion_id == "client-init":
        ok = "CosConfig" in c and "CosS3Client" in c
        return ok, f"包含客户端初始化" if ok else "缺少 CosConfig 或 CosS3Client"

    if assertion_id == "env-config":
        ok = ("getenv" in c or "environ" in c or "load_dotenv" in c or ".env" in c)
        return ok, f"从环境变量读取配置" if ok else "未从环境变量读取密钥"

    if assertion_id == "error-handling":
        ok = ("try" in c and "except" in c) or "CosServiceError" in c or "CosClientError" in c
        return ok, f"包含错误处理" if ok else "缺少错误处理"

    # ---- Eval 2: Download ----
    if assertion_id == "has-head-object":
        ok = "head_object" in c
        return ok, f"使用 head_object 检查文件" if ok else "未使用 head_object"

    if assertion_id == "size-check-logic":
        ok = "Content-Length" in c or "ContentLength" in c
        return ok, f"检查文件大小" if ok else "未检查 Content-Length"

    if assertion_id == "range-download":
        ok = "Range" in c
        return ok, f"使用 Range 参数" if ok else "未使用 Range 范围下载"

    if assertion_id == "correct-range-bytes":
        ok = "536870911" in c or "524288000" in c or "512" in c
        return ok, f"包含 512MB 范围" if ok else "Range 范围不正确"

    if assertion_id == "save-to-file":
        ok = "get_stream_to_file" in c or "stream_to_file" in c
        return ok, f"保存到本地文件" if ok else "未使用 get_stream_to_file"

    if assertion_id == "correct-downloads-dir":
        ok = "downloads" in c.lower()
        return ok, f"保存到 downloads 目录" if ok else "未保存到 downloads 目录"

    # ---- Eval 3: List Objects ----
    if assertion_id == "has-list-objects":
        ok = "list_objects" in c
        return ok, f"包含 list_objects 调用" if ok else "未找到 list_objects"

    if assertion_id == "prefix-filter":
        ok = "images/" in c and "Prefix" in c
        return ok, f"使用 Prefix 过滤" if ok else "未设置 Prefix='images/'"

    if assertion_id == "pagination-loop":
        ok = ("while" in c and "Marker" in c) or ("while" in c and "marker" in c.lower())
        return ok, f"包含分页循环" if ok else "缺少 while + Marker 分页循环"

    if assertion_id == "is-truncated-check":
        ok = "IsTruncated" in c
        return ok, f"检查 IsTruncated" if ok else "未检查 IsTruncated"

    if assertion_id == "prints-key-size":
        ok = ("Key" in c or "key" in c.lower()) and ("Size" in c or "size" in c.lower()) and "print" in c
        return ok, f"打印 Key 和 Size" if ok else "未打印 Key 和 Size"

    if assertion_id == "correct-bucket":
        ok = "media-assets-1250000000" in c
        return ok, f"Bucket 名称正确" if ok else "未找到正确的 Bucket 名称"

    if assertion_id == "wrapped-in-function":
        ok = "def " in c
        return ok, f"代码包装在函数中" if ok else "代码未包装在函数中"

    # ---- Eval 4: Create Bucket ----
    if assertion_id == "has-create-bucket":
        ok = "create_bucket" in c
        return ok, f"包含 create_bucket 调用" if ok else "未找到 create_bucket"

    if assertion_id == "correct-bucket-name":
        ok = "my-app-static-1250000000" in c
        return ok, f"Bucket 名称正确" if ok else "未找到正确的 Bucket 名称"

    if assertion_id == "acl-public-read":
        ok = "public-read" in c
        return ok, f"设置了 public-read ACL" if ok else "未设置 public-read"

    if assertion_id == "has-head-bucket":
        ok = "head_bucket" in c
        return ok, f"包含 head_bucket 验证" if ok else "未使用 head_bucket 验证"

    if assertion_id == "create-then-verify":
        ok = "create_bucket" in c and "head_bucket" in c
        return ok, f"创建 + 验证逻辑完整" if ok else "缺少创建或验证步骤"

    # ---- Eval 5: Presigned URL ----
    if assertion_id == "has-presigned-call":
        ok = "get_presigned" in c or "presigned" in c.lower()
        return ok, f"包含预签名 URL 调用" if ok else "未找到预签名 URL 方法"

    if assertion_id == "correct-expiry":
        ok = "7200" in c
        return ok, f"有效期 7200 秒" if ok else "有效期不是 7200"

    if assertion_id == "force-download":
        ok = "content-disposition" in c.lower() or "attachment" in c
        return ok, f"设置强制下载" if ok else "未设置强制下载参数"

    if assertion_id == "correct-bucket-key":
        ok = "my-bucket-1250000000" in c and "audit-2026.pdf" in c
        return ok, f"Bucket 和 Key 正确" if ok else "Bucket 或 Key 不正确"

    return False, f"未知断言: {assertion_id}"


def grade_eval(eval_dir: Path) -> None:
    """对单个 eval 目录（包含 with_skill 和 without_skill）进行评分。"""
    metadata_path = eval_dir / "eval_metadata.json"
    if not metadata_path.exists():
        print(f"  SKIP {eval_dir.name}: no eval_metadata.json")
        return

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assertions = metadata.get("assertions", [])

    for config in ["with_skill", "without_skill"]:
        outputs_dir = eval_dir / config / "outputs"
        code = read_code(outputs_dir)

        if not code:
            print(f"  WARN {eval_dir.name}/{config}: 找不到 .py 文件")

        results = []
        for assertion in assertions:
            aid = assertion["id"]
            passed, evidence = check_assertion(code, aid)
            results.append({
                "id": aid,
                "description": assertion["description"],
                "passed": passed,
                "evidence": evidence,
            })

        passed_count = sum(1 for r in results if r["passed"])
        total = len(results)

        grading = {
            "config": config,
            "total_assertions": total,
            "passed": passed_count,
            "failed": total - passed_count,
            "pass_rate": round(passed_count / total, 2) if total > 0 else 0,
            "expectations": [
                {"text": f"{r['id']}: {r['description']}", "passed": r["passed"], "evidence": r["evidence"]}
                for r in results
            ],
        }

        grading_path = eval_dir / config / "grading.json"
        grading_path.write_text(json.dumps(grading, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {config}: {passed_count}/{total} 通过 ({grading['pass_rate']:.0%})")


def main() -> None:
    print("=" * 60)
    print("  腾讯云 COS Skill 评估 — 自动评分")
    print("=" * 60)
    print()

    for i in range(1, 6):
        eval_dir = WORKSPACE / f"eval-{i}"
        print(f"Eval {i} ({eval_dir.name}):")
        grade_eval(eval_dir)
        print()

    print("评分完成！grading.json 已生成。")


if __name__ == "__main__":
    main()
