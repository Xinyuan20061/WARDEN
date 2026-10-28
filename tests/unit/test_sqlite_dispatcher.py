"""幂等提交、跨进程恢复和并发领取约束。"""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from warden.core.domain.enums import RunStatus
from warden.core.domain.models import AuditPlan, AuditRequest, EvidenceBundle, ThreatContract
from warden.infrastructure.execution.sqlite import IdempotencyConflict, SQLiteRunDispatcher


def _plan():
    return AuditPlan(
        "plan-1", AuditRequest("req-1", "contract", "model", "runtime"),
        ThreatContract("contract", "scenario", ("receiver",), (), "harmful", "benign"),
        (), ("test",),
        created_at="2026-10-28T00:00:00+00:00",
    )


class _Executor:
    def execute(self, plan, *, run_id):
        return EvidenceBundle(run_id, plan.plan_id, RunStatus.COMPLETED)


def test_concurrent_replay_only_enqueues_once_and_body_conflict(tmp_path):
    path = tmp_path / "runs.sqlite"
    queue = SQLiteRunDispatcher(path, _Executor())
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(lambda _: queue.submit(_plan()), range(12)))
    assert len({item.run_id for item in runs}) == 1
    assert len(queue.list()) == 1
    with pytest.raises(IdempotencyConflict):
        queue.submit(replace(_plan(), request=replace(_plan().request, model_id="other")))
    terminal = queue.run_next()
    assert terminal.status is RunStatus.COMPLETED
    assert queue.run_next() is None
    assert SQLiteRunDispatcher(path, _Executor()).get(terminal.run_id) == terminal


def test_new_process_can_query_plan_and_queued_run(tmp_path):
    path = tmp_path / "restart.sqlite"
    run = SQLiteRunDispatcher(path, _Executor()).submit(_plan())
    code = (
        "from pathlib import Path; "
        "from warden.infrastructure.execution.sqlite import SQLiteRunDispatcher; "
        "import sys; q=SQLiteRunDispatcher(Path(sys.argv[1]),None); "
        "assert q.get(sys.argv[2]).status.value=='planned'; "
        "assert q.get_plan('plan-1').request.request_id=='req-1'"
    )
    result = subprocess.run([sys.executable, "-c", code, str(path), run.run_id], check=False)
    assert result.returncode == 0


def test_interrupted_side_effect_is_not_automatically_retried(tmp_path):
    class _Crash:
        def execute(self, plan, *, run_id):
            raise KeyboardInterrupt()

    path = tmp_path / "interrupted.sqlite"
    queue = SQLiteRunDispatcher(path, _Crash())
    run = queue.submit(_plan())
    with pytest.raises(KeyboardInterrupt):
        queue.run_next()
    restarted = SQLiteRunDispatcher(path, _Executor())
    assert restarted.run_next() is None
    assert restarted.get(run.run_id).status is RunStatus.RUNNING
    reconciled = restarted.reconcile_interrupted(run.run_id)
    assert reconciled.status is RunStatus.FAILED
    assert reconciled.metadata["phase"] == "ambiguous"
    assert restarted.submit(_plan()).run_id == run.run_id
