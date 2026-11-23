/** 缺口分区明细：同一特征的多份回溯任务归并到日期后的前端契约。 */

export type GapStatus = '未覆盖' | '处理中' | '已完成'

export type GapPartition = {
  id: number
  status: GapStatus
  pending: boolean
  缺口编号: string
  目标特征: string
  分区日期: string
  缺口状态: GapStatus
  任务来源: string
  来源计划: string
  认领批次: string
  认领时间: string
  覆盖任务数: number
  已完成任务数: number
  处理中任务数: number
}

export type PlanClaimView = {
  id: number
  计划编号: string
  任务类型: string
  关联对象: string
  起始日期: string
  截止日期: string
  认领策略: string
  status: string
  pending: boolean
  本次到手日期: string
  原有占用: string
  后续补办范围: string
  当前批次: string
  累计覆盖日期: string[]
  累计覆盖数: number
  已完成日期: string[]
  认领历史: { 批次: string; 日期: string[]; 时间: string }[]
}

export type GapBoard = {
  feature: string
  scope: { 目标特征: string; 起始日期: string; 截止日期: string }
  features: { 目标特征: string; 起始日期: string; 截止日期: string }[]
  summary: Record<string, number>
  partitions: GapPartition[]
  plans: PlanClaimView[]
}

export type ClaimPreview = {
  ok: boolean
  message: string
  feature: string
  strategy: string
  will_acquire: string[]
  held: string[]
  occupied: { date: string; source: string; plan: string }[]
  pending: string[]
  completed: string[]
}

export type ClaimResult = {
  ok: boolean
  message: string
  action: string
  batch?: string
  feature?: string
  acquired?: string[]
  held?: string[]
  occupied?: { date: string; source: string; plan: string }[]
  pending?: string[]
  completed?: string[]
  executed?: string[]
  released?: string[]
  plan?: PlanClaimView
}

export const STRATEGIES = ['先跑未分配日期', '等整段一起交付'] as const
