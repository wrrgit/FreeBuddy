<template>
  <div class="panel">
    <div class="panel-head">
      <span>群成员（{{ members.length }}）</span>
      <tiny-button size="small" type="primary" plain @click="openCreate" :disabled="locked">
        + 添加
      </tiny-button>
    </div>

    <div v-for="m in members" :key="m.id" class="card">
      <div class="card-head">
        <span class="avatar" :style="{ background: m.color }">{{ m.name.charAt(0) }}</span>
        <div class="card-title">
          <div class="name-row">
            <span class="name">{{ m.name }}</span>
            <tiny-switch
              v-model="m.enabled"
              size="small"
              :disabled="locked"
              @change="onToggle(m)"
            />
          </div>
          <div class="cli-line">
            <tiny-tag size="small">{{ familyLabel(m.family) }}</tiny-tag>
            <tiny-tag v-if="m.summary_only" size="small" type="warning">仅最终方案</tiny-tag>
            <span class="model">{{ m.family === 'generic_family' ? m.cli : (m.model || '默认模型') }}</span>
          </div>
        </div>
      </div>
      <div class="role">{{ m.role || '（未设置角色）' }}</div>
      <div class="card-actions">
        <tiny-link type="primary" @click="openEdit(m)">编辑</tiny-link>
        <tiny-link type="danger" @click="onDelete(m)">删除</tiny-link>
      </div>
    </div>

    <tiny-dialog-box
      :visible="dialogVisible"
      :title="editingId ? '编辑成员' : '添加成员'"
      width="520px"
      @close="dialogVisible = false"
    >
      <tiny-form label-width="88px">
        <tiny-form-item label="名称">
          <tiny-input v-model="form.name" placeholder="如：研究员" maxlength="20" />
        </tiny-form-item>
        <tiny-form-item label="协议族">
          <tiny-select v-model="form.family" @change="onFamilyChange">
            <tiny-option
              v-for="f in families"
              :key="f.family"
              :value="f.family"
              :label="f.label"
            />
          </tiny-select>
        </tiny-form-item>
        <tiny-form-item v-if="form.family === 'generic_family'" label="命令模板">
          <tiny-input
            v-model="form.cli"
            placeholder="如：mycli ask {prompt_file}"
          />
          <div class="form-hint" v-if="genericHint">{{ genericHint }}</div>
        </tiny-form-item>
        <tiny-form-item v-else label="CLI">
          <tiny-select v-model="form.cli" @change="onCliChange">
            <tiny-option
              v-for="c in currentFamilyClis"
              :key="c.name"
              :value="c.name"
              :label="`${c.name}${c.installed ? '' : '（未安装）'}`"
            />
          </tiny-select>
        </tiny-form-item>
        <tiny-form-item v-if="form.family !== 'generic_family'" label="模型">
          <tiny-select
            v-model="form.model"
            clearable
            filterable
            allow-create
            :loading="modelsLoading"
            placeholder="默认模型（CLI 自行决定）"
          >
            <tiny-option v-for="mo in models" :key="mo" :value="mo" :label="mo" />
          </tiny-select>
        </tiny-form-item>
        <tiny-form-item label="角色分工">
          <tiny-input
            v-model="form.role"
            type="textarea"
            :rows="3"
            placeholder="如：魔鬼代言人：必须质疑主流观点，专挑反例与边界情况"
            maxlength="200"
          />
        </tiny-form-item>
        <tiny-form-item label="参与方式">
          <tiny-switch v-model="form.summary_only" />
          <span class="form-hint">开启后不参与每轮发言，仅输出最终总结方案（主持人角色）</span>
        </tiny-form-item>
        <tiny-form-item label="颜色">
          <div class="colors">
            <span
              v-for="c in palette"
              :key="c"
              class="color-dot"
              :style="{ background: c }"
              :class="{ active: form.color === c }"
              @click="form.color = c"
            />
          </div>
        </tiny-form-item>
      </tiny-form>
      <template #footer>
        <tiny-button @click="dialogVisible = false">取消</tiny-button>
        <tiny-button type="primary" :disabled="!form.name.trim() || !form.cli.trim()" @click="onSave">
          保存
        </tiny-button>
      </template>
    </tiny-dialog-box>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api } from '../api'
