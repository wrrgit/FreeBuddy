<template>
  <div
    class="msg"
    :id="`msg-${msg.id}`"
    :class="{ user: msg.member_id === 'user', error: msg.status === 'error' }"
  >
    <div class="avatar" :style="{ background: color }">{{ name.charAt(0) }}</div>
    <div class="body">
      <div class="head">
        <span class="name" :style="{ color }">{{ name }}</span>
        <span v-if="badge" class="badge" :class="msg.action" @click="onLocate">
          {{ badge }}
        </span>
        <span class="round" v-if="msg.round > 0">第 {{ msg.round }} 轮</span>
        <span class="time">{{ timeStr }}</span>
      </div>
      <div class="content">{{ msg.content }}</div>
      <ul v-if="msg.citations.length" class="citations">
        <li v-for="(c, i) in msg.citations" :key="i">{{ c }}</li>
      </ul>
      <details v-if="metaText" class="meta">
        <summary>来源信息</summary>
        <div class="meta-body">{{ metaText }}</div>
        <details v-if="msg.meta.raw" class="raw">
          <summary>原始输出</summary>
          <pre>{{ msg.meta.raw }}</pre>
        </details>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Member, Message } from '../types'

const props = defineProps<{ msg: Message; members: Member[] }>()
const emit = defineEmits<{ (e: 'locate', id: string): void }>()

const name = computed(() => props.msg.member_name)

const color = computed(() => {
  if (props.msg.member_id === 'user') return '#909399'
  return props.members.find((m) => m.id === props.msg.member_id)?.color ?? '#409EFF'
})

const badge = computed(() => {
  const map: Record<string, string> = {
    agree: '赞同',
    disagree: '反对',
    ask: '追问',
    new_topic: '新话题',
    summary: '总结',
  }
  const label = map[props.msg.action]
  if (!label) return ''
  if (props.msg.target_id && props.msg.action !== 'summary') {
    return `${label} → #${props.msg.target_id.slice(0, 8)}`
  }
  return label
})

const timeStr = computed(() =>
  new Date(props.msg.timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false })
)

const metaText = computed(() => {
  const m = props.msg.meta
  const parts: string[] = []
  if (m.cli) parts.push(`CLI: ${m.cli}`)
  if (m.model) parts.push(`模型: ${m.model}`)
  else if (m.cli) parts.push('模型: CLI 默认')
  if (m.session_id) parts.push(`会话: ${m.session_id.slice(0, 16)}…`)
  if (m.tokens) {
    const t = m.tokens as Record<string, number>
    const out = (t.output ?? 0) + (t.reasoning ?? 0)
    parts.push(`tokens: 输入≈${t.read ?? 0}(缓存) 输出=${out}`)
  }
  if (m.cost != null) parts.push(`成本: $${Number(m.cost).toFixed(4)}`)
  return parts.join(' · ')
})

const onLocate = () => {
  if (props.msg.target_id) emit('locate', props.msg.target_id)
}
</script>

<style scoped>
.msg {
  display: flex;
  gap: 10px;
  max-width: 86%;
  transition: background 0.3s;
}
.msg.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.msg.error .content {
  color: #f56c6c;
}
.msg.flash {
  background: #ecf5ff;
  border-radius: 8px;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
  font-weight: 600;
}
.body {
  min-width: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.name {
  font-size: 13px;
  font-weight: 600;
}
.badge {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 9px;
  cursor: pointer;
}
.badge.agree {
  color: #67c23a;
  background: #f0f9eb;
}
.badge.disagree {
  color: #f56c6c;
  background: #fef0f0;
}
.badge.ask {
  color: #e6a23c;
  background: #fdf6ec;
}
.badge.new_topic {
  color: #909399;
  background: #f4f4f5;
}
.badge.summary {
  color: #fff;
  background: #409eff;
}
.round,
.time {
  font-size: 11px;
  color: #c0c4cc;
}
.content {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg.user .content {
  background: #409eff;
  border-color: #409eff;
  color: #fff;
}
.citations {
  margin-top: 6px;
  padding-left: 18px;
  font-size: 12px;
  color: #909399;
}
.citations li {
  margin: 2px 0;
}
.meta {
  margin-top: 6px;
  font-size: 11px;
  color: #c0c4cc;
}
.meta summary {
  cursor: pointer;
  user-select: none;
}
.meta-body {
  padding: 4px 0;
}
.raw pre {
  margin-top: 4px;
  padding: 8px;
  background: #f4f4f5;
  border-radius: 4px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
