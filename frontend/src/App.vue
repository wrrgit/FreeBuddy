<template>
  <div class="layout">
    <aside class="side">
      <MemberPanel
        :members="members"
        :families="families"
        :locked="running"
        @changed="loadMembers"
      />
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="title">
          multi-cli 群聊
          <span v-if="running" class="status running">
            讨论中 · 第 {{ currentRound }}/{{ maxRounds }} 轮
          </span>
          <span v-else class="status idle">空闲</span>
        </div>
        <div class="question" v-if="question">主题：{{ question }}</div>
      </header>
      <section class="stream" ref="streamRef">
        <div v-if="messages.length === 0" class="empty">
          输入一个问题，让多个 CLI 成员开始讨论
        </div>
        <ChatMessage
          v-for="msg in messages"
          :key="msg.id"
          :msg="msg"
          :members="members"
          @locate="locateMessage"
        />
        <div v-if="typingMember" class="typing">
          <span class="dot">●</span> {{ typingMember }} 正在思考…
        </div>
      </section>
      <Composer
        :running="running"
        @discuss="onDiscuss"
        @stop="onStop"
        @interject="onInterject"
        @clear="onClear"
      />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import type { FamilyInfo, Member, Message, WsEvent } from './types'
import ChatMessage from './components/ChatMessage.vue'
import MemberPanel from './components/MemberPanel.vue'
import Composer from './components/Composer.vue'

const members = ref<Member[]>([])
const families = ref<FamilyInfo[]>([])
const messages = ref<Message[]>([])
const running = ref(false)
const question = ref('')
const currentRound = ref(0)
const maxRounds = ref(3)
const typingMember = ref('')
const streamRef = ref<HTMLElement>()

let ws: WebSocket | null = null
let reconnectTimer: number | null = null

const loadMembers = async () => {
  members.value = await api.getMembers()
}

const scrollToBottom = async () => {
  await nextTick()
  const el = streamRef.value
  if (el) el.scrollTop = el.scrollHeight
}

const locateMessage = (id: string) => {
  const el = document.getElementById(`msg-${id}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('flash')
    setTimeout(() => el.classList.remove('flash'), 1500)
  }
}

const handleEvent = (ev: WsEvent) => {
  switch (ev.type) {
    case 'init':
      messages.value = ev.messages ?? []
      running.value = ev.running ?? false
      question.value = ev.question ?? ''
      scrollToBottom()
      break
    case 'message':
      if (ev.message) {
        messages.value.push(ev.message)
        if (!ev.message.member_id || ev.message.member_id === 'user') {
          if (ev.message.member_id === 'user') question.value = ev.message.content
        }
        if (ev.message.action === 'summary') typingMember.value = ''
        scrollToBottom()
      }
      break
    case 'typing':
      typingMember.value = ev.member_name ?? ''
      currentRound.value = ev.round ?? currentRound.value
      scrollToBottom()
      break
    case 'round_start':
      currentRound.value = ev.round ?? 0
      maxRounds.value = ev.max_rounds ?? maxRounds.value
      typingMember.value = ''
      break
    case 'finished':
      running.value = false
      typingMember.value = ''
      break
    case 'cleared':
      messages.value = []
      question.value = ''
      typingMember.value = ''
      break
    case 'error':
      running.value = false
      typingMember.value = ''
      console.error(ev.error)
      break
  }
}

const connectWs = () => {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/ws`)
  ws.onmessage = (e) => handleEvent(JSON.parse(e.data) as WsEvent)
  ws.onclose = () => {
    reconnectTimer = window.setTimeout(connectWs, 2000)
  }
}

const onDiscuss = async (q: string, rounds: number) => {
  const res = await api.discuss(q, rounds)
  if (!res.ok) {
    alert(res.error ?? '启动失败')
    return
  }
  running.value = true
  maxRounds.value = rounds
  currentRound.value = 0
}

const onStop = async () => {
  await api.stop()
}

const onInterject = async (content: string) => {
  const res = await api.interject(content)
  if (!res.ok) alert(res.error ?? '发送失败')
}

const onClear = async () => {
  const res = await api.clear()
  if (!res.ok) alert(res.error ?? '清空失败')
}

onMounted(async () => {
  await loadMembers()
  families.value = await api.getFamilies()
  connectWs()
})

onUnmounted(() => {
  ws?.close()
  if (reconnectTimer) clearTimeout(reconnectTimer)
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
html,
body,
#app {
  height: 100%;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif;
}
.layout {
  display: flex;
  height: 100%;
  background: #f5f7fa;
}
.side {
  width: 300px;
  flex-shrink: 0;
  border-right: 1px solid #e4e7ed;
  background: #fff;
  overflow-y: auto;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.title {
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 10px;
}
.status {
  font-size: 12px;
  font-weight: 400;
  padding: 2px 10px;
  border-radius: 10px;
}
.status.running {
  color: #e6a23c;
  background: #fdf6ec;
}
.status.idle {
  color: #909399;
  background: #f4f4f5;
}
.question {
  font-size: 12px;
  color: #909399;
  max-width: 50%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stream {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.empty {
  margin: auto;
  color: #c0c4cc;
  font-size: 14px;
}
.typing {
  color: #909399;
  font-size: 13px;
  padding: 4px 12px;
}
.typing .dot {
  color: #409eff;
  animation: blink 1s infinite;
}
@keyframes blink {
  50% {
    opacity: 0.2;
  }
}
</style>
