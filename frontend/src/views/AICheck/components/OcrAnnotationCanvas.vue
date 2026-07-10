<script setup lang="ts">
import Konva from 'konva'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

export type OcrAnnotationCanvasSection = 'fields' | 'tables' | 'seals'
export type OcrAnnotationCanvasTool = 'select' | 'pan' | OcrAnnotationCanvasSection
export type OcrAnnotationCanvasItem = {
  id: string
  type: OcrAnnotationCanvasSection
  label: string
  value?: string
  bbox: [number, number, number, number]
  pageNo?: number
}

const props = withDefaults(
  defineProps<{
    previewUrl?: string
    pageNo?: number
    pageSize: { width: number; height: number }
    items: OcrAnnotationCanvasItem[]
    selectedId?: string
    tool?: OcrAnnotationCanvasTool
    zoom?: number
    disabled?: boolean
  }>(),
  {
    previewUrl: '',
    pageNo: 1,
    selectedId: '',
    tool: 'select',
    zoom: 1,
    disabled: false
  }
)

const emit = defineEmits<{
  select: [id: string]
  quickEdit: [id: string]
  create: [payload: { type: OcrAnnotationCanvasSection; bbox: [number, number, number, number] }]
  update: [payload: { id: string; bbox: [number, number, number, number] }]
  zoom: [delta: number]
  zoomReset: []
  imageLoad: []
  imageError: []
}>()

const containerRef = ref<HTMLDivElement | null>(null)
const viewportRef = ref<HTMLDivElement | null>(null)
const stageBox = ref({ width: 720, height: 540, scale: 1 })
const imageLoading = ref(false)
const imageFailed = ref(false)
const isPanning = ref(false)

let stage: Konva.Stage | null = null
let backgroundLayer: Konva.Layer | null = null
let roiLayer: Konva.Layer | null = null
let transformerLayer: Konva.Layer | null = null
let transformer: Konva.Transformer | null = null
let resizeObserver: ResizeObserver | null = null
let pageImage: HTMLImageElement | null = null
let loadToken = 0
let drawingRect: Konva.Rect | null = null
let drawingStart: { x: number; y: number; type: OcrAnnotationCanvasSection } | null = null
let panStart: { x: number; y: number; scrollLeft: number; scrollTop: number } | null = null

const pageWidth = computed(() => Math.max(1, Number(props.pageSize?.width || 1)))
const pageHeight = computed(() => Math.max(1, Number(props.pageSize?.height || 1)))
const currentPageItems = computed(() =>
  props.items.filter(
    (item) => Number(item.pageNo || props.pageNo || 1) === Number(props.pageNo || 1)
  )
)

const toneMap: Record<
  OcrAnnotationCanvasSection,
  { stroke: string; idleFill: string; activeFill: string; label: string; text: string }
> = {
  fields: {
    stroke: '#2563eb',
    idleFill: 'rgba(37, 99, 235, 0.04)',
    activeFill: 'rgba(37, 99, 235, 0.1)',
    label: '#1d4ed8',
    text: '#ffffff'
  },
  tables: {
    stroke: '#16a34a',
    idleFill: 'rgba(22, 163, 74, 0.04)',
    activeFill: 'rgba(22, 163, 74, 0.1)',
    label: '#15803d',
    text: '#ffffff'
  },
  seals: {
    stroke: '#dc2626',
    idleFill: 'rgba(220, 38, 38, 0.04)',
    activeFill: 'rgba(220, 38, 38, 0.1)',
    label: '#b42318',
    text: '#ffffff'
  }
}

const canEdit = computed(() => !props.disabled && !imageFailed.value && Boolean(props.previewUrl))
const canPan = computed(() => !props.disabled && Boolean(props.previewUrl))
const isPanTool = computed(() => props.tool === 'pan')

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const normalizeStageBox = (bbox: [number, number, number, number]) => {
  const scale = stageBox.value.scale
  const x1 = clamp(Math.min(bbox[0], bbox[2]) * scale, 0, stageBox.value.width)
  const y1 = clamp(Math.min(bbox[1], bbox[3]) * scale, 0, stageBox.value.height)
  const x2 = clamp(Math.max(bbox[0], bbox[2]) * scale, 0, stageBox.value.width)
  const y2 = clamp(Math.max(bbox[1], bbox[3]) * scale, 0, stageBox.value.height)
  return {
    x: x1,
    y: y1,
    width: Math.max(1, x2 - x1),
    height: Math.max(1, y2 - y1)
  }
}

