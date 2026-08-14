/**
 * OCR 能力测试结果的数据整形。
 *
 * 从 FdeConsole.vue 搬出来的 39 个函数：把 OCR 能力测试返回的原始结果
 * 整形成表格预览、结构化行、ROI 区域等界面要显示的形状。
 *
 * ## 为什么单独成模块
 *
 * FdeConsole.vue 29,203 行（script 10,875 / template 10,179 / style 8,147），
 * 比 routes.py 还大。这批函数不碰任何 ref/reactive，纯输入输出——留在 SFC 里
 * 既没法单测也没人找得到，而它们算错不会报错，只会让预览表少一列、
 * ROI 框画偏一点。
 *
 * 只搬传递引用全在本组内的 39 个，边界由 TypeScript 解析器给出。
 * 同家族另有 63 个成员因为回引 SFC 里的 reactive 状态（actionLoading、
 * ocrAnnotation、ocrSubpage）而留在原处——那需要先把状态与整形分开，是另一件事。
 */

import type { FdeOcrCapabilityTestDetailPayload } from '@/api/aicheck'
import { friendlyFieldLabel } from './components/auditLabels'

export const resolveOcrCapabilityPreviewType = (file?: File | null) => {
  const text = `${file?.type || ''} ${file?.name || ''}`.toLowerCase()
  if (/pdf/.test(text)) return 'pdf'
  if (/image|png|jpe?g|webp|gif/.test(text)) return 'image'
  return 'unsupported'
}

export const stringifyOcrCapabilityText = (value: unknown): string => {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) {
    return value
      .map((item) => stringifyOcrCapabilityText(item))
      .filter(Boolean)
      .join('\n')
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    return stringifyOcrCapabilityText(
      record.text ??
        record.fullText ??
        record.rawText ??
        record.plainText ??
        record.content ??
        record.value ??
        record.fieldValue ??
        record.ocrText
    )
  }
  return ''
}

export type OcrCapabilityRoiTone = 'blue' | 'green' | 'orange' | 'red' | 'purple'

export type OcrCapabilityRoi = {
  id: string
  type: string
  tone: OcrCapabilityRoiTone
  pageNo: number
  label: string
  text: string
  bbox: [number, number, number, number]
  confidence?: number
  source?: string
}

export type OcrCapabilityStructuredRow = {
  id: string
  pageNo: number
  type: string
  name: string
  value: string
  bboxText: string
  confidence?: number
  source: string
}

export type OcrCapabilitySealDisplayRow = {
  id: string
  title: string
  colorLabel: string
  typeLabel: string
  status: string
  tagType: 'success' | 'warning' | 'danger' | 'info'
  pageNo: number
  bboxText: string
  confidence?: number
  source: string
  contentLines: string[]
  meta: Array<{ label: string; value: string }>
}

export type OcrCapabilityTablePreview = {
  id: string
  title: string
  meta: Array<{ label: string; value: string }>
  columns: Array<{ key: string; label: string }>
  rows: Array<{ id: string; cells: Record<string, string> }>
}

export const ocrCapabilityRoiToneTypeMap: Record<
  OcrCapabilityRoiTone,
  'primary' | 'success' | 'warning' | 'danger' | 'info'
> = {
  blue: 'primary',
  green: 'success',
  orange: 'warning',
  red: 'danger',
  purple: 'info'
}

export const normalizeOcrCapabilityBbox = (
  bbox: unknown
): [number, number, number, number] | null => {
  if (!Array.isArray(bbox) || bbox.length < 4) return null
  let values: number[] = []
  if (Array.isArray(bbox[0])) {
    const points = bbox
      .filter((point): point is unknown[] => Array.isArray(point) && point.length >= 2)
      .map((point) => [Number(point[0]), Number(point[1])])
      .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
    if (!points.length) return null
    const xs = points.map(([x]) => x)
    const ys = points.map(([, y]) => y)
    values = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
  } else {
    values = bbox.slice(0, 4).map((value) => Number(value))
  }
  if (values.some((value) => !Number.isFinite(value))) return null
  const [rawX1, rawY1, rawX2, rawY2] = values
  const x1 = Math.min(rawX1, rawX2)
  const y1 = Math.min(rawY1, rawY2)
  const x2 = Math.max(rawX1, rawX2)
  const y2 = Math.max(rawY1, rawY2)
  if (x2 <= x1 || y2 <= y1) return null
  return [x1, y1, x2, y2]
}

export const ocrCapabilityRoiText = (record: Record<string, unknown>) =>
  stringifyOcrCapabilityText(
    record.text ??
      record.fullText ??
      record.fieldValue ??
      record.value ??
      record.sealName ??
      record.sealType ??
      record.label ??
      record.type
  )

