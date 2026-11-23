<template>
  <section class="gap-panel" data-testid="backfill-gap-panel">
    <header class="gap-head">
      <div>
        <h3>缺口分区明细</h3>
        <p class="page-desc">
          同一特征的多份回溯任务按日期归并：未覆盖的日期才能被新计划认领，处理中的日期列出占用任务来源，已完成的日期不再重新计算。
        </p>
      </div>
      <label class="gap-feature">
        <span>目标特征</span>
        <select v-model="feature" data-testid="gap-feature" @change="reload">
          <option v-for="item in board.features" :key="item.目标特征" :value="item.目标特征">
            {{ item.目标特征 }}（{{ item.起始日期 }} ~ {{ item.截止日期 }}）
          </option>
        </select>
      </label>
    </header>

    <div class="stat-row">
      <article v-for="item in summaryCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :data-testid="`gap-summary-${item.label}`">{{ item.value }}</strong>
      </article>
    </div>

    <table class="data-table" data-testid="gap-table">
      <thead>
        <tr>
          <th>分区日期</th>
          <th>缺口状态</th>
          <th>任务来源</th>
          <th>来源计划</th>
          <th>认领批次</th>
          <th>认领时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in board.partitions" :key="row.分区日期" :data-testid="`gap-row-${row.分区日期}`">
          <td>{{ row.分区日期 }}</td>
          <td>
            <span :class="['gap-badge', `gap-${row.缺口状态}`]" :data-testid="`gap-status-${row.分区日期}`">
              {{ row.缺口状态 }}
            </span>
          </td>
          <td>{{ row.任务来源 }}</td>
          <td>{{ row.来源计划 }}</td>
          <td>{{ row.认领批次 }}</td>
          <td>{{ row.认领时间 }}</td>
        </tr>
        <tr v-if="!board.partitions.length">
          <td colspan="6" class="empty-state">该特征还没有登记回溯范围，先在「缺口分区」登记起止日期</td>
        </tr>
      </tbody>
    </table>

    <section class="plan-board">
      <header class="gap-head">
        <div>
          <h3>回溯计划认领</h3>
          <p class="page-desc">
            同一时间段可能被两个补算计划选中。先跑未分配日期会立即领取未覆盖日期，等整段一起交付会等占用释放后整段领取。
          </p>
        </div>
      </header>

      <div class="plan-grid">
        <article
          v-for="plan in board.plans"
          :key="plan.计划编号"
          class="plan-card"
          :data-testid="`plan-card-${plan.计划编号}`"
        >
          <header class="plan-card-head">
            <strong>{{ plan.计划编号 }}</strong>
            <span class="plan-status">{{ plan.status }}</span>
          </header>
          <dl class="plan-fields">
            <dt>认领策略</dt>
            <dd>
              <select
                :value="plan.认领策略"
                :disabled="plan.status !== '待激活'"
                :data-testid="`plan-strategy-${plan.计划编号}`"
                @change="onStrategy(plan, $event)"
              >
                <option v-for="item in STRATEGIES" :key="item" :value="item">{{ item }}</option>
              </select>
            </dd>
            <dt>本次到手日期</dt>
            <dd :data-testid="`plan-acquired-${plan.计划编号}`">{{ plan.本次到手日期 }}</dd>
            <dt>原有占用</dt>
            <dd :data-testid="`plan-occupied-${plan.计划编号}`">{{ plan.原有占用 }}</dd>
            <dt>后续补办范围</dt>
            <dd :data-testid="`plan-pending-${plan.计划编号}`">{{ plan.后续补办范围 }}</dd>
            <dt>累计覆盖</dt>
            <dd>{{ plan.累计覆盖数 }} 天</dd>
          </dl>
          <div class="row-actions">
            <button class="link" type="button" :data-testid="`plan-preview-${plan.计划编号}`" @click="preview(plan)">
              预览本次范围
            </button>
            <button
              v-if="plan.status === '待激活'"
              class="link"
              type="button"
              :data-testid="`plan-activate-${plan.计划编号}`"
              @click="act(plan, '激活计划')"
            >
              激活计划
            </button>
            <button
              v-if="plan.status === '执行中'"
              class="link"
              type="button"
              :data-testid="`plan-execute-${plan.计划编号}`"
              @click="act(plan, '立即执行')"
            >
              执行本次分配
            </button>
            <button
              v-if="plan.status === '执行中'"
              class="link"
              type="button"
              :data-testid="`plan-reclaim-${plan.计划编号}`"
              @click="act(plan, '重新领取补办')"
            >
              重新领取补办
            </button>
            <button
              v-if="plan.status !== '已停用' && plan.status !== '已完成'"
              class="link"
              type="button"
              :data-testid="`plan-release-${plan.计划编号}`"
              @click="act(plan, '停用计划')"
            >
              释放占用
            </button>
          </div>
        </article>
        <p v-if="!board.plans.length" class="empty-state">该特征还没有回溯计划，可在「调度编排」登记后激活</p>
      </div>

      <p v-if="message" class="gap-message" data-testid="gap-message">{{ message }}</p>
      <p v-if="previewText" class="gap-preview" data-testid="gap-preview">{{ previewText }}</p>
      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  loadClaimPreview,
  loadGapBoard,
  runAction,
  setClaimStrategy,
} from '@/api/backend-service'
import {
  STRATEGIES,
  type ClaimPreview,
  type ClaimResult,
  type GapBoard,
  type PlanClaimView,
} from '@/domain/backfill_gap'

