import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  ApiError,
  apiFetch,
  clearStoredAuthToken,
  getStoredAuthToken,
  setStoredAuthToken,
} from '../api/client'
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
  const [token, setToken] = useState<string | null>(() => getStoredAuthToken())
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
      } catch (err) {
        if (!cancelled) {
          // Keep session on transient API/network errors; clear only invalid tokens.
          if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
            clearStoredAuthToken()
            setMerchant(null)
            setToken(null)
          }
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
    setStoredAuthToken(newToken)
    setToken(newToken)
  }, [])

  const logout = useCallback(() => {
    clearStoredAuthToken()
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
