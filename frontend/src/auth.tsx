import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api/endpoints'
import { clearAccessToken, setAccessToken } from './api/client'
import type { User } from './types/api'

interface AuthContextValue {
  user: User | null
  loading: boolean
  error: Error | null
  login: (email: string, password: string) => Promise<void>
  register: (payload: { email: string; display_name: string; password: string; role: string }) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    api.me()
      .then((result) => { setUser(result); setError(null) })
      .catch((reason: Error) => { setUser(null); setError(reason) })
      .finally(() => setLoading(false))
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    error,
    login: async (email, password) => {
      const result = await api.login(email, password)
      setAccessToken(result.access_token)
      setUser(result.user)
      setError(null)
    },
    register: async (payload) => {
      const result = await api.register(payload)
      setAccessToken(result.access_token)
      setUser(result.user)
      setError(null)
    },
    logout: () => {
      clearAccessToken()
      setUser(null)
      setError(null)
    },
  }), [user, loading, error])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
