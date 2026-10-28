# Gate 2：研究任务与公开接口

实现：SQLiteRunDispatcher 复用原 RunDispatcher，计划与任务可跨进程恢复；
request_id 与规范正文幂等，冲突映射 409；单数据库单 running 任务；
中断任务显式对账为 failed + phase=ambiguous，禁止自动重放副作用。

CallableAuditStage 包装既有白盒 collect/train；服务端注册协议/arm 引用映射。
研究请求新增字段可选，旧客户端不必提供。未知协议返回 blocked。
研究写操作有令牌验证；原 GET health 仍只表示服务存活。

公开投影隐藏真值、任意 metadata、工件 URI 和原始诊断；Python 可信域保留全信息。
工件网关仅暴露审批的 public-summary，拒绝任意路径、URI 与损坏哈希。

工程合同测试：并发 12 次同请求仅一任务；跨 Python 子进程恢复；
模拟进程中断不重放；研究 POST 缺授权拒绝；公共投影 canary 不泄漏。

部署验收：PARTIAL。尚未建立带硬 GPU/磁盘配额、强制超时和取消安全点的独立
生产 worker。run_next 是明确的本地/单实例消费入口，不承诺多副本 exactly-once。
研究配置由可信组合根注入，默认 REST 服务不加载模型。