export const ocrCapabilityStructuredValue = (record: Record<string, unknown>) =>
  stringifyOcrCapabilityText(
    record.fieldValue ??
      record.value ??
      record.text ??
      record.fullText ??
      record.rawText ??
      record.content ??
      record.sealName ??
      record.sealType ??
      record.tableName ??
      record.label
  )

export const ocrCapabilityTableSummary = (record: Record<string, unknown>) => {
  const rowCount = Number(record.rowCount ?? record.rows ?? 0)
  const columnCount = Number(record.columnCount ?? record.columns ?? 0)
  const cellCount = Array.isArray(record.cells) ? record.cells.length : 0
  const parts = [
    rowCount ? `${rowCount} 行` : '',
    columnCount ? `${columnCount} 列` : '',
    cellCount ? `${cellCount} 单元格` : ''
  ].filter(Boolean)
  return parts.join(' / ') || ocrCapabilityStructuredValue(record) || '表格结构'
}

export const cleanOcrCapabilityTableText = (value: unknown) =>
  stringifyOcrCapabilityText(value)
    .replace(/\s*\n+\s*/g, ' / ')
    .replace(/\s+/g, ' ')
    .trim()

export const uniqueOcrCapabilityTableKey = (base: string, used: Set<string>) => {
  let key = base || `col_${used.size + 1}`
  let index = 2
  while (used.has(key)) {
    key = `${base}_${index}`
    index += 1
  }
  used.add(key)
  return key
}

export const ocrCapabilityBboxText = (bbox: unknown) => {
  const normalized = normalizeOcrCapabilityBbox(bbox)
  return normalized ? normalized.map((value) => Math.round(value * 100) / 100).join(', ') : '-'
}

export const normalizeOcrCapabilityTextLines = (value: unknown): string[] =>
  stringifyOcrCapabilityText(value)
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)

