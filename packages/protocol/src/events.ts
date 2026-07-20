/**
 * SSE 事件类型定义（§4.3）
 *
 * 事件顺序链：meta → status* → (token* | clarify) → card* → citation? → badge? → done
 * 事件类型全集（M1 启用 9 种）
 * 前端遇到未知事件类型必须忽略而不是报错——向前兼容铁律
 */

/** meta 事件 - 永远第一个 */
export interface MetaEvent {
  type: 'meta'
  data: {
    conversation_id: string
    msg_id: string
    skill: string
    confidence: number
    provider: 'spark' | 'deepseek'
  }
}

/** status 事件 - 过程提示 */
export interface StatusEvent {
  type: 'status'
  data: {
    stage: string
    text: string  // 如 "正在检索知识库…"
  }
}

/** clarify 事件 - 低置信反问 */
export interface ClarifyEvent {
  type: 'clarify'
  data: {
    question: string
    options: string[]
  }
}

/** token 事件 - LLM 流式增量文本 */
export interface TokenEvent {
  type: 'token'
  data: {
    text: string
  }
}

/** card 事件 - 结构化卡片（M2 启用） */
export interface CardEvent {
  type: 'card'
  data: {
    card_type: string
    payload: unknown
  }
}

/** citation 事件 - 引用来源 */
export interface CitationEvent {
  type: 'citation'
  data: {
    items: Array<{
      /** n 对应正文【N】锚点，与《M0-M1技术开发手册》§4.4 / API 文档 §4.1 一致 */
      n: number
      source: string
      loc: string
      chunk_id: string
    }>
  }
}

/** badge 事件 - 证据等级 */
export interface BadgeEvent {
  type: 'badge'
  data: {
    level: string
  }
}

/** error 事件 - 失败（出现则无 done） */
export interface ErrorEvent {
  type: 'error'
  data: {
    code: number
    message: string
    recoverable: boolean
  }
}

/** done 事件 - 正常结束（正常路径永远最后一个） */
export interface DoneEvent {
  type: 'done'
  data: {
    usage: {
      tokens_in: number
      tokens_out: number
    }
    latency_ms: number
  }
}

/** 所有 SSE 事件的联合类型 */
export type SSEEvent =
  | MetaEvent
  | StatusEvent
  | ClarifyEvent
  | TokenEvent
  | CardEvent
  | CitationEvent
  | BadgeEvent
  | ErrorEvent
  | DoneEvent

/** SSE 事件类型枚举 */
export const SSE_EVENT_TYPES = [
  'meta',
  'status',
  'clarify',
  'token',
  'card',
  'citation',
  'badge',
  'error',
  'done',
] as const

export type SSEEventType = (typeof SSE_EVENT_TYPES)[number]
