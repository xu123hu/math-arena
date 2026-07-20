/**
 * SSE 客户端 composable 占位
 *
 * 使用 @microsoft/fetch-event-source（0.5.x）
 * 职责：
 * - 生成并持有 client_msg_id
 * - POST /api/agent/chat
 * - 按事件表 dispatch
 * - 维护流式状态机（idle/sending/streaming/done/error/aborted）
 */
// TODO: 实现 useAgentStream
export function useAgentStream() {
  return {
    // send, stop, state, messages...
  }
}
