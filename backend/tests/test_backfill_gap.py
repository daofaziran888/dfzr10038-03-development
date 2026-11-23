"""缺口分区明细的领域测试：按日期归并、认领互斥、交付范围可核对。

运行：cd backend && .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from app.seed import SEED_ROWS
from app.store import store
from app.services import backfill_gap, backfill_job, schedule_job

FEATURE = "user_age_bucket_7d"
RANGE = [f"2026-11-{day:02d}" for day in range(1, 8)]


def reseed() -> None:
    for name, rows in SEED_ROWS.items():
        store._tables[name] = [dict(row) for row in rows]


def statuses() -> dict[str, str]:
    return {row["分区日期"]: row["缺口状态"]
            for row in backfill_gap.partitions_for(FEATURE)}


def add_plan(plan_id: int, strategy: str = "先跑未分配日期") -> None:
    store.rows("schedule_job").append({
        "id": plan_id, "status": "待激活", "pending": True, "abnormal": False,
        "计划编号": f"SCHE-{plan_id:04d}", "任务类型": "特征回溯",
        "关联对象": FEATURE, "起始日期": RANGE[0], "截止日期": RANGE[-1],
        "认领策略": strategy, "认领历史": [],
    })


def active_per_day() -> Counter:
    counter: Counter = Counter()
    for job in store.rows("backfill_job"):
        if job.get("status") in ("回溯中", "已完成") and job.get("目标特征") == FEATURE:
            for day in backfill_gap.days_between(job["起始日期"], job["截止日期"]):
                counter[day] += 1
    return counter


class GapPartitionTest(unittest.TestCase):
    def setUp(self) -> None:
        reseed()

    def test_partitions_merge_same_feature_by_date(self) -> None:
        rows = backfill_gap.partitions_for(FEATURE)
        self.assertEqual([row["分区日期"] for row in rows], RANGE)
        self.assertEqual(statuses()[RANGE[0]], "未覆盖")
        self.assertEqual(statuses()[RANGE[1]], "已完成")
        self.assertEqual(statuses()[RANGE[2]], "处理中")
        done = next(row for row in rows if row["分区日期"] == RANGE[1])
        self.assertEqual(done["任务来源"], "BACK-0004")
        self.assertEqual(done["认领批次"], "首次派工")

    def test_summary_counts(self) -> None:
        summary = backfill_gap.summary_of(backfill_gap.partitions_for(FEATURE))
        self.assertEqual(summary, {"合计": 7, "未覆盖": 5, "处理中": 1, "已完成": 1})

    def test_no_overlapping_active_job_can_be_registered(self) -> None:
        service = backfill_job.BackfillJobService()
        entry, missing, conflict = service.create_entry({
            "任务编号": "BACK-9001", "目标特征": FEATURE,
            "起始日期": RANGE[2], "截止日期": RANGE[3],
        })
        self.assertIsNone(entry)
        self.assertFalse(missing)
        self.assertIn("BACK-0005", conflict)


class ClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        reseed()
        self.schedule = schedule_job.ScheduleJobService()

    def test_progressive_first_and_supplement_batches(self) -> None:
        entry, message = self.schedule.run_action(5, "激活计划")
        self.assertIsNotNone(entry)
        self.assertIn("2026-11-03", message)
        plan = store.find("schedule_job", 5)
        self.assertEqual(plan["本次到手日期"], "2026-11-01、2026-11-04、2026-11-05、2026-11-06、2026-11-07")
        self.assertIn("2026-11-03", plan["原有占用"])
        self.assertEqual(plan["后续补办范围"], "2026-11-03")
        self.assertEqual(plan["当前批次"], "首次派工")
        # 处理中的日期没有被提前显示成已完成。
        self.assertEqual(statuses()[RANGE[2]], "处理中")

        entry, _ = self.schedule.run_action(5, "立即执行")
        self.assertEqual(entry["status"], "执行中")

        entry, message = self.schedule.run_action(4, "停用计划")
        self.assertEqual(statuses()[RANGE[2]], "未覆盖")

        entry, message = self.schedule.run_action(5, "重新领取补办")
        self.assertIsNotNone(entry)
        self.assertEqual(store.find("schedule_job", 5)["当前批次"], "释放后补单")

        entry, _ = self.schedule.run_action(5, "立即执行")
        self.assertEqual(entry["status"], "已完成")
        view = backfill_gap.plan_view(store.find("schedule_job", 5))
        self.assertEqual(len(view["累计覆盖日期"]), 6)
        self.assertNotIn(RANGE[1], view["累计覆盖日期"])
        self.assertTrue(all(status == "已完成" for status in statuses().values()))

    def test_atomic_waits_then_delivers_whole_range(self) -> None:
        add_plan(7, strategy="等整段一起交付")
        entry, message = self.schedule.run_action(7, "激活计划")
        self.assertIsNotNone(entry)
        self.assertEqual(backfill_gap.plan_jobs("SCHE-0007"), [])
        self.assertIn("未齐", message)

        self.schedule.run_action(4, "停用计划")
        self.schedule.run_action(7, "重新领取补办")
        self.assertEqual(len(backfill_gap.plan_jobs("SCHE-0007")), 6)

    def test_completed_plan_cannot_reclaim(self) -> None:
        add_plan(8)
        self.schedule.run_action(8, "激活计划")
        self.schedule.run_action(8, "立即执行")  # 仍有 11-03 被占用 -> 执行中
        entry, message = self.schedule.run_action(8, "激活计划")
        self.assertIsNone(entry)
        self.assertIn("执行中", message)

    def test_concurrent_claims_write_each_date_once(self) -> None:
        plan_ids = list(range(20, 40))
        for plan_id in plan_ids:
            add_plan(plan_id)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda plan_id: backfill_gap.claim_plan(plan_id), plan_ids))
        acquired: Counter = Counter()
        for result in results:
            for day in result["acquired"]:
                acquired[day] += 1
        self.assertEqual(acquired, Counter({day: 1 for day in
                                            ["2026-11-01", "2026-11-04", "2026-11-05",
                                             "2026-11-06", "2026-11-07"]}))
        self.assertEqual(max(active_per_day().values()), 1)

    def test_done_dates_are_excluded_from_new_claims(self) -> None:
        add_plan(30)
        backfill_gap.claim_plan(30)
        job_days = [job["起始日期"] for job in backfill_gap.plan_jobs("SCHE-0030")]
        self.assertNotIn(RANGE[1], job_days)
        self.assertNotIn(RANGE[2], job_days)


if __name__ == "__main__":
    unittest.main()
