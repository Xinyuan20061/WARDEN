"""SQLite 持久单 worker 调度适配器；提交不执行模型。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from warden.core.domain.enums import RunStatus
from warden.core.domain.models import AuditPlan, AuditRun, to_primitive, utc_now
from warden.core.ports.runs import AuditExecutor
from warden.infrastructure.execution.serialization import restore_plan, restore_run


class IdempotencyConflict(ValueError):
    """同一请求标识对应不同规范请求正文。"""


class SQLiteRunDispatcher:
    """复用 RunDispatcher 的持久队列。

    参数：
        database: SQLite 文件；保存受限计划真值，禁止对外下载数据库。
        executor: 原 AuditExecutor；只有显式 run_next 才会调用。

    资源所有权：
        每次操作关闭数据库连接；不关闭注入执行器或模型。
        单数据库只允许一个运行中任务。崩溃后的任务须人工对账，不自动重试。
    """

    def __init__(self, database: Path, executor: AuditExecutor) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    digest TEXT NOT NULL, plan_id TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        """为单次事务创建连接，竞争时最多等待 30 秒。"""
        with closing(sqlite3.connect(self.database, timeout=30)) as connection:
            with connection:
                yield connection

    def save_plan(self, plan: AuditPlan) -> None:
        """原子保存 plan；已有标识内容不一致时拒绝覆盖。"""
        encoded = _encode(plan)
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO plans VALUES (?, ?)", (plan.plan_id, encoded))
            prior = connection.execute(
                "SELECT payload FROM plans WHERE id=?", (plan.plan_id,)
            ).fetchone()[0]
            if prior != encoded:
                raise ValueError("同一 plan_id 不允许覆盖")

    def get_plan(self, plan_id: str) -> AuditPlan | None:
        """返回持久计划，未知 plan_id 返回 None。"""
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM plans WHERE id=?", (plan_id,)).fetchone()
        return restore_plan(json.loads(row[0])) if row else None

    def list_plans(self) -> tuple[AuditPlan, ...]:
        """返回跨进程持久计划列表，不暴露数据库路径。"""
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM plans ORDER BY rowid").fetchall()
        return tuple(restore_plan(json.loads(row[0])) for row in rows)

    def submit(self, plan: AuditPlan) -> AuditRun:
        """幂等提交 plan，返回 planned 快照；同 key 异正文抛 IdempotencyConflict。"""
        if plan.status not in {RunStatus.PLANNED, RunStatus.BLOCKED}:
            raise ValueError("只能提交 planned 或 blocked 计划")
        digest = sha256(_encode({"request": to_primitive(plan.request),
                                  "contract": to_primitive(plan.threat_contract),
                                  "stages": list(plan.stages)}).encode()).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT digest, payload FROM runs WHERE request_id=?", (plan.request.request_id,)
            ).fetchone()
            if prior:
                if prior[0] != digest:
                    raise IdempotencyConflict("request_id 已绑定不同请求正文")
                return restore_run(json.loads(prior[1]))
            encoded_plan = _encode(plan)
            connection.execute("INSERT OR IGNORE INTO plans VALUES (?, ?)",
                               (plan.plan_id, encoded_plan))
            stored = connection.execute(
                "SELECT payload FROM plans WHERE id=?", (plan.plan_id,)
            ).fetchone()[0]
            if stored != encoded_plan:
                raise ValueError("同一 plan_id 不允许覆盖")
            run = AuditRun(f"run-{uuid4().hex}", plan.plan_id, plan.status,
                           blockers=plan.blockers,
                           metadata={"phase": "queued", "worker_mode": "explicit_single_worker"})
            connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                               (run.run_id, plan.request.request_id, digest, plan.plan_id,
                                run.status.value, _encode(run)))
        return run

    def persist_blocked(self, plan: AuditPlan) -> AuditRun:
        """幂等保存阻塞任务；重启后仍可查询，Worker 不消费 blocked。"""
        if plan.status is not RunStatus.BLOCKED:
            raise ValueError("计划不是 blocked")
        return self.submit(plan)

    def get(self, run_id: str) -> AuditRun | None:
        """返回跨进程可查询的快照，未知标识返回 None。"""
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return restore_run(json.loads(row[0])) if row else None

    def list(self) -> tuple[AuditRun, ...]:
        """按持久插入顺序返回任务。"""
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM runs ORDER BY rowid").fetchall()
        return tuple(restore_run(json.loads(row[0])) for row in rows)

    def run_next(self) -> AuditRun | None:
        """显式消费一个排队任务；已有 running 时不再消费，返回 None。

        异常：
            模型异常记录为 failed，进程崩溃则保留 running 等待对账。
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
                return None
            row = connection.execute(
                "SELECT payload FROM runs WHERE status='planned' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            queued = restore_run(json.loads(row[0]))
            running = replace(queued, status=RunStatus.RUNNING, updated_at=utc_now(),
                              metadata={"phase": "executing"})
            connection.execute("UPDATE runs SET status=?, payload=? WHERE id=?",
                               (running.status.value, _encode(running), running.run_id))
        try:
            plan = self.get_plan(running.plan_id)
            if plan is None:
                raise RuntimeError("队列缺少持久计划")
            evidence = self.executor.execute(plan, run_id=running.run_id)
            if (evidence.run_id != running.run_id or evidence.plan_id != running.plan_id
                    or evidence.status not in {RunStatus.COMPLETED, RunStatus.FAILED}):
                raise RuntimeError("执行器返回无效终态证据")
            terminal = replace(running, status=evidence.status, evidence=evidence,
                               error="执行失败，详见证据" if evidence.status is RunStatus.FAILED
                               else None, updated_at=utc_now(), metadata={"phase": "finished"})
        except Exception as exc:
            terminal = replace(running, status=RunStatus.FAILED,
                               error=f"{type(exc).__name__}: {exc}", updated_at=utc_now())
        with self._connect() as connection:
            connection.execute("UPDATE runs SET status=?, payload=? WHERE id=?",
                               (terminal.status.value, _encode(terminal), terminal.run_id))
        return terminal

    def reconcile_interrupted(self, run_id: str) -> AuditRun:
        """操作者确认 worker 已停止后标记歧义任务；不自动重新执行。

        参数：
            run_id: 已确认中断的 running 任务。

        返回：
            failed 快照，metadata.phase=ambiguous，提示副作用需人工核查。
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = restore_run(json.loads(row[0]))
            if run.status is not RunStatus.RUNNING:
                raise ValueError("只能对账 running 任务")
            terminal = replace(run, status=RunStatus.FAILED, updated_at=utc_now(),
                               error="执行已中断，副作用未知；禁止自动重放",
                               metadata={"phase": "ambiguous", "automatic_retry": False})
            connection.execute("UPDATE runs SET status=?, payload=? WHERE id=?",
                               (terminal.status.value, _encode(terminal), run_id))
        return terminal


def _encode(value: object) -> str:
    """生成规范 JSON；不允许 NaN。"""
    return json.dumps(to_primitive(value), ensure_ascii=False, sort_keys=True, allow_nan=False)
