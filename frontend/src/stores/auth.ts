import { defineStore } from 'pinia'
import { ref } from 'vue'
import { request } from '../api'
export const useAuth = defineStore('auth', () => {
  const username = ref(sessionStorage.getItem('username') || '')
  async function login(name: string, password: string) {
    const data = await request('POST', '/auth/login', { username: name, password })
    sessionStorage.setItem('token', data.access_token)
    sessionStorage.setItem('username', data.user.username)
    username.value = data.user.username
  }
  function logout() { sessionStorage.clear(); username.value = '' }
  return { username, login, logout }
})
