/**
 * Chat Store - 聊天状态管理
 *
 * 消息对象结构：
 * { client_msg_id, role, status: 'sending|streaming|done|error|aborted', blocks[], meta? }
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Message {
  client_msg_id: string
  role: 'user' | 'assistant' | 'system'
  status: 'sending' | 'streaming' | 'done' | 'error' | 'aborted'
  content: string
  blocks: unknown[]
  meta?: Record<string, unknown>
}

export interface Conversation {
  id: string
  title: string
  updated_at: string
}

export const useChatStore = defineStore('chat', () => {
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Map<string, Message>>(new Map())
  const conversations = ref<Conversation[]>([])
  const isStreaming = ref(false)

  function addMessage(msg: Message) {
    messages.value.set(msg.client_msg_id, msg)
  }

  function updateMessage(clientMsgId: string, updates: Partial<Message>) {
    const msg = messages.value.get(clientMsgId)
    if (msg) {
      messages.value.set(clientMsgId, { ...msg, ...updates })
    }
  }

  function clearMessages() {
    messages.value.clear()
  }

  return {
    currentConversationId,
    messages,
    conversations,
    isStreaming,
    addMessage,
    updateMessage,
    clearMessages,
  }
})