export const uniqueOcrCapabilityLines = (lines: string[]) => {
  const seen = new Set<string>()
  return lines.filter((line) => {
    const key = line.replace(/\s+/g, '').toLowerCase()
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export const isOcrCapabilityPlaceholderSealName = (value: unknown) => {
  const text = String(value || '').trim()
  return !text || text === '视觉印章候选' || text === '视觉蓝章候选' || /^visual_/i.test(text)
}

export const ocrCapabilitySealColorLabel = (record: Record<string, unknown>) => {
  const text =
    `${record.visualColor || ''} ${record.sealType || ''} ${record.sealName || ''}`.toLowerCase()
  if (text.includes('blue')) return '蓝章'
  if (text.includes('red')) return '红章'
  const colorField = Array.isArray(record.fields)
    ? (record.fields as Array<Record<string, unknown>>).find((field) =>
        String(field.fieldName || '').includes('颜色')
      )
    : null
  const colorText = String(colorField?.fieldValue || '').toLowerCase()
  if (colorText.includes('blue')) return '蓝章'
  if (colorText.includes('red')) return '红章'
  return '印章'
}

export const ocrCapabilitySealTypeLabel = (record: Record<string, unknown>) => {
  const type = String(record.sealType || '').toLowerCase()
  if (type.includes('blue')) return '蓝色印章候选'
  if (type.includes('red')) return '红色印章候选'
  if (type.includes('candidate')) return '印章候选'
  return String(record.sealType || record.type || '印章')
}

export const ocrCapabilitySealFieldLines = (record: Record<string, unknown>) => {
  const fields = Array.isArray(record.fields)
    ? (record.fields as Array<Record<string, unknown>>)
    : []
  return fields.flatMap((field) => {
    const name = String(field.fieldName || field.fieldCode || field.name || '').trim()
    const value = stringifyOcrCapabilityText(field.fieldValue ?? field.value ?? field.text).trim()
    if (!value || name.includes('颜色') || name === '印章原文' || name === '识别文字') return []
    return [`${name || '字段'}：${value}`]
  })
}

export const ocrCapabilityBboxOverlapRatio = (
  first: [number, number, number, number],
  second: [number, number, number, number]
) => {
  const left = Math.max(first[0], second[0])
  const top = Math.max(first[1], second[1])
  const right = Math.min(first[2], second[2])
  const bottom = Math.min(first[3], second[3])
  const width = Math.max(0, right - left)
  const height = Math.max(0, bottom - top)
  const overlap = width * height
  if (!overlap) return 0
  const firstArea = (first[2] - first[0]) * (first[3] - first[1])
  const secondArea = (second[2] - second[0]) * (second[3] - second[1])
  return overlap / Math.max(1, Math.min(firstArea, secondArea))
}

export const ocrCapabilityBboxCenterInside = (
  inner: [number, number, number, number],
  outer: [number, number, number, number]
) => {
  const centerX = (inner[0] + inner[2]) / 2
  const centerY = (inner[1] + inner[3]) / 2
  return centerX >= outer[0] && centerX <= outer[2] && centerY >= outer[1] && centerY <= outer[3]
}

export const ocrCapabilityRoiArea = (bbox: [number, number, number, number]) =>
  Math.max(0, bbox[2] - bbox[0]) * Math.max(0, bbox[3] - bbox[1])

export const ocrCapabilityRoiOverlapRatio = (first: OcrCapabilityRoi, second: OcrCapabilityRoi) =>
  ocrCapabilityBboxOverlapRatio(first.bbox, second.bbox)

export const ocrCapabilitySealRoiHasTextEvidence = (source: Record<string, unknown>) => {
  const text = stringifyOcrCapabilityText(
    source.text ?? source.fullText ?? source.rawText ?? source.content ?? source.sealName
  ).replace(/\s+/g, '')
  if (/专用章|印章|许可|单位名称|业务范围|资质证书|有效期|有限公司|TS\d+/i.test(text)) {
    return true
  }
  const fields = Array.isArray(source.fields)
    ? (source.fields as Array<Record<string, unknown>>)
    : []
  return fields.some((field) => {
    const name = String(field.fieldName || field.fieldCode || '').trim()
    const value = stringifyOcrCapabilityText(field.fieldValue ?? field.value ?? field.text).replace(
      /\s+/g,
      ''
    )
    return (
      name !== '印章颜色' &&
      /专用章|印章|许可|单位名称|业务范围|资质证书|有效期|有限公司|TS\d+/i.test(value)
    )
  })
}

export const shouldKeepOcrCapabilityRoi = (
  source: Record<string, unknown>,
  roi: OcrCapabilityRoi
) => {
  if (roi.type !== '印章') return true
  const flags = Array.isArray(source.qualityFlags) ? source.qualityFlags.map(String) : []
  const candidateOnly =
    flags.includes('visual_candidate_only') ||
    flags.includes('requires_seal_ocr_text') ||
    source.candidateOnly === true
  if (!candidateOnly) return true
  return ocrCapabilitySealRoiHasTextEvidence(source)
}

export const dedupeOcrCapabilityRois = (items: OcrCapabilityRoi[]) => {
  const sorted = [...items].sort((left, right) => {
    const typeWeight = (roi: OcrCapabilityRoi) =>
      roi.type === '表格' ? 4 : roi.type === '字段' ? 3 : roi.type === '印章' ? 2 : 1
    const textWeight = (roi: OcrCapabilityRoi) => (roi.text ? 1 : 0)
    return (
      typeWeight(right) - typeWeight(left) ||
      textWeight(right) - textWeight(left) ||
      ocrCapabilityRoiArea(right.bbox) - ocrCapabilityRoiArea(left.bbox)
    )
  })
  const kept: OcrCapabilityRoi[] = []
  sorted.forEach((roi) => {
    const duplicate = kept.some(
      (existing) =>
        existing.pageNo === roi.pageNo &&
        existing.type === roi.type &&
        ocrCapabilityRoiOverlapRatio(existing, roi) >= 0.68
    )
    if (!duplicate) kept.push(roi)
  })
  return kept.sort((left, right) => left.pageNo - right.pageNo || left.bbox[1] - right.bbox[1])
}

export const createOcrCapabilityStructuredRow = (
  source: Record<string, unknown>,
  type: string,
  index: number,
  fallbackName: string
): OcrCapabilityStructuredRow | null => {
  const rawName =
    source.fieldName ||
    source.fieldCode ||
    source.name ||
    source.tableId ||
    source.sealName ||
    source.sealType ||
    source.type ||
    source.label ||
    fallbackName
  const name =
    type === '字段'
      ? friendlyFieldLabel(String(rawName || fallbackName))
      : String(rawName || fallbackName)
  const value =
    type === '表格' ? ocrCapabilityTableSummary(source) : ocrCapabilityStructuredValue(source)
  if (!value && !source.bbox) return null
  return {
    id: `${type}-${source.id || source.fragmentId || source.fieldCode || source.tableId || source.sealId || index}`,
    pageNo: Number(source.pageNo || 1),
    type,
    name,
    value,
    bboxText: ocrCapabilityBboxText(source.bbox),
    confidence:
      source.confidence !== undefined || source.ocrConfidence !== undefined
        ? Number(source.confidence ?? source.ocrConfidence)
        : undefined,
    source: String(source.sourceEngine || source.source || source.extractionMethod || '-')
  }
}

export const createOcrCapabilityRoi = (
  source: Record<string, unknown>,
  type: string,
  tone: OcrCapabilityRoiTone,
  index: number,
  fallbackLabel: string
): OcrCapabilityRoi | null => {
  const bbox = normalizeOcrCapabilityBbox(source.bbox)
  if (!bbox) return null
  const rawLabel =
    source.fieldName ||
    source.fieldCode ||
    source.sealName ||
    source.sealType ||
    source.tableId ||
    source.type ||
    source.label ||
    fallbackLabel
  const label =
    type === '字段'
      ? friendlyFieldLabel(String(rawLabel || fallbackLabel))
      : String(rawLabel || fallbackLabel)
  return {
    id: `${type}-${source.id || source.fragmentId || source.fieldCode || source.tableId || source.sealId || index}`,
    type,
    tone,
    pageNo: Number(source.pageNo || 1),
    label,
    text: ocrCapabilityRoiText(source),
    bbox,
    confidence:
      source.confidence !== undefined || source.ocrConfidence !== undefined
        ? Number(source.confidence ?? source.ocrConfidence)
        : undefined,
    source: String(source.sourceEngine || source.source || '')
  }
}

export const ocrCapabilityRoiTagType = (tone: OcrCapabilityRoiTone) =>
  ocrCapabilityRoiToneTypeMap[tone] || 'info'

export const ocrCapabilityBlobErrorMessage = async (blob: Blob) => {
  if (!String(blob.type || '').includes('application/json')) return ''
  try {
    const payload = JSON.parse(await blob.text())
    return String(payload?.message || payload?.data?.message || payload?.data?.reason || '')
  } catch {
    return ''
  }
}

export const ocrCapabilityTerminalStatuses = new Set(['success', 'failed', 'cancelled'])

export const ocrCapabilityFailureMessage = (detail: FdeOcrCapabilityTestDetailPayload | null) => {
  const diagnostics = [
    ...(detail?.run?.diagnostics || []),
    ...((detail?.parseResult?.diagnostics as Array<Record<string, unknown> | string> | undefined) ||
      [])
  ]
  const first = diagnostics.find(Boolean)
  if (typeof first === 'string') return first
  if (first && typeof first === 'object') {
    return String(first.message || first.code || 'OCR 重新预标注失败。')
  }
  return 'OCR 重新预标注失败，请检查 OCR 服务状态后重试。'
}

export const resolveOcrCapabilityUploadUrl = (uploadUrl: string) => {
  const proxyOrigin = import.meta.env.VITE_MINIO_UPLOAD_PROXY_ORIGIN
  if (!proxyOrigin) return uploadUrl
  try {
    const sourceUrl = new URL(uploadUrl)
    const targetUrl = new URL(proxyOrigin)
    sourceUrl.protocol = targetUrl.protocol
    sourceUrl.host = targetUrl.host
    return sourceUrl.toString()
  } catch {
    return uploadUrl
  }
}

export const isOcrCapabilityHeaderNameSafe = (name: string) =>
  /^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/.test(name)

export const isOcrCapabilityHeaderValueSafe = (value: string) => /^[\t\x20-\xff]*$/.test(value)

export const normalizeOcrCapabilityContentType = (value: string) => {
  const contentType = String(value || '').trim()
  return /^[A-Za-z0-9!#$%&'*+.^_`|~-]+\/[A-Za-z0-9!#$%&'*+.^_`|~-]+(?:\s*;\s*[A-Za-z0-9!#$%&'*+.^_`|~-]+=[A-Za-z0-9!#$%&'*+.^_`|~-]+)*$/.test(
    contentType
  )
    ? contentType
    : 'application/octet-stream'
}

export const sanitizeOcrCapabilityUploadHeaders = (
  rawHeaders: Record<string, string> | undefined,
  fallbackContentType: string
) => {
  const headers: Record<string, string> = {}
  Object.entries(rawHeaders || {}).forEach(([rawName, rawValue]) => {
    const name = String(rawName || '').trim()
    const value = String(rawValue ?? '').trim()
    if (!name || !isOcrCapabilityHeaderNameSafe(name) || !isOcrCapabilityHeaderValueSafe(value)) {
      return
    }
    headers[name] = value
  })
  if (!Object.keys(headers).some((name) => name.toLowerCase() === 'content-type')) {
    headers['Content-Type'] = normalizeOcrCapabilityContentType(fallbackContentType)
  }
  return headers
}
