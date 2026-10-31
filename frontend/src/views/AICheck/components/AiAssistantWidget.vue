<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElIcon } from 'element-plus'
import { ArrowDown, ChatDotRound } from '@element-plus/icons-vue'

// 右下角悬浮的 AI 助手：样子和交互照在线客服窗口来——点悬浮按钮，面板从按钮处弹出，
// 背景压一层半透明黑色遮罩，让注意力落在面板上；点遮罩、再点按钮或面板右上角的收起键都会缩回去。
// 面板打开时背景页面点不了，要换节点先收起它。
// 收起只是隐藏，里面的对话和选中的证据都留着，再点开接着用。
const props = defineProps<{
  open: boolean
  title: string
  subtitle?: string
  hint?: string
}>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

// 第一次点开才挂载里面的内容：审查工作台一挂上就会去建会话、拉工作区，没点开的人不该为它发请求。
const everOpened = ref(props.open)
watch(
  () => props.open,
  (open) => {
    if (open) everOpened.value = true
  }
)

const panel = ref<HTMLElement>()
const launcher = ref<HTMLElement>()
const toggle = () => emit('update:open', !props.open)
const close = () => {
  emit('update:open', false)
  void nextTick(() => launcher.value?.focus({ preventScroll: true }))
}
const focusPanel = () => panel.value?.focus({ preventScroll: true })

// 只在焦点落在标题栏或按钮上时响应 Esc：面板里有下拉框、弹层，它们按 Esc 是关自己，不该把整个助手收掉。
const handleKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Escape') return
  if ((event.target as HTMLElement | null)?.closest('.ai-assistant-body')) return
  close()
}
</script>

<template>
  <div class="ai-assistant" @keydown="handleKeydown">
    <Transition name="ai-assistant-mask">
      <div v-show="open" class="ai-assistant-mask" aria-hidden="true" @click="close"></div>
    </Transition>
    <Transition name="ai-assistant-pop" @after-enter="focusPanel">
      <section
        v-show="open"
        id="ai-assistant-panel"
        ref="panel"
        class="ai-assistant-panel"
        role="dialog"
        aria-label="AI 审查助手"
        tabindex="-1"
      >
        <header class="ai-assistant-head">
          <span class="ai-assistant-avatar" aria-hidden="true">
            <ElIcon><ChatDotRound /></ElIcon>
          </span>
          <div class="ai-assistant-heading">
            <strong>{{ title }}</strong>
            <span v-if="subtitle" class="ai-assistant-subtitle" :title="subtitle">{{
              subtitle
            }}</span>
          </div>
          <button
            type="button"
            class="ai-assistant-minimize"
            aria-label="收起 AI 审查"
            title="收起"
            @click="close"
          >
            <ElIcon><ArrowDown /></ElIcon>
          </button>
        </header>
        <div class="ai-assistant-body">
          <slot v-if="everOpened"></slot>
        </div>
      </section>
    </Transition>
    <button
      ref="launcher"
      type="button"
      :class="['ai-assistant-launcher', { 'is-open': open }]"
      :aria-expanded="open"
      aria-controls="ai-assistant-panel"
      :title="open ? '收起 AI 审查' : hint"
      @click="toggle"
    >
      <ElIcon class="ai-assistant-launcher-icon">
        <ArrowDown v-if="open" />
        <ChatDotRound v-else />
      </ElIcon>
      <span class="ai-assistant-launcher-label">AI审查</span>
    </button>
  </div>
</template>

<style scoped>
/* 层级压在页面内容之上、Element 弹窗（2000 起）之下：面板里点“查看原文”弹出的证据窗要盖在助手上面。 */
.ai-assistant {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1900;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
  pointer-events: none;
}

.ai-assistant > * {
  pointer-events: auto;
}

