import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { apiFetch, AUTH_TOKEN_STORAGE_KEY } from '../api/client'
import type { Merchant } from '../api/types'

type AuthContextValue = {
  token: string | null
  merchant: Merchant | null
  bootstrapping: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY),
  )
  const [merchant, setMerchant] = useState<Merchant | null>(null)
  const [bootstrapping, setBootstrapping] = useState(!!token)

  useEffect(() => {
    if (!token) {
      return
    }

    let cancelled = false
    void (async () => {
      setBootstrapping(true)
      try {
        const m = await apiFetch<Merchant>('me/')
        if (!cancelled) setMerchant(m)
      } catch {
        if (!cancelled) {
          sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
          setMerchant(null)
          setToken(null)
        }
      } finally {
        if (!cancelled) setBootstrapping(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [token])

  const login = useCallback(async (username: string, password: string) => {
    const { token: newToken } = await apiFetch<{ token: string }>(
      'auth/token/',
      {
        method: 'POST',
        body: JSON.stringify({ username, password }),
        skipAuth: true,
      },
    )
    sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, newToken)
    setToken(newToken)
  }, [])

  const logout = useCallback(() => {
    sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
    setMerchant(null)
    setToken(null)
  }, [])

  const value = useMemo(
    () => ({ token, merchant, bootstrapping, login, logout }),
    [token, merchant, bootstrapping, login, logout],
  )

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
