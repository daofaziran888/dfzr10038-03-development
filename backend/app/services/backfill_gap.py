"""缺口分区明细：按特征归并多份回溯任务，按日期核对未覆盖、处理中和已完成。

回溯任务只记录区间，调度员真正领取的是区间里的具体日期。本服务把同一特征下
多份任务区间展开到天，按“已完成 > 处理中 > 未覆盖”的优先级归并出每个日期的
覆盖情况，并提供计划激活、补办认领、执行与释放的日期级认领逻辑。

认领约束：
- 同一特征 + 同一日期同时只允许一份活动任务占用；认领过程加锁并在锁内二次检查。
- 只有显式执行完成的任务才算“已完成”，处理中的日期不会被提前显示成已完成。
- 已完成的日期从新增认领范围中排除，不会被重新计算。
"""
from __future__ import annotations

import datetime as dt
import re
import threading
from typing import Any

from app.store import store

UNCOVERED = "未覆盖"
PROCESSING = "处理中"
DONE = "已完成"
RELEASED = "已释放"

STRATEGY_PROGRESSIVE = "先跑未分配日期"
STRATEGY_ATOMIC = "等整段一起交付"
STRATEGIES = [STRATEGY_PROGRESSIVE, STRATEGY_ATOMIC]

BATCH_FIRST = "首次派工"
BATCH_SUPPLEMENT = "释放后补单"

SCOPE_MODULE = "backfill_scope"
PLAN_MODULE = "schedule_job"
JOB_MODULE = "backfill_job"
BACKFILL_TASK_TYPE = "特征回溯"

# 同步接口在线程池里并发执行，认领和占用检查必须串行并做二次检查。
CLAIM_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# 日期与通用格式化
# ---------------------------------------------------------------------------


def _parse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def days_between(start: Any, end: Any) -> list[str]:
    """展开闭区间日期；非法或倒置区间返回空列表。"""
    first, last = _parse_date(start), _parse_date(end)
    if first is None or last is None or last < first:
        return []
    return [(first + dt.timedelta(days=offset)).isoformat()
            for offset in range((last - first).days + 1)]


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _fmt_dates(dates: list[str]) -> str:
    return "、".join(dates) if dates else "无"


def _fmt_occupied(partitions: list[dict[str, Any]]) -> str:
    if not partitions:
        return "无"
    return "；".join(
        f"{item['分区日期']}（{item['任务来源']} / {item['来源计划']}）"
        for item in partitions
    )


# ---------------------------------------------------------------------------
# 回溯范围与任务归并
# ---------------------------------------------------------------------------


def _scope_for(feature: str) -> dict[str, Any] | None:
    for row in store.rows(SCOPE_MODULE):
        if str(row.get("目标特征", "")) == feature:
            return row
    return None


def _feature_jobs(feature: str) -> list[dict[str, Any]]:
    return [row for row in store.rows(JOB_MODULE)
            if str(row.get("目标特征", "")) == feature
            and row.get("status") != RELEASED]


def _covers(job: dict[str, Any], day: str) -> bool:
    return day in days_between(job.get("起始日期"), job.get("截止日期"))


def partitions_for(feature: str) -> list[dict[str, Any]]:
    """把同一特征的多份回溯任务按日期归并成缺口分区明细。"""
    scope = _scope_for(feature)
    if scope is None:
        return []
    scope_id = int(scope.get("id", 0) or 0)
    jobs = _feature_jobs(feature)
    rows: list[dict[str, Any]] = []
    for index, day in enumerate(
        days_between(scope.get("起始日期"), scope.get("截止日期")), start=1
    ):
        done = [job for job in jobs
                if job.get("status") == DONE and _covers(job, day)]
        processing = [job for job in jobs
                      if job.get("status") == "回溯中" and _covers(job, day)]
        if done:
            status, sources = DONE, done
        elif processing:
            status, sources = PROCESSING, processing
        else:
            status, sources = UNCOVERED, []
        source_jobs = "、".join(
            str(job.get("任务编号", "")) for job in sources) or "—"
        source_plans = "、".join(sorted({
            str(job.get("来源计划", ""))
            for job in sources if job.get("来源计划")
        })) or "—"
        batches = "、".join(sorted({
            str(job.get("认领批次", ""))
            for job in sources if job.get("认领批次")
        })) or "—"
        claimed_at = "、".join(sorted({
            str(job.get("认领时间", ""))
            for job in sources if job.get("认领时间")
        })) or "—"
        rows.append({
            "id": scope_id * 100 + index,
            "status": status,
            "pending": status != DONE,
            "abnormal": False,
            "缺口编号": f"GAP-{scope_id:02d}-{day[5:7]}{day[8:10]}",
            "目标特征": feature,
            "分区日期": day,
            "缺口状态": status,
            "任务来源": source_jobs,
            "来源计划": source_plans,
            "认领批次": batches,
            "认领时间": claimed_at,
            "覆盖任务数": len(done) + len(processing),
            "已完成任务数": len(done),
            "处理中任务数": len(processing),
        })
    return rows