const stageBoxToPageBbox = (
  x: number,
  y: number,
  width: number,
  height: number
): [number, number, number, number] => {
  const scale = stageBox.value.scale || 1
  const x1 = clamp(Math.round(x / scale), 0, pageWidth.value)
  const y1 = clamp(Math.round(y / scale), 0, pageHeight.value)
  const x2 = clamp(Math.round((x + width) / scale), 0, pageWidth.value)
  const y2 = clamp(Math.round((y + height) / scale), 0, pageHeight.value)
  return [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)]
}

const calculateStageSize = () => {
  const containerWidth = Math.max(320, containerRef.value?.clientWidth || 720)
  const maxStageHeight = Math.min(920, Math.max(460, window.innerHeight - 260))
  const fitScale = Math.min(containerWidth / pageWidth.value, maxStageHeight / pageHeight.value)
  const scale = Math.max(0.05, fitScale * Math.max(0.25, Math.min(Number(props.zoom || 1), 3)))
  stageBox.value = {
    width: Math.max(1, Math.round(pageWidth.value * scale)),
    height: Math.max(1, Math.round(pageHeight.value * scale)),
    scale
  }
  if (stage) {
    stage.width(stageBox.value.width)
    stage.height(stageBox.value.height)
  }
}

const setCursor = (cursor: string) => {
  if (stage?.container()) {
    stage.container().style.cursor = cursor
  }
}

const currentCursor = () => {
  if (props.disabled) return 'not-allowed'
  if (isPanning.value) return 'grabbing'
  if (isPanTool.value) return 'grab'
  return props.tool === 'select' ? 'default' : 'crosshair'
}

const selectedGroup = () =>
  roiLayer?.findOne(
    (node) => node.getAttr('annotationId') === props.selectedId
  ) as Konva.Group | null

const syncTransformer = () => {
  if (!transformerLayer) return
  transformerLayer.destroyChildren()
  transformer = null
  const group = selectedGroup()
  if (!group || props.disabled) {
    transformerLayer.batchDraw()
    return
  }
  transformer = new Konva.Transformer({
    nodes: [group],
    rotateEnabled: false,
    ignoreStroke: false,
    borderStroke: '#0f172a',
    borderStrokeWidth: 1,
    anchorFill: '#ffffff',
    anchorStroke: '#0f172a',
    anchorStrokeWidth: 1,
    anchorSize: 9,
    enabledAnchors: [
      'top-left',
      'top-center',
      'top-right',
      'middle-left',
      'middle-right',
      'bottom-left',
      'bottom-center',
      'bottom-right'
    ],
    boundBoxFunc: (_oldBox, newBox) => {
      const minSize = 12
      const width = Math.max(minSize, Math.min(newBox.width, stageBox.value.width))
      const height = Math.max(minSize, Math.min(newBox.height, stageBox.value.height))
      return {
        ...newBox,
        x: clamp(newBox.x, 0, Math.max(0, stageBox.value.width - width)),
        y: clamp(newBox.y, 0, Math.max(0, stageBox.value.height - height)),
        width,
        height
      }
    }
  })
  transformerLayer.add(transformer)
  transformerLayer.batchDraw()
}

const emitGroupBbox = (group: Konva.Group) => {
  const rect = group.findOne('.roi-rect') as Konva.Rect | null
  if (!rect) return
  emit('update', {
    id: String(group.getAttr('annotationId') || ''),
    bbox: stageBoxToPageBbox(
      group.x(),
      group.y(),
      Math.max(1, rect.width()),
      Math.max(1, rect.height())
    )
  })
}

const textWidth = (value: string, fontSize = 13) => {
  const visibleChars = Array.from(value)
  return visibleChars.reduce(
    (sum, char) => sum + (/[\u4e00-\u9fff]/.test(char) ? fontSize : fontSize * 0.58),
    0
  )
}

const previewText = (item: OcrAnnotationCanvasItem) => {
  if (item.type === 'tables') {
    const raw = String(item.value || '').trim()
    if (!raw) return '待填写表格内容'
    const rows = raw
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.includes('|') && !/^\|?\s*:?-{3,}/.test(line))
    const columnCount = rows[0]
      ? rows[0].replace(/^\|/, '').replace(/\|$/, '').split('|').length
      : 0
    if (rows.length) {
      return `已识别表格内容：${rows.length} 行${columnCount ? ` × ${columnCount} 列` : ''}`
    }
    return '已填写表格内容'
  }
  const text = String(item.value || '')
    .replace(/\s+/g, ' ')
    .trim()
  if (text) return text.length > 96 ? `${text.slice(0, 96)}...` : text
  return '待填写文字'
}