/* 整屏遮罩。z-index 取 -1：.ai-assistant 自己是个层叠上下文（fixed + 1900），
   遮罩在里面垫在面板和按钮后面，整体仍压在页面内容之上、Element 弹窗之下。 */
.ai-assistant-mask {
  position: fixed;
  inset: 0;
  z-index: -1;
  background: rgb(0 0 0 / 45%);
}

.ai-assistant-mask-enter-active {
  transition: opacity 220ms ease-out;
}

.ai-assistant-mask-leave-active {
  transition: opacity 160ms ease-in;
}

.ai-assistant-mask-enter-from,
.ai-assistant-mask-leave-to {
  opacity: 0;
}

.ai-assistant-panel {
  display: flex;
  width: min(1040px, calc(100vw - 48px));
  height: min(780px, calc(100vh - 100px));
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  outline: none;
  box-shadow: 0 18px 60px rgb(15 23 42 / 22%);
  transform-origin: right bottom;
  flex-direction: column;
}

.ai-assistant-head {
  display: flex;
  padding: 12px 16px;
  color: #fff;
  background: linear-gradient(135deg, var(--el-color-primary), var(--el-color-primary-dark-2));
  flex: none;
  gap: 12px;
  align-items: center;
}

.ai-assistant-avatar {
  display: inline-flex;
  width: 34px;
  height: 34px;
  font-size: 18px;
  background: rgb(255 255 255 / 20%);
  border-radius: 50%;
  flex: none;
  align-items: center;
  justify-content: center;
}