def all_partitions(feature: str | None = None) -> list[dict[str, Any]]:
    if feature:
        return partitions_for(feature)
    rows: list[dict[str, Any]] = []
    for scope in store.rows(SCOPE_MODULE):
        rows.extend(partitions_for(str(scope.get("目标特征", ""))))
    return rows


def summary_of(partitions: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "合计": len(partitions),
        UNCOVERED: sum(1 for row in partitions if row["status"] == UNCOVERED),
        PROCESSING: sum(1 for row in partitions if row["status"] == PROCESSING),
        DONE: sum(1 for row in partitions if row["status"] == DONE),
    }


# ---------------------------------------------------------------------------
# 计划读取
# ---------------------------------------------------------------------------


def is_backfill_plan(plan: dict[str, Any]) -> bool:
    return str(plan.get("任务类型", "")) == BACKFILL_TASK_TYPE


def plan_jobs(plan_no: str) -> list[dict[str, Any]]:
    return [row for row in store.rows(JOB_MODULE)
            if str(row.get("来源计划", "")) == plan_no]


def _plan_range(plan: dict[str, Any]) -> tuple[str, list[str]]:
    feature = str(plan.get("关联对象", ""))
    start = plan.get("起始日期")
    end = plan.get("截止日期")
    scope = _scope_for(feature)
    if (not start or not end) and scope is not None:
        start, end = scope.get("起始日期"), scope.get("截止日期")
    days = days_between(start, end)
    if scope is not None:
        allowed = set(days_between(scope.get("起始日期"), scope.get("截止日期")))
        days = [day for day in days if day in allowed]
    return feature, days


def _plan_done_dates(plan_no: str) -> list[str]:
    days: set[str] = set()
    for job in plan_jobs(plan_no):
        if job.get("status") == DONE:
            days.update(days_between(job.get("起始日期"), job.get("截止日期")))
    return sorted(days)


def _plan_covered_dates(plan_no: str) -> list[str]:
    days: set[str] = set()
    for job in plan_jobs(plan_no):
        if job.get("status") in (DONE, "回溯中"):
            days.update(days_between(job.get("起始日期"), job.get("截止日期")))
    return sorted(days)


def plan_view(plan: dict[str, Any]) -> dict[str, Any]:
    covered = _plan_covered_dates(str(plan.get("计划编号", "")))
    return {
        "id": int(plan.get("id", 0) or 0),
        "计划编号": plan.get("计划编号", ""),
        "任务类型": plan.get("任务类型", ""),
        "关联对象": plan.get("关联对象", ""),
        "起始日期": plan.get("起始日期", ""),
        "截止日期": plan.get("截止日期", ""),
        "认领策略": plan.get("认领策略", STRATEGY_PROGRESSIVE),
        "status": plan.get("status", ""),
        "pending": bool(plan.get("pending")),
        "本次到手日期": plan.get("本次到手日期", "无"),
        "原有占用": plan.get("原有占用", "无"),
        "后续补办范围": plan.get("后续补办范围", "无"),
        "当前批次": plan.get("当前批次", ""),
        "认领历史": list(plan.get("认领历史") or []),
        "累计覆盖日期": covered,
        "累计覆盖数": len(covered),
        "已完成日期": _plan_done_dates(str(plan.get("计划编号", ""))),
        "上次操作时间": plan.get("上次操作时间", ""),
    }


# ---------------------------------------------------------------------------
# 认领
# ---------------------------------------------------------------------------


def active_job(feature: str, day: str) -> dict[str, Any] | None:
    """同一特征+日期是否已有活动占用；锁内二次检查用。"""
    for job in _feature_jobs(feature):
        if job.get("status") in (DONE, "回溯中") and _covers(job, day):
            return job
    return None