const canvasLabelText = (item: OcrAnnotationCanvasItem) => {
  const fallback = item.type === 'fields' ? '字段' : item.type === 'tables' ? '表格' : '印章'
  const text = String(item.label || fallback)
    .replace(/\s+/g, ' ')
    .trim()
  return text.length > 18 ? `${text.slice(0, 18)}...` : text
}

const addItemNode = (item: OcrAnnotationCanvasItem) => {
  if (!roiLayer) return
  const box = normalizeStageBox(item.bbox)
  const tone = toneMap[item.type]
  const isSelected = item.id === props.selectedId
  const group = new Konva.Group({
    x: box.x,
    y: box.y,
    width: box.width,
    height: box.height,
    draggable: canEdit.value && props.tool === 'select',
    annotationId: item.id,
    name: 'annotation-group',
    dragBoundFunc: (pos) => ({
      x: clamp(pos.x, 0, Math.max(0, stageBox.value.width - box.width)),
      y: clamp(pos.y, 0, Math.max(0, stageBox.value.height - box.height))
    })
  })
  const rect = new Konva.Rect({
    width: box.width,
    height: box.height,
    fill: isSelected ? tone.activeFill : tone.idleFill,
    stroke: tone.stroke,
    strokeWidth: isSelected ? 2 : 1,
    opacity: isSelected ? 1 : 0.46,
    hitStrokeWidth: 10,
    cornerRadius: 3,
    name: 'roi-rect'
  })
  const labelText = canvasLabelText(item)
  const badgeWidth = Math.max(54, Math.min(box.width, labelText.length * 13 + 24))
  const badge = new Konva.Rect({
    x: 0,
    y: -24,
    width: badgeWidth,
    height: 22,
    fill: tone.label,
    cornerRadius: 4,
    opacity: 1,
    visible: isSelected
  })
  const text = new Konva.Text({
    x: 8,
    y: -20,
    width: Math.max(24, badgeWidth - 14),
    height: 18,
    text: labelText,
    fill: tone.text,
    fontSize: 13,
    fontStyle: 'bold',
    wrap: 'none',
    ellipsis: true,
    visible: isSelected
  })
  const valuePreview = previewText(item)
  const previewWidth = Math.max(120, Math.min(420, textWidth(valuePreview) + 26))
  const previewY = Math.min(box.height + 8, Math.max(8, box.height - 2))
  const previewGroup = new Konva.Group({
    x: 0,
    y: previewY,
    visible: isSelected,
    listening: false
  })
  const previewBackground = new Konva.Rect({
    width: previewWidth,
    height: 30,
    fill: valuePreview === '待填写文字' ? '#fff7ed' : '#ffffff',
    stroke: valuePreview === '待填写文字' ? '#fdba74' : tone.stroke,
    strokeWidth: 1,
    cornerRadius: 5,
    shadowColor: '#0f172a',
    shadowOpacity: 0.16,
    shadowBlur: 14,
    shadowOffset: { x: 0, y: 8 }
  })
  const previewLabel = new Konva.Text({
    x: 10,
    y: 7,
    width: previewWidth - 20,
    height: 18,
    text: valuePreview,
    fill: valuePreview === '待填写文字' ? '#9a3412' : '#0f172a',
    fontSize: 13,
    fontStyle: 'bold',
    wrap: 'none',
    ellipsis: true
  })
  previewGroup.add(previewBackground, previewLabel)
  group.add(rect, badge, text, previewGroup)
  group.on('mouseenter', () => {
    setCursor(props.tool === 'select' ? 'move' : currentCursor())
    previewGroup.visible(isSelected)
    roiLayer?.batchDraw()
  })
  group.on('mouseleave', () => {
    setCursor(currentCursor())
    previewGroup.visible(isSelected)
    roiLayer?.batchDraw()
  })
  group.on('click tap', (event) => {
    event.cancelBubble = true
    emit('select', item.id)
  })
  group.on('dblclick dbltap', (event) => {
    event.cancelBubble = true
    emit('quickEdit', item.id)
  })
  group.on('dragstart', () => {
    emit('select', item.id)
  })
  group.on('dragmove', () => {
    const rectNode = group.findOne('.roi-rect') as Konva.Rect | null
    if (!rectNode) return
    group.x(clamp(group.x(), 0, Math.max(0, stageBox.value.width - rectNode.width())))
    group.y(clamp(group.y(), 0, Math.max(0, stageBox.value.height - rectNode.height())))
  })
  group.on('dragend', () => emitGroupBbox(group))
  group.on('transformstart', () => {
    emit('select', item.id)
  })
  group.on('transformend', () => {
    const rectNode = group.findOne('.roi-rect') as Konva.Rect | null
    if (!rectNode) return
    const nextWidth = Math.max(12, rectNode.width() * group.scaleX())
    const nextHeight = Math.max(12, rectNode.height() * group.scaleY())
    group.scaleX(1)
    group.scaleY(1)
    group.x(clamp(group.x(), 0, Math.max(0, stageBox.value.width - nextWidth)))
    group.y(clamp(group.y(), 0, Math.max(0, stageBox.value.height - nextHeight)))
    group.width(nextWidth)
    group.height(nextHeight)
    rectNode.width(nextWidth)
    rectNode.height(nextHeight)
    emitGroupBbox(group)
  })
  roiLayer.add(group)
}

