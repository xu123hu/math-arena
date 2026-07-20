import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/login',
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/role-select',
    name: 'RoleSelect',
    component: () => import('@/pages/role-select.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/student',
    component: () => import('@/layouts/WorkspaceLayout.vue'),
    meta: { requiresAuth: true, role: 'student' },
    children: [
      {
        path: '',
        name: 'StudentHome',
        component: () => import('@/pages/student/index.vue'),
      },
      {
        path: 'chat/:id',
        name: 'StudentChat',
        component: () => import('@/pages/student/chat.vue'),
      },
      {
        path: 'classes',
        name: 'StudentClasses',
        component: () => import('@/pages/student/classes.vue'),
      },
      {
        path: 'memories',
        name: 'StudentMemories',
        component: () => import('@/pages/student/memories.vue'),
      },
    ],
  },
  {
    path: '/teacher',
    component: () => import('@/layouts/WorkspaceLayout.vue'),
    meta: { requiresAuth: true, role: 'teacher' },
    children: [
      {
        path: '',
        name: 'TeacherHome',
        component: () => import('@/pages/teacher/index.vue'),
      },
      {
        path: 'chat/:id',
        name: 'TeacherChat',
        component: () => import('@/pages/teacher/chat.vue'),
      },
      {
        path: 'classes',
        name: 'TeacherClasses',
        component: () => import('@/pages/teacher/classes.vue'),
      },
      {
        path: 'memories',
        name: 'TeacherMemories',
        component: () => import('@/pages/teacher/memories.vue'),
      },
    ],
  },
  {
    path: '/research',
    component: () => import('@/layouts/WorkspaceLayout.vue'),
    meta: { requiresAuth: true, role: 'researcher' },
    children: [
      {
        path: '',
        name: 'ResearchHome',
        component: () => import('@/pages/research/index.vue'),
      },
      {
        path: 'chat/:id',
        name: 'ResearchChat',
        component: () => import('@/pages/research/chat.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录/角色不符 → /login
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  const requiresAuth = to.meta.requiresAuth !== false

  if (requiresAuth && !token) {
    next('/login')
  } else {
    next()
  }
})

export default router