def _next_task_no() -> str:
    highest = 0
    for job in store.rows(JOB_MODULE):
        match = re.match(r"BACK-(\d+)$", str(job.get("任务编号", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"BACK-{highest + 1:04d}"


def _create_claim_job(
    plan: dict[str, Any],
    feature: str,
    day: str,
    batch: str,
    partition: dict[str, Any],
) -> dict[str, Any]:
    rows = store.rows(JOB_MODULE)
    job = {
        "id": max((int(row.get("id", 0) or 0) for row in rows), default=0) + 1,
        "status": "回溯中",
        "pending": True,
        "abnormal": False,
        "任务编号": _next_task_no(),
        "目标特征": feature,
        "起始日期": day,
        "截止日期": day,
        "回溯模式": "缺口补算",
        "并行度": "单分区",
        "当前进度": "0%",
        "数据行数": "—",
        "缺口编号": partition.get("缺口编号", ""),
        "来源计划": plan.get("计划编号", ""),
        "认领批次": batch,
        "认领时间": _now(),
    }
    rows.append(job)
    return job


def _plan_batch(plan: dict[str, Any]) -> str:
    return BATCH_FIRST if not plan.get("认领历史") else BATCH_SUPPLEMENT


def claim_plan(plan_id: int, *, supplement: bool = False) -> dict[str, Any]:
    """按计划策略从缺口分区明细领取实际日期。

    - 先跑未分配日期：立刻领取所有未覆盖日期，被其他计划占用的日期进入补办范围。
    - 等整段一起交付：只要区间内还有他人占用，就整段等待，不领零散日期。
    """
    with CLAIM_LOCK:
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return {"ok": False, "message": f"调度计划 {plan_id} 不存在或已归档", "plan": None}
        if not is_backfill_plan(plan):
            return {"ok": False, "message": "该计划不是特征回溯计划，无法读取缺口分区明细",
                    "plan": plan_view(plan)}

        plan_no = str(plan.get("计划编号", ""))
        if plan.get("status") == "已完成":
            return {"ok": False, "message": f"计划 {plan_no} 已全部交付，无需重新认领",
                    "plan": plan_view(plan)}
        if not supplement and plan.get("status") == "执行中":
            return {"ok": False,
                    "message": f"计划 {plan_no} 已在执行中；如需领取补办日期请用「重新领取补办」",
                    "plan": plan_view(plan)}
        feature, plan_days = _plan_range(plan)
        partition_days = set(plan_days)
        partitions = [row for row in partitions_for(feature)
                      if row["分区日期"] in partition_days]
        if not partitions:
            return {"ok": False, "message": f"特征 {feature} 没有可对账的缺口分区",
                    "plan": plan_view(plan)}

        own_held = [row for row in partitions
                    if row["status"] == PROCESSING and plan_no in str(row["来源计划"])]
        occupied = [row for row in partitions
                    if row["status"] == PROCESSING and plan_no not in str(row["来源计划"])]
        completed = [row for row in partitions if row["status"] == DONE]
        uncovered = [row for row in partitions if row["status"] == UNCOVERED]

        strategy = str(plan.get("认领策略") or STRATEGY_PROGRESSIVE)
        batch = _plan_batch(plan)
        acquired: list[str] = []
        if strategy == STRATEGY_ATOMIC and occupied:
            # 等整段一起交付：不抢占零散日期，等占用释放后整段领取。
            pending_days = sorted(
                {row["分区日期"] for row in partitions if row["status"] != DONE}
                - {row["分区日期"] for row in own_held}
            )
        else:
            blocked_days: list[str] = []
            for row in uncovered:
                day = row["分区日期"]
                if active_job(feature, day) is not None:
                    # 并发下另一个计划已抢先写入，跳过，等待补办。
                    blocked_days.append(day)
                    continue
                _create_claim_job(plan, feature, day, batch, row)
                acquired.append(day)
            pending_days = sorted([row["分区日期"] for row in occupied] + blocked_days)
            if strategy == STRATEGY_ATOMIC:
                # 整段交付要求一次领齐，领不齐就整段退回，不留下半段任务。
                if pending_days:
                    for job in plan_jobs(plan_no):
                        if job.get("status") == "回溯中":
                            job["status"] = RELEASED
                            job["pending"] = False
                            job["释放时间"] = _now()
                    acquired = []
                    pending_days = sorted(
                        {row["分区日期"] for row in partitions if row["status"] != DONE})

        plan["status"] = "执行中"
        plan["pending"] = True
        plan["当前批次"] = batch
        plan["本次到手日期"] = _fmt_dates(acquired)
        plan["原有占用"] = _fmt_occupied(occupied)
        plan["后续补办范围"] = _fmt_dates(pending_days)
        plan["累计覆盖日期"] = _plan_covered_dates(plan_no)
        plan["已完成日期"] = _plan_done_dates(plan_no)
        plan["上次操作时间"] = _now()

        history = list(plan.get("认领历史") or [])
        if acquired:
            history.append({"批次": batch, "日期": acquired, "时间": _now()})
            plan["认领历史"] = history

        if strategy == STRATEGY_ATOMIC and (occupied or not acquired):
            blocked = occupied or [
                {"分区日期": day, "任务来源": "—", "来源计划": "整段未领齐"}
                for day in pending_days
            ]
            message = (
                f"计划 {plan_no} 采用「{strategy}」，区间内仍有 {len(blocked)} 个日期未齐，"
                f"本次不领零散日期；原有占用 {_fmt_occupied(occupied)}；"
                f"后续补办范围 {_fmt_dates(pending_days)}"
            )
        else:
            remaining = sorted(set(pending_days) - set(acquired)) if acquired else pending_days
            if acquired and not remaining:
                next_step = "整段已领齐"
            else:
                next_step = f"后续补办范围 {_fmt_dates(remaining)}"
            message = (
                f"计划 {plan_no} {batch}：本次到手 {_fmt_dates(acquired)}；"
                f"原有占用 {_fmt_occupied(occupied)}；{next_step}"
            )

        result = {
            "ok": True,
            "message": message,
            "action": "reclaim" if supplement else "activate",
            "batch": batch,
            "plan": plan_view(plan),
            "feature": feature,
            "strategy": strategy,
            "acquired": acquired,
            "held": [row["分区日期"] for row in own_held],
            "occupied": [
                {"date": row["分区日期"], "source": row["任务来源"],
                 "plan": row["来源计划"]}
                for row in occupied
            ],
            "pending": pending_days,
            "completed": [row["分区日期"] for row in completed],
        }
        plan["last_claim"] = result
        return result


def execute_plan(plan_id: int) -> dict[str, Any]:
    """执行本计划已领取的日期：只把本计划处理中的任务显式完成。"""
    with CLAIM_LOCK:
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return {"ok": False, "message": f"调度计划 {plan_id} 不存在或已归档", "plan": None}
        if not is_backfill_plan(plan):
            return {"ok": False, "message": "该计划不是特征回溯计划", "plan": plan_view(plan)}

        plan_no = str(plan.get("计划编号", ""))
        executed: list[str] = []
        for job in plan_jobs(plan_no):
            if job.get("status") != "回溯中":
                continue
            day = str(job.get("起始日期", ""))
            job["status"] = DONE
            job["pending"] = False
            job["abnormal"] = False
            job["当前进度"] = "100%"
            job["数据行数"] = f"{12000 + int(job.get('id', 0) or 0) * 7}行"
            job["完成时间"] = _now()
            executed.append(day)

        feature, plan_days = _plan_range(plan)
        partition_days = set(plan_days)
        partitions = [row for row in partitions_for(feature)
                      if row["分区日期"] in partition_days]
        pending = [row["分区日期"] for row in partitions
                   if row["status"] == PROCESSING]
        plan["本次执行日期"] = _fmt_dates(sorted(executed))
        plan["后续补办范围"] = _fmt_dates(pending)
        plan["累计覆盖日期"] = _plan_covered_dates(plan_no)
        plan["已完成日期"] = _plan_done_dates(plan_no)
        plan["上次操作时间"] = _now()

        all_done = bool(partitions) and all(
            row["status"] == DONE for row in partitions)
        if all_done:
            plan["status"] = "已完成"
            plan["pending"] = False
        else:
            plan["status"] = "执行中"
            plan["pending"] = True

        message = (
            f"计划 {plan_no} 已执行本次分配：{_fmt_dates(sorted(executed))}；"
            f"后续补办范围 {_fmt_dates(pending)}"
        )
        result = {
            "ok": True,
            "message": message,
            "action": "execute",
            "plan": plan_view(plan),
            "feature": feature,
            "executed": sorted(executed),
            "pending": pending,
            "completed": [row["分区日期"] for row in partitions
                          if row["status"] == DONE],
        }
        return result


def release_plan(plan_id: int) -> dict[str, Any]:
    """释放计划占用：处理中的任务转为已释放，日期回到未覆盖供其他计划补办。"""
    with CLAIM_LOCK:
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return {"ok": False, "message": f"调度计划 {plan_id} 不存在或已归档", "plan": None}
        if not is_backfill_plan(plan):
            return {"ok": False, "message": "该计划不是特征回溯计划", "plan": plan_view(plan)}

        plan_no = str(plan.get("计划编号", ""))
        released: list[str] = []
        for job in plan_jobs(plan_no):
            if job.get("status") != "回溯中":
                continue
            job["status"] = RELEASED
            job["pending"] = False
            job["释放时间"] = _now()
            released.append(str(job.get("起始日期", "")))

        plan["status"] = "已停用"
        plan["pending"] = False
        plan["本次释放日期"] = _fmt_dates(sorted(released))
        plan["后续补办范围"] = "无" if not released else _fmt_dates(sorted(released))
        plan["上次操作时间"] = _now()
        message = f"计划 {plan_no} 已释放占用：{_fmt_dates(sorted(released))}"
        return {
            "ok": True,
            "message": message,
            "action": "release",
            "plan": plan_view(plan),
            "feature": str(plan.get("关联对象", "")),
            "released": sorted(released),
        }


def set_strategy(plan_id: int, strategy: str) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        return {"ok": False, "message": f"未知认领策略：{strategy}"}
    with CLAIM_LOCK:
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return {"ok": False, "message": f"调度计划 {plan_id} 不存在或已归档"}
        if not is_backfill_plan(plan):
            return {"ok": False, "message": "该计划不是特征回溯计划"}
        if plan.get("status") != "待激活":
            return {"ok": False, "message": "计划已激活，不能再切换认领策略"}
        plan["认领策略"] = strategy
        plan["上次操作时间"] = _now()
        return {
            "ok": True,
            "message": f"计划 {plan.get('计划编号', '')} 认领策略已切换为「{strategy}」",
            "plan": plan_view(plan),
        }


def preview_plan(plan_id: int) -> dict[str, Any]:
    """值班员激活前预览：本次能拿到哪些日期、哪些被占用、剩下要补办什么。"""
    with CLAIM_LOCK:
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return {"ok": False, "message": f"调度计划 {plan_id} 不存在或已归档", "plan": None}
        if not is_backfill_plan(plan):
            return {"ok": False, "message": "该计划不是特征回溯计划", "plan": plan_view(plan)}
        feature, plan_days = _plan_range(plan)
        partition_days = set(plan_days)
        partitions = [row for row in partitions_for(feature)
                      if row["分区日期"] in partition_days]
        plan_no = str(plan.get("计划编号", ""))
        strategy = str(plan.get("认领策略") or STRATEGY_PROGRESSIVE)
        completed = [row["分区日期"] for row in partitions if row["status"] == DONE]
        occupied = [row for row in partitions
                    if row["status"] == PROCESSING and plan_no not in str(row["来源计划"])]
        held = [row["分区日期"] for row in partitions
                if row["status"] == PROCESSING and plan_no in str(row["来源计划"])]
        uncovered = [row["分区日期"] for row in partitions if row["status"] == UNCOVERED]
        will_acquire: list[str] = []
        if strategy == STRATEGY_ATOMIC and occupied:
            will_acquire = []
            pending = sorted((set(uncovered) | {row["分区日期"] for row in occupied})
                             - set(held))
        else:
            will_acquire = uncovered
            pending = [row["分区日期"] for row in occupied]
        return {
            "ok": True,
            "message": (
                f"计划 {plan_no}（{strategy}）预览：本次可领 {_fmt_dates(will_acquire)}；"
                f"原有占用 {_fmt_occupied(occupied)}；后续补办范围 {_fmt_dates(pending)}"
            ),
            "plan": plan_view(plan),
            "feature": feature,
            "strategy": strategy,
            "will_acquire": will_acquire,
            "held": held,
            "occupied": [
                {"date": row["分区日期"], "source": row["任务来源"],
                 "plan": row["来源计划"]}
                for row in occupied
            ],
            "pending": pending,
            "completed": completed,
        }


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------


def board(feature: str | None = None) -> dict[str, Any]:
    scopes = store.rows(SCOPE_MODULE)
    features = [{
        "目标特征": str(scope.get("目标特征", "")),
        "起始日期": scope.get("起始日期", ""),
        "截止日期": scope.get("截止日期", ""),
    } for scope in scopes]
    selected = feature or (features[0]["目标特征"] if features else "")
    partitions = partitions_for(selected) if selected else []
    plans = [
        plan_view(plan) for plan in store.rows(PLAN_MODULE)
        if is_backfill_plan(plan) and str(plan.get("关联对象", "")) == selected
    ]
    scope = _scope_for(selected) if selected else None
    return {
        "feature": selected,
        "scope": {
            "目标特征": selected,
            "起始日期": scope.get("起始日期", "") if scope else "",
            "截止日期": scope.get("截止日期", "") if scope else "",
        },
        "features": features,
        "summary": summary_of(partitions),
        "partitions": partitions,
        "plans": plans,
    }
