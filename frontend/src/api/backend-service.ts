import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'
import type { ClaimPreview, ClaimResult, GapBoard } from '@/domain/backfill_gap'

export { moduleMeta }

export async function loadGapBoard(feature?: string): Promise<GapBoard> {
  const query = feature ? `?feature=${encodeURIComponent(feature)}` : ''
  const response = await request(`/api/backfill_gap${query}`)
  if (!response.ok) throw new Error('缺口分区明细读取失败')
  return await response.json()
}

export async function loadClaimPreview(planId: number): Promise<ClaimPreview> {
  const response = await request(`/api/schedule_job/${planId}/claim-preview`)
  if (!response.ok) throw new Error('认领预览读取失败')
  return await response.json()
}

export async function setClaimStrategy(
  planId: number,
  strategy: string,
): Promise<{ ok: boolean; message: string }> {
  const response = await request(`/api/schedule_job/${planId}/claim-strategy`, {
    method: 'POST',
    body: JSON.stringify({ action: strategy }),
  })
  return await response.json()
}

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}