const renderCanvas = () => {
  if (!stage || !backgroundLayer || !roiLayer) return
  calculateStageSize()
  backgroundLayer.destroyChildren()
  roiLayer.destroyChildren()
  const background = new Konva.Rect({
    x: 0,
    y: 0,
    width: stageBox.value.width,
    height: stageBox.value.height,
    fill: '#f8fafc',
    stroke: '#d7e2f1',
    strokeWidth: 1,
    listening: true,
    name: 'annotation-background'
  })
  backgroundLayer.add(background)
  if (pageImage) {
    backgroundLayer.add(
      new Konva.Image({
        image: pageImage,
        x: 0,
        y: 0,
        width: stageBox.value.width,
        height: stageBox.value.height,
        listening: false
      })
    )
  }
  currentPageItems.value.forEach(addItemNode)
  backgroundLayer.batchDraw()
  roiLayer.batchDraw()
  syncTransformer()
}

const loadImage = () => {
  const source = String(props.previewUrl || '')
  pageImage = null
  imageFailed.value = false
  if (!source) {
    imageLoading.value = false
    renderCanvas()
    return
  }
  imageLoading.value = true
  const token = ++loadToken
  const image = new Image()
  image.onload = () => {
    if (token !== loadToken) return
    imageLoading.value = false
    imageFailed.value = false
    pageImage = image
    emit('imageLoad')
    renderCanvas()
  }
  image.onerror = () => {
    if (token !== loadToken) return
    imageLoading.value = false
    imageFailed.value = true
    pageImage = null
    emit('imageError')
    renderCanvas()
  }
  image.src = source
}

const retryLoadImage = () => {
  loadImage()
}

const handleCanvasWheel = (event: WheelEvent) => {
  if (!event.ctrlKey && !event.metaKey) return
  event.preventDefault()
  emit('zoom', event.deltaY > 0 ? -0.1 : 0.1)
}

const targetIsRoi = (target: Konva.Node) =>
  target.hasName('annotation-group') || Boolean(target.findAncestor('.annotation-group'))

const pointerFromEvent = (event: MouseEvent | TouchEvent) => {
  if ('touches' in event) {
    const touch = event.touches[0] || event.changedTouches[0]
    return touch ? { x: touch.clientX, y: touch.clientY } : null
  }
  return { x: event.clientX, y: event.clientY }
}

const updatePanFromWindow = (event: MouseEvent | TouchEvent) => {
  if (!panStart || !containerRef.value) return
  const pointer = pointerFromEvent(event)
  if (!pointer) return
  event.preventDefault()
  containerRef.value.scrollLeft = panStart.scrollLeft - (pointer.x - panStart.x)
  containerRef.value.scrollTop = panStart.scrollTop - (pointer.y - panStart.y)
}

const detachPanListeners = () => {
  window.removeEventListener('mousemove', updatePanFromWindow)
  window.removeEventListener('mouseup', finishPanFromWindow)
  window.removeEventListener('touchmove', updatePanFromWindow)
  window.removeEventListener('touchend', finishPanFromWindow)
  window.removeEventListener('touchcancel', finishPanFromWindow)
}

const finishPanFromWindow = () => {
  panStart = null
  isPanning.value = false
  detachPanListeners()
  setCursor(currentCursor())
}