.ai-assistant-heading {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.ai-assistant-heading strong {
  font-size: 15px;
  line-height: 1.3;
}

.ai-assistant-subtitle {
  overflow: hidden;
  font-size: 12px;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.88;
}

.ai-assistant-minimize {
  display: inline-flex;
  width: 32px;
  height: 32px;
  font-size: 18px;
  color: inherit;
  cursor: pointer;
  background: transparent;
  border: none;
  border-radius: 50%;
  flex: none;
  align-items: center;
  justify-content: center;
  transition: background-color 160ms ease;
}

.ai-assistant-minimize:hover,
.ai-assistant-minimize:focus-visible {
  background: rgb(255 255 255 / 22%);
}

.ai-assistant-body {
  position: relative;
  display: flex;
  min-height: 0;
  background: var(--el-bg-color-page);
  flex: 1;
  flex-direction: column;
}

.ai-assistant-body > :deep(*) {
  min-height: 0;
  flex: 1;
}

.ai-assistant-launcher {
  display: inline-flex;
  height: 48px;
  padding: 0 18px 0 14px;
  font: inherit;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  background: linear-gradient(135deg, var(--el-color-primary), var(--el-color-primary-dark-2));
  border: none;
  border-radius: 24px;
  box-shadow: 0 8px 24px rgb(37 99 235 / 38%);
  align-items: center;
  transition:
    padding 260ms ease,
    box-shadow 160ms ease,
    transform 160ms ease;
}

.ai-assistant-launcher:hover {
  box-shadow: 0 12px 30px rgb(37 99 235 / 46%);
  transform: translateY(-2px);
}

.ai-assistant-launcher:focus-visible {
  outline: 3px solid var(--el-color-primary-light-5);
  outline-offset: 2px;
}

.ai-assistant-launcher-icon {
  font-size: 22px;
}

/* 展开时按钮收成圆形，只留一个收起箭头，和客服窗口的开合一个样子。 */
.ai-assistant-launcher-label {
  max-width: 6em;
  margin-left: 8px;
  overflow: hidden;
  white-space: nowrap;
  opacity: 1;
  transition:
    max-width 260ms ease,
    margin-left 260ms ease,
    opacity 200ms ease;
}

.ai-assistant-launcher.is-open {
  width: 48px;
  padding: 0 13px;
}

.ai-assistant-launcher.is-open .ai-assistant-launcher-label {
  max-width: 0;
  margin-left: 0;
  opacity: 0;
}

.ai-assistant-pop-enter-active {
  transition:
    opacity 200ms ease-out,
    transform 280ms cubic-bezier(0.2, 0.9, 0.3, 1.08);
}

.ai-assistant-pop-leave-active {
  transition:
    opacity 150ms ease-in,
    transform 180ms ease-in;
}

.ai-assistant-pop-enter-from,
.ai-assistant-pop-leave-to {
  opacity: 0;
  transform: translateY(18px) scale(0.9);
}

/*
 * 里面的审查工作台按「整页宽度」决定分栏：窄于 1280 就改成单栏（工位版）或者根本不改（旧版，窄了对话栏被挤成一条缝）。
 * 现在它装在一个固定宽度的面板里，该看面板宽，不该看整页宽，所以这里按面板的宽度重新定：
 * 面板够宽（页宽 900 以上）保持左右两栏，人工结论和快捷操作固定在右边；窄了才叠成单栏。
 */
@media (900px < width < 1280px) {
  .ai-assistant-body :deep(.review-b-shell.is-embedded.is-workstation-mode .review-b-layout) {
    padding: 0;
    overflow: hidden;
    grid-template-columns: minmax(0, 1fr) minmax(290px, 330px);
    grid-template-rows: none;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded.is-workstation-mode .conversation-column) {
    height: 100%;
    overflow-y: auto;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded.is-workstation-mode .context-panel) {
    height: 100%;
    max-height: 100%;
    overflow-y: auto;
  }
}

@media (width <= 900px) {
  /* 单栏时让整个面板内容在 layout 里滚，输入框钉在面板底。
     输入框是 sticky，只在它所属的块里有效；对话列和右边栏是两个并排的块，
     输入框在对话列里，滚到右边栏那一段它就跟着对话列滚走了。
     所以把对话列拆掉（display: contents），它的子项直接成为 layout 的子项，
     输入框的「块」就变成整个 layout，一路钉到底。 */
  .ai-assistant-body {
    overflow-y: auto;
  }

  /* sticky 的「块」必须比滚动区高：内容撑高的壳和 layout 不能再各自卡死高度、各自滚动，
     不然 sticky 只能在那个固定高度的盒子里动，滚过一屏就脱钩（实测）。
     滚动交给 .ai-assistant-body，壳和 layout 随内容长高。 */
  .ai-assistant-body :deep(.review-b-shell.is-embedded) {
    height: auto;
    overflow: visible;
    flex: none;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded .review-b-layout) {
    display: flex;
    height: auto;
    padding: 14px 16px 0;
    overflow: visible;
    flex: none;
    flex-direction: column;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded .review-b-layout > *) {
    flex-shrink: 0;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded .conversation-column) {
    display: contents;
  }

  /* sticky 只在元素「自然位置」落在可视区下面时才钉住；输入框排在右边栏前面，滚过去它就脱钩。
     用 order 把它排到最后，自然位置在整个内容的底部，从头到尾都钉着。 */
  .ai-assistant-body :deep(.review-b-shell.is-embedded .composer-card) {
    order: 10;
    margin-top: 0;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded .context-panel) {
    margin: 12px 0 14px;
  }

  .ai-assistant-body :deep(.review-b-shell.is-embedded .context-panel) {
    position: static;
    height: auto;
    max-height: none;
    overflow: visible;
  }
}

@media (width <= 640px) {
  .ai-assistant {
    right: 12px;
    bottom: 12px;
  }

  .ai-assistant-panel {
    width: calc(100vw - 24px);
    height: calc(100dvh - 84px);
    border-radius: 14px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ai-assistant-pop-enter-active,
  .ai-assistant-pop-leave-active,
  .ai-assistant-mask-enter-active,
  .ai-assistant-mask-leave-active,
  .ai-assistant-launcher,
  .ai-assistant-launcher-label {
    transition-duration: 0.01ms;
  }
}
</style>
