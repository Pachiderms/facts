import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, checkAssertion } from '../api/client'
import type { CheckResponse } from '../api/types'

export interface CheckState {
  loading: boolean
  /** Vrai quand la requête dure : probable démarrage à froid de l'hébergeur gratuit. */
  slow: boolean
  error: string | null
  result: CheckResponse | null
  /** Affirmation correspondant au résultat affiché (pas celle en cours de saisie). */
  assertion: string | null
}

const SLOW_AFTER_MS = 8_000

export function useCheck() {
  const [state, setState] = useState<CheckState>({ loading: false, slow: false, error: null, result: null, assertion: null })
  const controller = useRef<AbortController | null>(null)
  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearSlow = () => {
    if (slowTimer.current) clearTimeout(slowTimer.current)
    slowTimer.current = null
  }

  useEffect(
    () => () => {
      controller.current?.abort()
      clearSlow()
    },
    [],
  )

  const submit = useCallback(async (assertion: string, institutionalFilter: boolean) => {
    controller.current?.abort() // une seule vérification à la fois : la plus récente gagne
    const mine = new AbortController()
    controller.current = mine
    clearSlow()
    setState((s) => ({ ...s, loading: true, slow: false, error: null }))
    slowTimer.current = setTimeout(() => setState((s) => (s.loading ? { ...s, slow: true } : s)), SLOW_AFTER_MS)
    try {
      const result = await checkAssertion(assertion, institutionalFilter, mine.signal)
      if (mine.signal.aborted) return
      setState({ loading: false, slow: false, error: null, result, assertion })
    } catch (e) {
      if (mine.signal.aborted) return
      const message = e instanceof ApiError ? e.message : 'Une erreur est survenue. Réessayez.'
      setState((s) => ({ ...s, loading: false, slow: false, error: message }))
    } finally {
      clearSlow()
    }
  }, [])

  return { ...state, submit }
}