const startPan = (event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => {
  if (!containerRef.value || !canPan.value) return
  const pointer = pointerFromEvent(event.evt)
  if (!pointer) return
  event.cancelBubble = true
  event.evt.preventDefault()
  drawingStart = null
  drawingRect?.destroy()
  drawingRect = null
  panStart = {
    x: pointer.x,
    y: pointer.y,
    scrollLeft: containerRef.value.scrollLeft,
    scrollTop: containerRef.value.scrollTop
  }
  isPanning.value = true
  setCursor('grabbing')
  window.addEventListener('mousemove', updatePanFromWindow)
  window.addEventListener('mouseup', finishPanFromWindow)
  window.addEventListener('touchmove', updatePanFromWindow, { passive: false })
  window.addEventListener('touchend', finishPanFromWindow)
  window.addEventListener('touchcancel', finishPanFromWindow)
}

const startDrawing = () => {
  if (!stage || !roiLayer || !canEdit.value || props.tool === 'select') return
  if (props.tool === 'pan') return
  const position = stage.getPointerPosition()
  if (!position) return
  drawingStart = { x: position.x, y: position.y, type: props.tool }
  drawingRect = new Konva.Rect({
    x: position.x,
    y: position.y,
    width: 1,
    height: 1,
    fill: toneMap[props.tool].activeFill,
    stroke: toneMap[props.tool].stroke,
    strokeWidth: 1.5,
    opacity: 0.78,
    dash: [6, 4],
    cornerRadius: 3,
    listening: false
  })
  roiLayer.add(drawingRect)
  roiLayer.batchDraw()
}

const updateDrawing = () => {
  if (!stage || !roiLayer || !drawingStart || !drawingRect) return
  const position = stage.getPointerPosition()
  if (!position) return
  const x1 = clamp(Math.min(drawingStart.x, position.x), 0, stageBox.value.width)
  const y1 = clamp(Math.min(drawingStart.y, position.y), 0, stageBox.value.height)
  const x2 = clamp(Math.max(drawingStart.x, position.x), 0, stageBox.value.width)
  const y2 = clamp(Math.max(drawingStart.y, position.y), 0, stageBox.value.height)
  drawingRect.setAttrs({
    x: x1,
    y: y1,
    width: Math.max(1, x2 - x1),
    height: Math.max(1, y2 - y1)
  })
  roiLayer.batchDraw()
}

const finishDrawing = () => {
  if (!roiLayer || !drawingStart || !drawingRect) return
  const rect = drawingRect
  const type = drawingStart.type
  const width = rect.width()
  const height = rect.height()
  const x = rect.x()
  const y = rect.y()
  drawingRect.destroy()
  drawingRect = null
  drawingStart = null
  roiLayer.batchDraw()
  if (width < 10 || height < 10) return
  emit('create', { type, bbox: stageBoxToPageBbox(x, y, width, height) })
}

const setupStage = () => {
  if (!viewportRef.value) return
  calculateStageSize()
  stage = new Konva.Stage({
    container: viewportRef.value,
    width: stageBox.value.width,
    height: stageBox.value.height
  })
  backgroundLayer = new Konva.Layer()
  roiLayer = new Konva.Layer()
  transformerLayer = new Konva.Layer()
  stage.add(backgroundLayer, roiLayer, transformerLayer)
  stage.on('mousedown touchstart', (event) => {
    if (!stage) return
    if (isPanTool.value) {
      startPan(event)
      return
    }
    if (targetIsRoi(event.target)) return
    if (props.tool === 'select') {
      emit('select', '')
      return
    }
    startDrawing()
  })
  stage.on('mousemove touchmove', updateDrawing)
  stage.on('mouseup touchend', finishDrawing)
  stage.on('mouseleave', () => {
    if (panStart) finishPanFromWindow()
    if (drawingStart) finishDrawing()
  })
  stage.on('wheel', (event) => handleCanvasWheel(event.evt))
  stage.on('dblclick dbltap', (event) => {
    if (targetIsRoi(event.target)) return
    emit('zoomReset')
  })
}

onMounted(() => {
  setupStage()
  resizeObserver = new ResizeObserver(() => {
    calculateStageSize()
    renderCanvas()
  })
  if (containerRef.value) resizeObserver.observe(containerRef.value)
  window.addEventListener('resize', renderCanvas)
  nextTick(() => {
    calculateStageSize()
    loadImage()
    renderCanvas()
  })
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', renderCanvas)
  detachPanListeners()
  stage?.destroy()
  stage = null
})

watch(
  () => props.previewUrl,
  () => loadImage()
)

watch(
  () => [
    props.items,
    props.selectedId,
    props.tool,
    props.disabled,
    props.pageNo,
    props.zoom,
    props.pageSize.width,
    props.pageSize.height
  ],
  () => renderCanvas(),
  { deep: true }
)
</script>

<template>
  <div
    ref="containerRef"
    class="ocr-annotation-canvas"
    title="选择模式拖动 ROI；拖动画布模式平移；Ctrl/⌘ + 滚轮缩放，双击适配"
  >
    <div class="ocr-annotation-canvas__status">
      <span>{{ pageSize.width }} × {{ pageSize.height }}</span>
      <strong>{{ Math.round((zoom || 1) * 100) }}%</strong>
    </div>
    <div
      ref="viewportRef"
      class="ocr-annotation-canvas__stage"
      :class="{
        'is-drawing': tool !== 'select' && tool !== 'pan',
        'is-panning': isPanTool,
        'is-pan-active': isPanning,
        'is-disabled': disabled,
        'is-loading': imageLoading,
        'is-error': imageFailed
      }"
      :style="{ width: `${stageBox.width}px`, height: `${stageBox.height}px` }"
      role="img"
      aria-label="OCR 标注画布"
    ></div>
    <div v-if="imageLoading" class="ocr-annotation-canvas__overlay">
      <strong>正在加载页图</strong>
      <span>加载完成后可以拖拽和框选 ROI。</span>
    </div>
    <div v-else-if="imageFailed || !previewUrl" class="ocr-annotation-canvas__overlay is-error">
      <strong>{{ imageFailed ? '页图加载失败' : '暂无可标注页图' }}</strong>
      <span>请重新上传文件并系统预标注，已有草稿对象会继续保留。</span>
      <button v-if="imageFailed && previewUrl" type="button" @click="retryLoadImage">
        重新加载页图
      </button>
    </div>
  </div>
