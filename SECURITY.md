# Security Policy

WARDEN 的 Python Adapter 与科学方法默认作为可信同进程代码运行。接口隔离不能替代
操作系统级沙箱；不可信插件应在独立容器或受限进程中执行。

请勿提交模型密钥、`.env`、原始 activation、训练数据、Probe/SAE 权重或包含秘密载荷的
实验记录。安全问题请通过仓库的私密安全报告渠道提交。
