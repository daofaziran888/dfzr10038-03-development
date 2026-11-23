"""特征回溯任务服务：任务按区间写入日期分区，同一特征+日期只允许一份活动任务。"""
from __future__ import annotations

from typing import Any

from app.services.backfill_gap import CLAIM_LOCK, active_job, days_between
from app.services.base import BaseModuleService
from app.store import store


class BackfillJobService(BaseModuleService):
    MODULE = "backfill_job"
    ENTITY = "回溯任务"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["任务编号", "目标特征", "起始日期", "截止日期", "回溯模式", "并行度", "当前进度", "数据行数"]
    REQUIRED_FIELDS = ["任务编号", "目标特征", "起始日期"]
    STATUS_ORDER = ["待执行", "回溯中", "已完成", "部分缺失"]
    ACTION_RULES = {"启动回溯": "回溯中", "暂停回溯": "已完成", "标记缺失": "部分缺失"}
    NEGATIVE_ACTIONS = []

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        with CLAIM_LOCK:
            return self._create_locked(values)

    def _create_locked(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing, ""
        feature = str(values.get("目标特征", "")).strip()
        start = values.get("起始日期")
        end = values.get("截止日期") or start
        days = days_between(start, end)
        if not days:
            return None, ["起始日期", "截止日期"], ""
        holders = sorted({
            str(job.get("任务编号", ""))
            for day in days
            if (job := active_job(feature, day)) is not None
        })
        if holders:
            # 同一特征+日期已有一份活动任务，不能登记第二份。
            return None, [], (
                f"特征 {feature} 的日期 {'、'.join(days)} 已被任务 "
                f"{'、'.join(holders)} 占用，同一特征同一日期只允许一份活动任务"
            )
        entry, missing, conflict = super().create_entry({**values, "截止日期": days[-1]})
        return entry, missing, conflict

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        with CLAIM_LOCK:
            return self._run_locked(entry_id, action)

    def _run_locked(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action == "启动回溯" and entry.get("status") != "回溯中":
            feature = str(entry.get("目标特征", ""))
            days = days_between(entry.get("起始日期"), entry.get("截止日期") or entry.get("起始日期"))
            blocked = [
                day for day in days
                if (other := active_job(feature, day)) is not None
                and int(other.get("id", 0)) != entry_id
            ]
            if blocked:
                holders = "、".join(sorted({
                    str(active_job(feature, day).get("任务编号", ""))
                    for day in blocked
                }))
                return None, (
                    f"日期 {'、'.join(blocked)} 已被任务 {holders} 占用，"
                    "同一特征同一日期只允许一份任务处理"
                )
        return super().run_action(entry_id, action)
