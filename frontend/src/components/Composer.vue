<template>
  <footer class="composer">
    <div class="row" v-if="running">
      <tiny-button type="warning" size="small" @click="$emit('stop')">
        停止讨论
      </tiny-button>
      <span class="hint">讨论进行中，你可以随时插话，成员在下一轮会看到</span>
    </div>
    <div class="input-row">
      <tiny-input
        v-model="text"
        type="textarea"
        :rows="3"
        :placeholder="
          running
            ? '插话：补充信息或纠正方向…'
            : '输入一个问题，多个 CLI 成员将展开讨论…'
        "
        @keydown.enter.exact.prevent="onEnter"
      />
      <div class="controls">
        <div class="rounds" v-if="!running">
          <span class="label">讨论轮数</span>
          <tiny-select v-model="rounds" style="width: 70px">
            <tiny-option v-for="n in 5" :key="n" :value="n" :label="`${n}`" />
          </tiny-select>
          <label class="skip-triage">
            <input type="checkbox" v-model="skipTriage" />
            跳过判断，直接讨论
          </label>
        </div>
        <tiny-button v-if="running" type="primary" :disabled="!text.trim()" @click="onInterject">
          插话
        </tiny-button>
        <tiny-button v-else type="primary" :disabled="!text.trim()" @click="onDiscuss">
          开始讨论
        </tiny-button>
        <tiny-button v-if="!running && hasMessages" @click="$emit('clear')">
          清空
        </tiny-button>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'

const props = defineProps<{ running: boolean; hasMessages?: boolean }>()
const emit = defineEmits<{
  (e: 'discuss', question: string, rounds: number, skipTriage: boolean): void
  (e: 'stop'): void
  (e: 'interject', content: string): void
  (e: 'clear'): void
}>()

const text = ref('')
const rounds = ref(2)
const skipTriage = ref(false)

const onEnter = () => {
  if (props.running) onInterject()
  else onDiscuss()
}

const onDiscuss = () => {
  const q = text.value.trim()
  if (!q) return
  emit('discuss', q, rounds.value, skipTriage.value)
  text.value = ''
}

const onInterject = () => {
  const c = text.value.trim()
  if (!c) return
  emit('interject', c)
  text.value = ''
}
</script>

<style scoped>
.composer {
  background: #fff;
  border-top: 1px solid #e4e7ed;
  padding: 12px 20px 16px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.hint {
  font-size: 12px;
  color: #e6a23c;
}
.input-row {
  display: flex;
  gap: 14px;
  align-items: flex-end;
}
.controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
  flex-shrink: 0;
}
.rounds {
  display: flex;
  align-items: center;
  gap: 6px;
}
.label {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}
.skip-triage {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  cursor: pointer;
  margin-left: 6px;
}
.skip-triage input {
  margin: 0;
  cursor: pointer;
}
</style>
