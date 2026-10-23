# Contributing

1. 初始化公开 submodule：`git submodule update --init --recursive vendor/stegopot`。需要运行
   FRACTAL-Bench 集成测试时，再使用已授权账号初始化 `vendor/fractal-bench`。
2. 创建 Python 3.11+ 虚拟环境。
3. 安装开发依赖：`pip install -e ".[api,probe,dev]"`。
4. 按 `AGENTS.md` 保持依赖方向和科研完整性。
5. 提交前运行编译、测试、lint 和 wheel 构建。

公开接口变更应先修改 `schemas/` 与文档，并提供兼容性说明。权重和实验数据使用外部
Artifact 发布，只在仓库中提交清单、哈希和 Model Card。
