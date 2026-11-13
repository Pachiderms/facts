import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ApiError,
  deleteAccount,
  exportAccount,
  fetchMe,
  getFeatures,
  loginWithGoogle,
  logoutEverywhere,
  logoutSession,
  type AccountUser,
} from '../api/client'
import { clearSession, getSession, setSession } from '../lib/session'
import { useHistorySync } from './useHistorySync'

export interface AuthState {
  /** Les comptes sont proposés (serveur configuré). Sinon l'interface n'affiche rien. */
  enabled: boolean
  googleClientId: string | null
  user: AccountUser | null
  loading: boolean
  error: string | null
  signIn: (credential: string) => Promise<void>
  signOut: () => Promise<void>
  signOutEverywhere: () => Promise<void>
  download: () => Promise<Blob | null>
  remove: () => Promise<boolean>
  clearError: () => void
}

const DISABLED: AuthState = {
  enabled: false,
  googleClientId: null,
  user: null,
  loading: false,
  error: null,
  signIn: async () => {},
  signOut: async () => {},
  signOutEverywhere: async () => {},
  download: async () => null,
  remove: async () => false,
  clearError: () => {},
}

const AuthContext = createContext<AuthState>(DISABLED)

export const useAuth = () => useContext(AuthContext)

const message = (e: unknown) => (e instanceof ApiError ? e.message : 'Une erreur est survenue. Réessayez.')

export function AuthProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(false)
  const [googleClientId, setGoogleClientId] = useState<string | null>(null)
  const [user, setUser] = useState<AccountUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useHistorySync(user?.id ?? null)

  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    void (async () => {
      const features = await getFeatures()
      if (!alive) return
      setEnabled(features.accounts)
      setGoogleClientId(features.googleClientId)
      const token = features.accounts ? getSession() : null
      if (token) {
        try {
          const me = await fetchMe(token, controller.signal)
          if (alive) setUser(me)
        } catch (e) {
          // 401 : session expirée ou révoquée. Autre erreur (réseau) : on garde le jeton pour réessayer plus tard.
          if (e instanceof ApiError && e.status === 401) clearSession()
        }
      }
      if (alive) setLoading(false)
    })()
    return () => {
      alive = false
      controller.abort()
    }
  }, [])

  const signIn = useCallback(async (credential: string) => {
    setError(null)
    try {
      const { sessionToken, user: me } = await loginWithGoogle(credential)
      setSession(sessionToken)
      setUser(me)
    } catch (e) {
      setError(message(e))
    }
  }, [])

  const endSession = useCallback(async (revoke: (t: string) => Promise<unknown>) => {
    const token = getSession()
    clearSession()
    setUser(null)
    if (token) {
      try {
        await revoke(token)
      } catch {
        /* déconnecté localement dans tous les cas ; la session expirera côté serveur */
      }
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      enabled,
      googleClientId,
      user,
      loading,
      error,
      signIn,
      signOut: () => endSession(logoutSession),
      signOutEverywhere: () => endSession(logoutEverywhere),
      download: async () => {
        const token = getSession()
        if (!token) return null
        try {
          return await exportAccount(token)
        } catch (e) {
          setError(message(e))
          return null
        }
      },
      remove: async () => {
        const token = getSession()
        if (!token) return false
        try {
          await deleteAccount(token)
        } catch (e) {
          setError(message(e))
          return false
        }
        clearSession()
        setUser(null)
        return true
      },
      clearError: () => setError(null),
    }),
    [enabled, googleClientId, user, loading, error, signIn, endSession],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
