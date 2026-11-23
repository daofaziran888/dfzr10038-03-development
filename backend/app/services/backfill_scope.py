"""回溯范围服务：登记需要按日期对账的特征与日期区间，供缺口分区明细展开。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class BackfillScopeService(BaseModuleService):
    MODULE = "backfill_scope"
    ENTITY = "回溯范围"
    OPERATION_TERM = "对账"
    LIST_FIELDS = ["目标特征", "起始日期", "截止日期", "回溯模式", "缺口说明", "负责人", "登记时间"]
    REQUIRED_FIELDS = ["目标特征", "起始日期", "截止日期"]
    STATUS_ORDER = ["待对账", "对账中", "已对齐", "已归档"]
    ACTION_RULES = {"开始对账": "对账中", "确认对齐": "已对齐", "归档范围": "已归档"}
    NEGATIVE_ACTIONS = []
