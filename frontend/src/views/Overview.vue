<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "特征注册", "created": 0, "pending": 0, "abnormal": 0}, {"name": "衍生工程", "created": 0, "pending": 0, "abnormal": 0}, {"name": "时间窗口", "created": 0, "pending": 0, "abnormal": 0}, {"name": "特征回溯", "created": 0, "pending": 0, "abnormal": 0}, {"name": "缺口分区", "created": 0, "pending": 0, "abnormal": 0}, {"name": "样本分层", "created": 0, "pending": 0, "abnormal": 0}, {"name": "标注派发", "created": 0, "pending": 0, "abnormal": 0}, {"name": "标注审核", "created": 0, "pending": 0, "abnormal": 0}, {"name": "一致性计算", "created": 0, "pending": 0, "abnormal": 0}, {"name": "特征存储", "created": 0, "pending": 0, "abnormal": 0}, {"name": "在线服务", "created": 0, "pending": 0, "abnormal": 0}, {"name": "离线导出", "created": 0, "pending": 0, "abnormal": 0}, {"name": "特征血缘", "created": 0, "pending": 0, "abnormal": 0}, {"name": "特征监控", "created": 0, "pending": 0, "abnormal": 0}, {"name": "版本管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据切分", "created": 0, "pending": 0, "abnormal": 0}, {"name": "特征目录", "created": 0, "pending": 0, "abnormal": 0}, {"name": "质量规则", "created": 0, "pending": 0, "abnormal": 0}, {"name": "标注词典", "created": 0, "pending": 0, "abnormal": 0}, {"name": "批量接入", "created": 0, "pending": 0, "abnormal": 0}, {"name": "特征报告", "created": 0, "pending": 0, "abnormal": 0}, {"name": "调度编排", "created": 0, "pending": 0, "abnormal": 0}, {"name": "治理审计", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
