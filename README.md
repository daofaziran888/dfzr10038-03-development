# 特征工坊 · 特征工程与标注数据管理平台

面向特征注册与检索、衍生特征工程、时间窗口计算、特征回溯填充、样本分层抽取、标注任务派发、标注质量审核、特征血缘追踪与在线/离线特征服务的数据特征工程与标注管理平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 特征注册 | `feature_reg` | 特征定义 | 特征编号、特征名称、数据类型 |
| 衍生工程 | `derive_rule` | 衍生规则 | 规则编号、输入特征、衍生函数 |
| 时间窗口 | `time_window` | 窗口模板 | 模板编号、窗口类型、窗口宽度 |
| 特征回溯 | `backfill_job` | 回溯任务 | 任务编号、目标特征、起始日期 |
| 缺口分区 | `backfill_scope` | 回溯范围 | 目标特征、起始日期、截止日期 |
| 样本分层 | `sample_strata` | 分层策略 | 策略编号、特征范围、分层字段 |
| 标注派发 | `label_task` | 标注任务 | 任务编号、样本范围、标注类型 |
| 标注审核 | `label_review` | 审核批次 | 批次编号、标注任务、审核人 |
| 一致性计算 | `consent_calc` | 一致性报告 | 报告编号、标注任务、评估指标 |
| 特征存储 | `feature_store` | 存储配置 | 配置编号、特征列表、存储引擎 |
| 在线服务 | `online_serv` | 服务端点 | 端点编号、特征列表、QPS上限 |
| 离线导出 | `offline_exp` | 导出管道 | 管道编号、特征范围、导出格式 |
| 特征血缘 | `feature_line` | 血缘链路 | 链路编号、上游特征、下游特征 |
| 特征监控 | `feature_mon` | 监控规则 | 规则编号、目标特征、监控类型 |
| 版本管理 | `version_mgr` | 特征版本 | 版本编号、关联特征、版本标签 |
| 数据切分 | `data_split` | 切分配置 | 配置编号、数据集、切分方式 |
| 特征目录 | `feat_catalog` | 目录索引 | 索引编号、目录名称、父目录 |
| 质量规则 | `quality_rule` | 质量检查 | 规则编号、目标特征、检查类型 |
| 标注词典 | `label_dict` | 标注项 | 词典编号、标签名称、标签值 |
| 批量接入 | `batch_load` | 接入任务 | 任务编号、数据源、目标特征 |
| 特征报告 | `report_task` | 分析报表 | 报告编号、报告类型、特征范围 |
| 调度编排 | `schedule_job` | 调度计划 | 计划编号、任务类型、关联对象、认领策略 |
| 治理审计 | `govern_audit` | 审计记录 | 记录编号、审计对象、审计类型 |

## 回溯缺口分区与日期认领

`backfill_scope` 登记需要按日期对账的特征和起止日期，`GET /api/backfill_gap`
把同一特征下的多份回溯任务归并成逐日分区明细，状态按「已完成 > 处理中 > 未覆盖」
取值，处理中的日期会列出占用它的任务来源。

调度编排里的 `任务类型=特征回溯` 计划按两种认领策略读取缺口分区明细：

- `先跑未分配日期`：激活时立即领取所有未覆盖日期，被其他计划占用的日期进入
  后续补办范围。
- `等整段一起交付`：区间内仍有他人占用时不领零散日期，等释放后一次领齐。

认领结果（本次到手日期、原有占用、后续补办范围）随动作返回并在计划列表里展示。
同一特征 + 同一日期只允许一份活动任务：认领在进程内锁下串行并二次检查，重复
登记重叠区间会被拒绝；只有显式「立即执行」才把处理中的日期转为已完成，已完成
的日期不会再进入新增认领范围。

```text
GET  /api/backfill_gap[?feature=user_age_bucket_7d]
GET  /api/backfill_gap/partitions
GET  /api/schedule_job/{id}/claim-preview
POST /api/schedule_job/{id}/claim-strategy   {"action": "先跑未分配日期"}
POST /api/schedule_job/{id}/actions          {"action": "激活计划|重新领取补办|立即执行|停用计划"}
```

示例数据：`user_age_bucket_7d` 在 2026-11-01 至 2026-11-07 的缺口里，11-02 已完成、
11-03 被旧计划 SCHE-0004 的处理中任务占用，其余五天未覆盖。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数仓与数据湖
