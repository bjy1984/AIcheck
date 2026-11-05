<script lang="ts">
import { ref } from 'vue'

/** 账号菜单「安装节点审计 skill」打开它；状态放模块里，菜单在哪个页面外壳都能开。 */
export const skillInstallOpen = ref(false)
export const openSkillInstall = () => {
  skillInstallOpen.value = true
}
/** 只给监检和管理员：skill 要用监检或管理员账号授权。 */
export const canInstallSkill = (role?: string) =>
  ['inspection', 'admin'].includes(String(role || ''))
</script>

<script setup lang="ts">
/* 一条提示词安装节点审计 skill（2026-11-04）：向服务器要一句话（含 10 分钟有效的安装链接和安装包校验值），
 * 用户把它发给自己电脑上的 AI 助手，AI 助手照链接里的说明装好、自检、打开网页授权。 */
import { computed, watch } from 'vue'
import { ElButton, ElDialog, ElInput, ElMessage } from 'element-plus'
import { createSkillInstallLinkApi } from '@/api/aicheck'
import type { SkillInstallLink } from '@/api/aicheck/skillInstall'
import { getAicheckErrorMessage } from '@/utils/aicheckError'

const link = ref<SkillInstallLink | null>(null)
const loading = ref(false)
const error = ref('')
const overHttp = computed(() => window.location.protocol === 'http:')
const expiresAt = computed(() => {
  if (!link.value) return ''
  const at = new Date(link.value.expiresAt)
  return Number.isNaN(at.getTime())
    ? ''
    : at.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
})

const generate = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await createSkillInstallLinkApi(window.location.origin)
    link.value = response.data
  } catch (exception) {
    link.value = null
    error.value = getAicheckErrorMessage(exception, '安装提示词没生成出来，请稍后重试。')
  } finally {
    loading.value = false
  }
}

watch(skillInstallOpen, (open) => {
  if (open) void generate()
})

const copy = async () => {
  if (!link.value) return
  try {
    await navigator.clipboard.writeText(link.value.prompt)
    ElMessage.success('已复制，发给你电脑上的 AI 助手就行')
  } catch {
    ElMessage.warning('浏览器不让直接复制：请选中框里的文字手动复制')
  }
}
</script>

<template>
  <ElDialog
    v-model="skillInstallOpen"
    title="安装节点审计 skill"
    width="min(560px, 94vw)"
    append-to-body
    class="skill-install-dialog"
  >
    <div class="skill-install">
      <p class="skill-install-lead">
        把下面这句话发给你电脑上的 AI 助手（Claude Code、Codex
        等）。它会自己下载、核对校验值、安装，最后打开浏览器让你授权；装好后对它说「审计 P-xxx 节点
        N」就行。
      </p>
      <p v-if="loading" class="skill-install-note">正在生成…</p>
      <p v-else-if="error" class="skill-install-note is-error">{{ error }}</p>
      <template v-else-if="link">
        <ElInput
          :model-value="link.prompt"
          type="textarea"
          :rows="5"
          readonly
          aria-label="安装提示词"
          class="skill-install-prompt"
        />
        <div class="skill-install-actions">
          <small>链接到 {{ expiresAt }} 前有效，过期了点「重新生成」。</small>
          <span class="skill-install-spacer"></span>
          <ElButton :loading="loading" @click="generate">重新生成</ElButton>
          <ElButton type="primary" @click="copy">复制</ElButton>
        </div>
      </template>
      <ul class="skill-install-tips">
        <li>电脑上要有 Python 3.9 或更新的版本；Windows 请让 AI 助手在 Git Bash 里装。</li>
        <li v-if="overHttp">
          平台目前用 HTTP：建议在办公网络里装，别用公共 Wi-Fi。AI
          助手会先核对安装包的校验值，对不上就停下。
        </li>
        <li>授权时用你自己的监检或管理员账号，口令只在浏览器里输，不要发给 AI 助手。</li>
      </ul>
    </div>
  </ElDialog>
</template>

<style scoped>
.skill-install {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}

.skill-install-lead,
.skill-install-note {
  margin: 0;
  font-size: 14px;
  line-height: 22px;
  color: #475467;
}

.skill-install-note.is-error {
  color: #b42318;
}

.skill-install-prompt :deep(.el-textarea__inner) {
  font-size: 13px;
  line-height: 20px;
  color: #172033;
  background: #f8fafc;
}

.skill-install-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.skill-install-actions small {
  font-size: 12px;
  color: #667085;
}

.skill-install-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.skill-install-spacer {
  flex: 1;
}

.skill-install-tips {
  display: grid;
  padding: 10px 14px 10px 28px;
  margin: 0;
  font-size: 13px;
  line-height: 20px;
  color: #475467;
  background: #f8fafc;
  border-radius: 8px;
  gap: 4px;
}
</style>
