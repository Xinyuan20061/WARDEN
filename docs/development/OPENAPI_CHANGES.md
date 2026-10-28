# v1 研究接口变更

基线 WARDEN 0.3.0，候选 0.4.0rc1。

| 项目 | 变更 |
|---|---|
| AuditRequest | 可选 research_protocol_ref、study_arm_ref；须同时提供 |
| POST audit-plans | 使用研究引用时要求 Bearer 操作者令牌；未知注册项生成 blocked 计划 |
| POST runs | 研究计划同样要求令牌；持久队列正文冲突返回 409 |
| GET artifacts/{artifact_id}/content | 新增，要求令牌、服务端 reader 和已审批公共摘要 |
| 计划/任务/资源/能力响应 | 采用受限公共投影，不再返回 truth、任意 metadata、uri 或原始诊断 |
| 旧请求 | 原字段和路径保留，不提供研究引用时仍可使用原同步演示 |

公开响应的字段收紧是显式的数据访问边界变化。依赖旧响应中本地 URI 或秘密 truth 的
客户端必须改用审批工件 ID，或在可信后端使用 Python 领域对象。
成功响应仍是原 plan/run 结构的公共子集。原始诊断和细粒度 phase 保留于可信 worker 域。
该版本未发布可接受任意执行参数的 research job 路由。
