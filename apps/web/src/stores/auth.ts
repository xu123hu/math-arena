/**
 * Auth Store - 认证状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface User {
  id: string
  nickname: string
  active_role: string
  roles: string[]
  verified: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const activeRole = computed(() => user.value?.active_role || '')

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  function setUser(newUser: User) {
    user.value = newUser
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
  }

  return {
    token,
    user,
    isLoggedIn,
    activeRole,
    setToken,
    setUser,
    logout,
  }
})
