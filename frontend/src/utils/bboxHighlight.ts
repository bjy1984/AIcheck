/**
 * OCR 证据框的几何换算。
 *
 * 抽成独立单元是因为线上/demo 数据里 evidence_links 的 bbox 全为空，这段换算
 * 在真实环境里跑不到——只能靠单测钉住，不能靠「点开看看」。
 *
 * 坐标约定：bbox 是 [x0, y0, x1, y1] 的**像素**坐标，原点左上，基准是原图的
 * naturalWidth/naturalHeight。换算成百分比而非像素，是为了让高亮框跟随 <img>
 * 的等比缩放，不必监听尺寸变化。
 */

export type Bbox = [number, number, number, number]

/**
 * 校验并归一化 bbox。返回 undefined 表示这条证据不可定位——调用方据此
 * 退化为「只跳页、不画框」，而不是画一个错位的框误导用户。
 */
export const normalizeBbox = (bbox?: number[] | null): Bbox | undefined => {
  if (!Array.isArray(bbox) || bbox.length < 4) return undefined
  const [x0, y0, x1, y1] = bbox.map(Number)
  if (![x0, y0, x1, y1].every((n) => Number.isFinite(n))) return undefined
  // 零宽或反向的框画出来是空的或翻转的，两种都比不画更糟
  if (x1 <= x0 || y1 <= y0) return undefined
  return [x0, y0, x1, y1]
}

export type HighlightStyle = {
  left: string
  top: string
  width: string
  height: string
}

/** 把像素 bbox 换算成相对原图尺寸的百分比定位样式。 */
export const bboxToPercentStyle = (
  bbox: number[] | undefined,
  natural: { width: number; height: number } | null | undefined
): HighlightStyle | null => {
  const box = normalizeBbox(bbox)
  if (!box || !natural?.width || !natural?.height) return null
  const [x0, y0, x1, y1] = box
  const pct = (value: number, total: number) => `${(value / total) * 100}%`
  return {
    left: pct(x0, natural.width),
    top: pct(y0, natural.height),
    width: pct(x1 - x0, natural.width),
    height: pct(y1 - y0, natural.height)
  }
}