const props = defineProps<{ refreshToken?: number }>()

const emptyBoard: GapBoard = {
  feature: '',
  scope: { 目标特征: '', 起始日期: '', 截止日期: '' },
  features: [],
  summary: {},
  partitions: [],
  plans: [],
}

const board = ref<GapBoard>({ ...emptyBoard })
const feature = ref('')
const message = ref('')
const previewText = ref('')
const errorMessage = ref('')

const summaryCards = computed(() => [
  { label: '合计', value: board.value.summary['合计'] ?? 0 },
  { label: '未覆盖', value: board.value.summary['未覆盖'] ?? 0 },
  { label: '处理中', value: board.value.summary['处理中'] ?? 0 },
  { label: '已完成', value: board.value.summary['已完成'] ?? 0 },
])

async function reload() {
  errorMessage.value = ''
  try {
    board.value = await loadGapBoard(feature.value || undefined)
    feature.value = board.value.feature
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺口分区明细读取失败'
  }
}

function describePreview(data: ClaimPreview) {
  const acquire = data.will_acquire.length ? data.will_acquire.join('、') : '无'
  const pending = data.pending.length ? data.pending.join('、') : '无'
  return `本次可领：${acquire}；原有占用：${data.occupied.length ? data.occupied.map((item) => `${item.date}（${item.source} / ${item.plan}）`).join('；') : '无'}；后续补办：${pending}`
}

function describeClaim(data: ClaimResult) {
  if (data.action === 'release') {
    return `已释放：${(data.released ?? []).join('、') || '无'}`
  }
  if (data.action === 'execute') {
    return `已执行：${(data.executed ?? []).join('、') || '无'}；后续补办：${(data.pending ?? []).join('、') || '无'}`
  }
  const acquired = (data.acquired ?? []).join('、') || '无'
  const pending = (data.pending ?? []).join('、') || '无'
  const occupied = (data.occupied ?? []).map((item) => `${item.date}（${item.source} / ${item.plan}）`).join('；') || '无'
  return `${data.batch ?? ''} 本次到手：${acquired}；原有占用：${occupied}；后续补办：${pending}`
}

async function preview(plan: PlanClaimView) {
  errorMessage.value = ''
  previewText.value = ''
  try {
    const data = await loadClaimPreview(plan.id)
    previewText.value = data.ok ? describePreview(data) : data.message
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '认领预览失败'
  }
}

async function onStrategy(plan: PlanClaimView, event: Event) {
  const strategy = (event.target as HTMLSelectElement).value
  errorMessage.value = ''
  try {
    const result = await setClaimStrategy(plan.id, strategy)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '切换认领策略失败'
    await reload()
  }
}

async function act(plan: PlanClaimView, action: string) {
  errorMessage.value = ''
  message.value = ''
  try {
    const result = await runAction('schedule_job', plan.id, action)
    if (!result.ok) throw new Error(result.message)
    message.value = result.claim ? describeClaim(result.claim) : result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '计划动作执行失败'
    await reload()
  }
}

onMounted(reload)

// 工作台里的登记/动作完成后会推进 refreshToken，看板随后按缺口分区明细重新对账。
watch(() => props.refreshToken, () => { void reload() })
</script>
