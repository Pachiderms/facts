import { useEffect, useState } from 'react'
import { fetchUsage, type Usage } from '../../api/client'
import { useAuth } from '../../hooks/useAuth'

/** Quota du jour (lecture seule) et état du service. Discret : absent tant que le serveur n'a pas répondu. */
export function UsageNote({ refreshKey }: { refreshKey: unknown }) {
  const { user, enabled } = useAuth()
  const [usage, setUsage] = useState<Usage | null>(null)
  const userId = user?.id ?? null

  useEffect(() => {
    const controller = new AbortController()
    fetchUsage(controller.signal)
      .then(setUsage)
      .catch(() => setUsage(null)) // statut inconnu : on n'affiche rien plutôt qu'un faux chiffre
    return () => controller.abort()
  }, [refreshKey, userId])

  if (!usage) return null
  const { remaining, limit } = usage.checks
  return (
    <div className="mt-2 space-y-1 text-[11px] text-neutral-500" aria-live="polite">
      <p>
        {remaining === 0
          ? 'Limite du jour atteinte. Revenez demain.'
          : `${remaining} vérification${remaining > 1 ? 's' : ''} restante${remaining > 1 ? 's' : ''} aujourd’hui sur ${limit}.`}
        {usage.plan === 'anonymous' && enabled && ' Un compte gratuit augmente cette limite.'}
      </p>
      {usage.degraded && <p>Le service est très sollicité : les réponses peuvent être un peu moins précises ou plus lentes.</p>}
    </div>
  )
}
