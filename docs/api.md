# Platform API Contract

## Collaboration Boundary

测试平台通过 REST API 或 `WardenClient` 使用内核。平台不得扫描 `artifacts/`、读取
Activation 文件或导入 `warden.infrastructure`。这样 WARDEN 可以独立修改模型后端和
科学方法，而不破坏页面。

## Audit Request

`POST /v1/audit-plans` 接受：

```json
{
  "request_id": "demo-001",
  "contract_id": "fractal-instance-id",
  "model_id": "Qwen/Qwen3-8B",
  "runtime_id": "local-whitebox",
  "mode": "causal_audit",
  "probe_id": "collusion-linear-v1",
  "sae_id": null,
  "capture_targets": [
    {
      "target_id": "receiver-resid-20",
      "agent_ids": ["receiver"],
      "layer": 20,
      "component": "resid_post",
      "token_policy": "last_token",
      "retain_gradient": true
    }
  ],
  "metadata": {}
}
```

创建计划不等于完成实验。返回值中的 `status` 可能为 `blocked`，`blockers` 会准确说明缺失
的 Runtime、Probe、SAE 或模型能力。

## Run Submission

`POST /v1/runs` 接受一个已登记计划：

```json
{"plan_id": "plan-..."}
```

部署层通过 `RunDispatcher` 选择同步、队列或分布式执行。默认开发服务不加载模型，
因此未注入调度器时会返回 `blocked` 任务，而不是伪造一个完成结果。

## Artifact Rule

API 中不返回原始张量，只返回 `ArtifactRef`：

```json
{
  "artifact_id": "activation-acde0123456789ab",
  "kind": "activation",
  "uri": "file:///...",
  "content_hash": "sha256...",
  "media_type": "application/vnd.pytorch.tensor",
  "size_bytes": 4096,
  "metadata": {}
}
```

生产部署应由受控下载端点替换本地 `file:` URI，领域契约不需要改变。

## Compatibility

- 主版本 `/v1` 内新增可选字段保持兼容。
- 删除字段、改变语义或收紧合法值需要新的 API 主版本。
- 前端应展示 `blocked` 和 `unavailable`，不能把它们折叠成阴性检测结果。