</template>

<style scoped lang="less">
.ocr-annotation-canvas {
  position: relative;
  min-width: 0;
  min-height: 460px;
  overflow: auto;
  overscroll-behavior: contain;
  background: linear-gradient(90deg, rgb(37 99 235 / 7%) 1px, transparent 1px),
    linear-gradient(rgb(37 99 235 / 7%) 1px, transparent 1px), #f8fafc;
  background-size: 40px 40px;
  border: 1px solid #cbd8ea;
  border-radius: 8px;
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 70%);
}

.ocr-annotation-canvas__stage {
  position: relative;
  margin: 18px auto;
  overflow: hidden;
  background: #f8fafc;
  border-radius: 4px;
  box-shadow: 0 10px 36px rgb(15 23 42 / 10%);
  touch-action: none;
}

.ocr-annotation-canvas__stage.is-drawing {
  cursor: crosshair;
}

.ocr-annotation-canvas__stage.is-panning {
  cursor: grab;
}

.ocr-annotation-canvas__stage.is-pan-active {
  cursor: grabbing;
}

.ocr-annotation-canvas__stage.is-disabled {
  cursor: not-allowed;
}

.ocr-annotation-canvas__status {
  position: sticky;
  top: 10px;
  left: 10px;
  z-index: 2;
  display: inline-flex;
  min-height: 30px;
  padding: 5px 9px;
  margin: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #1f2d3d;
  background: rgb(255 255 255 / 92%);
  border: 1px solid #dbe8f7;
  border-radius: 999px;
  align-items: center;
  gap: 8px;
}

.ocr-annotation-canvas__status strong {
  color: #2563eb;
}

.ocr-annotation-canvas__overlay {
  position: absolute;
  inset: 0;
  z-index: 3;
  display: flex;
  flex-direction: column;
  padding: 24px;
  color: #64748b;
  text-align: center;
  pointer-events: auto;
  background: rgb(248 250 252 / 84%);
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.ocr-annotation-canvas__overlay strong {
  font-size: 16px;
  font-weight: 600;
  color: #172033;
}

.ocr-annotation-canvas__overlay span {
  max-width: min(520px, 90%);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.6;
}

.ocr-annotation-canvas__overlay.is-error {
  color: #b42318;
  background: linear-gradient(180deg, rgb(255 241 240 / 92%), rgb(255 255 255 / 92%));
}

.ocr-annotation-canvas__overlay.is-error strong {
  color: #991b1b;
}

.ocr-annotation-canvas__overlay button {
  min-height: 36px;
  padding: 0 14px;
  margin-top: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  background: #2563eb;
  border: 0;
  border-radius: 6px;
  box-shadow: 0 8px 18px rgb(37 99 235 / 20%);
}

.ocr-annotation-canvas__overlay button:hover {
  background: #1d4ed8;
}
</style>
