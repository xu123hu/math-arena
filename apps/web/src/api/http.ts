/**
 * HTTP 请求封装（api/http.ts）
 *
 * - 请求拦截器自动带 Authorization: Bearer <token>
 * - 响应拦截器：code !== 0 → 抛 ApiError
 * - 40101 → 清空 auth store 跳登录
 * - 所有 url 以 import.meta.env.VITE_API_BASE 为前缀
 */
import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'

const VITE_API_BASE = import.meta.env.VITE_API_BASE || '/api'

interface ApiResponse<T = unknown> {
  code: number
  data: T
  message?: string
  request_id?: string
}

export class ApiError extends Error {
  code: number
  requestId?: string

  constructor(code: number, message: string, requestId?: string) {
    super(message)
    this.code = code
    this.requestId = requestId
    this.name = 'ApiError'
  }
}

const http: AxiosInstance = axios.create({
  baseURL: VITE_API_BASE,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：自动带 token
http.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截器：统一错误处理
http.interceptors.response.use(
  (response: AxiosResponse<ApiResponse>) => {
    const { data } = response
    if (data.code !== 0) {
      // 40101 → 跳登录
      if (data.code === 40101) {
        localStorage.removeItem('token')
        window.location.href = '/login'
      }
      throw new ApiError(data.code, data.message || '请求失败', data.request_id)
    }
    return response
  },
  (error) => {
    if (error.response) {
      const { data } = error.response
      throw new ApiError(data?.code || 500, data?.message || '网络错误', data?.request_id)
    }
    throw new ApiError(0, '网络连接失败')
  },
)

export default http
