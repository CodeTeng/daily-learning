# 《AI大模型Ragent项目》——本地开发环境搭建

本文档将指导大家完成 Ragent 项目的环境搭建、代码克隆和基础配置，帮助你快速启动项目进行开发。

## 环境准备

### 1. IDE 安装

项目需要 IntelliJ IDEA 2023 及以上版本。

如果没有专业版，可以使用社区免费版。社区版在部分功能和插件支持上有所限制，但不影响项目的正常开发。

IDEA 下载地址：[https://www.jetbrains.com/zh-cn/idea](https://www.jetbrains.com/zh-cn/idea)

![无法获取该图片](https://oss.open8gu.com/image-20250626104253212.png)

点击下载按钮，并下载下方的社区免费版本。

![无法获取该图片](https://oss.open8gu.com/image-20250626104515776.png)

### 2. JDK 安装

Ragent 系统框架基于 SpringBoot3 开发，要求 JDK 版本不低于 17。请根据操作系统下载对应的 JDK17 版本。

- [Azul Zulu Windows](https://www.azul.com/downloads/?version=java-17-lts&os=windows&package=jdk#zulu)

- [Azul Zulu MacOS](https://www.azul.com/downloads/?version=java-17-lts&os=macos&package=jdk#zulu)

以 Windows 为例，大部分电脑为 x86 架构，选择第一个下载即可。

![无法获取该图片](https://oss.open8gu.com/image-20260302170109489.png)

## 项目克隆与配置

### 1. 克隆项目

打开 GitHub 项目地址：[https://github.com/nageoffer/ragent](https://github.com/nageoffer/ragent)，复制 SSH 克隆地址。

如果访问 GitHub 较慢，可使用 Gitee 镜像地址：[https://gitee.com/nageoffer/ragent](https://gitee.com/nageoffer/ragent)

建议使用 Git 克隆而非下载 ZIP 压缩包。通过 Git 克隆的项目可以方便地拉取远程仓库的最新代码，Ragent 后续会持续更新迭代。

![无法获取该图片](https://oss.open8gu.com/image-20260302171058002.png)

打开 IntelliJ IDEA，在菜单栏找到 Git -> Clone 选项（不同操作系统位置可能略有差异）。

![无法获取该图片](https://oss.open8gu.com/image-20260302171546005.png)

在 URL 文本框中填写 Ragent 的 SSH 地址（如：`git@github.com:nageoffer/ragent.git`），Directory 填写项目在本地的存储路径。

![无法获取该图片](https://oss.open8gu.com/image-20260302171401109.png)

等待项目克隆及 Maven 依赖初始化完成。

### 2. 配置 Maven 环境

可以先使用 IDEA 默认的 Maven 编译项目，如果编译成功则无需额外配置。如果编译失败，请尝试更换 Maven 版本。

Maven 版本过低（3.6.x）或过高（3.9.3 及以上）可能导致与 IDEA 的兼容性问题，引发项目编译错误。

![无法获取该图片](https://oss.open8gu.com/image-20250626104122700.png)

### 3. 配置 JDK17

项目克隆成功后，在 IDEA 中打开 `Project Structure...` 配置，检查 JDK 版本。

![无法获取该图片](https://oss.open8gu.com/image-20250626105525126.png)

确认 JDK 版本为 17，否则会导致项目编译失败或 Maven 打包异常。

![无法获取该图片](https://oss.open8gu.com/image-20260302171950302.png)

配置完成后，点击项目右侧的 Maven 图标进行编译测试。如果 Maven 打包成功，说明环境配置正确，可以开始项目开发。

![无法获取该图片](https://oss.open8gu.com/image-20260302172334560.png)

## 项目更新

项目后续可能会持续迭代和修复问题，建议在每次开始开发前，先拉取最新代码。

![无法获取该图片](https://oss.open8gu.com/image-20260302171827213.png)

至此，项目的克隆和基础配置已完成。如果在配置过程中遇到问题，可以检查 JDK 和 Maven 版本是否符合要求，或参考项目的 README 文档获取更多帮助。

> Source: https://t.zsxq.com/YllVK
> Resolved: https://articles.zsxq.com/id_j2ark054epm1.html
