# Python 子项目

`learning-py` 是 `learning` 仓库的 Python 部分，使用 [uv](https://docs.astral.sh/uv/) 进行环境与依赖管理。

## 目录结构

```
python/
├── README.md             # 本文件
├── pyproject.toml        # 项目元数据 + 依赖 + 工具配置
├── uv.lock               # uv 生成的精确锁文件（提交到 git）
├── .python-version       # 期望的 Python 版本
├── docs/                 # 知识笔记（与 src 中的示例相互对照）
│   ├── README.md
│   └── python-gil.md
├── src/
│   └── learning_py/      # 包源码
│       ├── __init__.py
│       └── concurrent/
│           └── gil_demo.py
└── tests/                # pytest 测试
    └── test_smoke.py
```

采用 src-layout，能避免「直接 import 当前目录」掩盖打包问题。

## 环境准备

确保已安装 uv（macOS 推荐 `brew install uv`），然后：

```bash
cd python
uv sync          # 创建 .venv 并安装运行 + dev 依赖
```

`uv sync` 会读取 `pyproject.toml` 与 `uv.lock`，在 `.venv/` 下生成虚拟环境，无需手动 `python -m venv`。

## 常用命令

| 目的 | 命令 |
| --- | --- |
| 运行包入口脚本 | `uv run learning-py` |
| 运行模块（示例：GIL 演示） | `uv run python -m learning_py.concurrent.gil_demo` |
| 跑测试 | `uv run pytest` |
| 代码检查 | `uv run ruff check .` |
| 添加运行时依赖 | `uv add <pkg>` |
| 添加开发依赖 | `uv add --dev <pkg>` |
| 更新锁文件 | `uv lock --upgrade` |

## 添加新主题的建议

1. 在 `docs/` 下新增一篇 `<topic>.md`，先讲清楚「是什么 / 为什么 / 怎么验证」。
2. 在 `src/learning_py/<area>/` 下放可运行示例，模块名与文档关键字保持一致。
3. 在 `tests/` 下加一个最小的冒烟测试，保证后续重构不会悄悄破坏示例。
4. 更新 `docs/README.md` 的目录索引。
