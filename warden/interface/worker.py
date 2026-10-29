"""独立单 Worker：只消费部署者配置的持久队列，不自动恢复歧义任务。"""

from __future__ import annotations

import json
import time

from warden.core.domain.models import to_primitive
from warden.infrastructure.execution.sqlite import SQLiteRunDispatcher


def consume(queue: SQLiteRunDispatcher, *, once: bool = False, poll_seconds: float = 1) -> int:
    """消费任务并输出终态；once 无任务返回 0，任务失败返回 1。

    参数：queue 与 API 共享数据库；执行器和模型由组合根管理。
    中断不重放：队列中的 running 任务需要操作者先停止旧进程并对账。
    """
    if poll_seconds <= 0:
        raise ValueError("poll_seconds 必须为正数")
    if queue.executor is None:
        raise RuntimeError("Worker 未配置执行器；请设置 WARDEN_EXECUTION_CONFIG")
    while True:
        run = queue.run_next()
        if run is not None:
            print(json.dumps(to_primitive(run), ensure_ascii=False), flush=True)
        if once:
            return int(run is not None and run.status.value != "completed")
        if run is None:
            time.sleep(poll_seconds)
