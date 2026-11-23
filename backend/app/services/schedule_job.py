"""调度编排服务：回溯计划激活时读取缺口分区明细，按认领策略领取实际日期。"""
from __future__ import annotations

from typing import Any

from app.services import backfill_gap
from app.services.base import BaseModuleService
from app.store import store


class ScheduleJobService(BaseModuleService):
    MODULE = "schedule_job"
    ENTITY = "调度计划"
    OPERATION_TERM = "关联"
    LIST_FIELDS = [
        "计划编号", "任务类型", "关联对象", "起始日期", "截止日期", "认领策略",
        "Cron表达式", "时区设置", "依赖检查", "失败通知", "下次执行",
        "本次到手日期", "原有占用", "后续补办范围",
    ]
    REQUIRED_FIELDS = ["计划编号", "任务类型", "关联对象"]
    STATUS_ORDER = ["待激活", "执行中", "已完成", "已停用"]
    ACTION_RULES = {
        "激活计划": "执行中", "重新领取补办": "执行中",
        "立即执行": "已完成", "停用计划": "已停用",
    }
    NEGATIVE_ACTIONS = ["停用计划"]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        if backfill_gap.is_backfill_plan(entry):
            # 计划视图按缺口分区明细实时刷新，避免列出已经变化的占用日期。
            return {**entry, **backfill_gap.plan_view(entry)}
        return entry

    def list_entries(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        rows, total = super().list_entries(**kwargs)
        return [
            {**row, **backfill_gap.plan_view(row)}
            if backfill_gap.is_backfill_plan(row) else row
            for row in rows
        ], total

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if not backfill_gap.is_backfill_plan(entry):
            return super().run_action(entry_id, action)

        if action == "激活计划":
            result = backfill_gap.claim_plan(entry_id)
            return (entry if result["ok"] else None), str(result["message"])
        if action == "重新领取补办":
            result = backfill_gap.claim_plan(entry_id, supplement=True)
            return (entry if result["ok"] else None), str(result["message"])
        if action == "立即执行":
            result = backfill_gap.execute_plan(entry_id)
            return (entry if result["ok"] else None), str(result["message"])
        if action == "停用计划":
            result = backfill_gap.release_plan(entry_id)
            return (entry if result["ok"] else None), str(result["message"])
        return super().run_action(entry_id, action)
