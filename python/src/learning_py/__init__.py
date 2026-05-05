"""learning-py: Python 学习项目入口包。"""

__version__ = "0.1.0"


def main() -> None:
    """`uv run learning-py` 的默认入口，打印一行问候用于验证环境。"""
    print(f"Hello from learning-py {__version__}!")


__all__ = ["main", "__version__"]