import type { FamilyInfo, Member } from '../types'

const props = defineProps<{ members: Member[]; families: FamilyInfo[]; locked: boolean }>()
const emit = defineEmits<{ (e: 'changed'): void }>()

const palette = ['#409EFF', '#67C23A', '#F56C6C', '#E6A23C', '#9254DE', '#36CFC9']

const dialogVisible = ref(false)
const editingId = ref('')
const models = ref<string[]>([])
const modelsLoading = ref(false)
const form = reactive({
  name: '',
  cli: '',
  family: 'opencode_family',
  model: '' as string,
  role: '',
  color: palette[0],
  enabled: true,
  summary_only: false,
})

const familyLabel = (family: string) =>
  props.families.find((f) => f.family === family)?.label ?? family

const currentFamilyClis = computed(
  () => props.families.find((f) => f.family === form.family)?.clis ?? []
)

const genericHint = computed(
  () => props.families.find((f) => f.family === 'generic_family')?.hint ?? ''
)

const loadModels = async (cli: string, family: string) => {
  if (family === 'generic_family') return
  modelsLoading.value = true
  try {
    const res = await api.getModels(cli, family)
    models.value = res.models ?? []
  } finally {
    modelsLoading.value = false
  }
}

const onFamilyChange = () => {
  form.cli = currentFamilyClis.value[0]?.name ?? ''
  form.model = ''
  loadModels(form.cli, form.family)
}

const onCliChange = (cli: string) => {
  form.model = ''
  loadModels(cli, form.family)
}

const openCreate = () => {
  editingId.value = ''
  const firstInstalled = props.families.find((f) => f.clis.some((c) => c.installed))
  Object.assign(form, {
    name: '',
    family: firstInstalled?.family ?? 'opencode_family',
    cli: firstInstalled?.clis.find((c) => c.installed)?.name ?? 'deveco',
    model: '',
    role: '',
    color: palette[props.members.length % palette.length],
    enabled: true,
    summary_only: false,
  })
  loadModels(form.cli, form.family)
  dialogVisible.value = true
}

const openEdit = (m: Member) => {
  editingId.value = m.id
  Object.assign(form, {
    name: m.name,
    family: m.family,
    cli: m.cli,
    model: m.model ?? '',
    role: m.role,
    color: m.color,
    enabled: m.enabled,
    summary_only: m.summary_only,
  })
  loadModels(m.cli, m.family)
  dialogVisible.value = true
}

const buildBody = () => ({
  name: form.name.trim(),
  cli: form.cli.trim(),
  family: form.family,
  model: form.model || null,
  role: form.role.trim(),
  color: form.color,
  enabled: form.enabled,
  summary_only: form.summary_only,
})

const onSave = async () => {
  if (editingId.value) {
    await api.updateMember(editingId.value, buildBody())
  } else {
    await api.addMember(buildBody())
  }
  dialogVisible.value = false
  emit('changed')
}

const onToggle = async (m: Member) => {
  await api.updateMember(m.id, {
    name: m.name,
    cli: m.cli,
    family: m.family,
    model: m.model,
    role: m.role,
    color: m.color,
    enabled: m.enabled,
    summary_only: m.summary_only,
  })
}

const onDelete = async (m: Member) => {
  if (!confirm(`确定删除成员「${m.name}」？`)) return
  await api.deleteMember(m.id)
  emit('changed')
}
</script>

<style scoped>
.panel {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 600;
}
.card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
  opacity: 1;
}
.card:has(.tiny-switch:not(.tiny-switch-checked)) {
  opacity: 0.5;
}
.card-head {
  display: flex;
  gap: 8px;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}
.card-title {
  flex: 1;
  min-width: 0;
}
.name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.name {
  font-size: 14px;
  font-weight: 600;
}
.cli-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  flex-wrap: wrap;
}
.model {
  font-size: 11px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}
.role {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
  line-height: 1.5;
}
.card-actions {
  display: flex;
  gap: 12px;
  margin-top: 6px;
}
.colors {
  display: flex;
  gap: 8px;
}
.color-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid transparent;
}
.color-dot.active {
  border-color: #303133;
}
.form-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.5;
}
</style>
