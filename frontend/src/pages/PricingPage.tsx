import { Check, Crown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError, fetchBilling, startCheckout, type Billing } from '../api/client'
import { EmailLoginForm } from '../components/EmailLoginForm'
import { GoogleSignInButton } from '../components/GoogleSignInButton'
import { useAuth } from '../hooks/useAuth'
import { legalHref } from '../lib/route'

const FREE_FEATURES = ['Vérificateur IA et salons de débat', 'Quota quotidien de vérifications', 'Compte gratuit : quotas plus élevés que sans compte']
const PRO_FEATURES = ['Tout ce que contient l’offre gratuite', 'Quotas quotidiens nettement relevés (vérifications et messages vérifiés)', 'Résiliable à tout moment']

const frDate = (iso: string) => new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })

function Features({ items }: { items: string[] }) {
  return (
    <ul className="mt-4 space-y-2 text-xs text-neutral-700">
      {items.map((t) => (
        <li key={t} className="flex gap-2">
          <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-neutral-900" aria-hidden="true" />
          <span>{t}</span>
        </li>
      ))}
    </ul>
  )
}

/** Tarifs : Gratuit / Pro. Le paiement reste « bientôt disponible » tant que le serveur ne l'a pas ouvert. */
export function PricingPage() {
  const auth = useAuth()
  const [billing, setBilling] = useState<Billing | null>(null)
  const [failed, setFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const userId = auth.user?.id ?? null

  useEffect(() => {
    const controller = new AbortController()
    setFailed(false)
    fetchBilling(controller.signal)
      .then(setBilling)
      .catch(() => !controller.signal.aborted && setFailed(true))
    return () => controller.abort()
  }, [userId])

  const subscribe = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      window.location.assign(await startCheckout()) // adresse https validée par startCheckout
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Paiement indisponible pour le moment.')
      setBusy(false)
    }
  }

  const isPro = billing?.plan === 'pro'
  const open = billing?.enabled === true

  let action: React.ReactNode
  if (!billing) {
    action = <p className="text-xs text-neutral-500">{failed ? 'Offre momentanément indisponible.' : 'Chargement…'}</p>
  } else if (isPro) {
    action = (
      <div className="space-y-2 text-xs">
        <p className="font-bold text-neutral-900">Vous êtes abonné Pro.</p>
        {billing.currentPeriodEnd && (
          <p className="text-neutral-600">
            {billing.status === 'cancelled' ? 'Accès jusqu’au' : 'Période en cours jusqu’au'} {frDate(billing.currentPeriodEnd)}.
          </p>
        )}
        {billing.portalUrl && (
          <a href={billing.portalUrl} target="_blank" rel="noopener noreferrer" className="inline-block font-bold underline">
            Gérer mon abonnement
          </a>
        )}
      </div>
    )
  } else if (!open) {
    action = (
      <button type="button" disabled className="w-full cursor-not-allowed rounded-xl bg-neutral-300 px-4 py-2.5 text-xs font-bold text-white">
        Bientôt disponible
      </button>
    )
  } else if (!auth.user) {
    action = auth.enabled && (auth.googleClientId || auth.emailLogin) ? (
      <div className="space-y-3">
        <p className="text-xs text-neutral-600">Connectez-vous pour vous abonner : l’abonnement est rattaché à votre compte.</p>
        {auth.googleClientId && <GoogleSignInButton clientId={auth.googleClientId} onCredential={(c) => void auth.signIn(c)} />}
        {auth.emailLogin && (
          <div className="rounded-xl bg-white p-3 text-neutral-900 [&_p]:text-neutral-500">
            <EmailLoginForm />
          </div>
        )}
      </div>
    ) : (
      <p className="text-xs text-neutral-500">La connexion est momentanément indisponible.</p>
    )
  } else {
    action = (
      <button
        type="button"
        onClick={() => void subscribe()}
        disabled={busy}
        className="w-full rounded-xl bg-white px-4 py-2.5 text-xs font-bold text-neutral-900 transition hover:bg-neutral-100 disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
      >
        {busy ? 'Redirection…' : 'Passer à Pro'}
      </button>
    )
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-extrabold text-neutral-900">Tarifs</h1>
        <p className="mt-1 text-xs text-neutral-500">Le service reste gratuit. L’offre Pro relève les plafonds quotidiens pour celles et ceux qui l’utilisent beaucoup.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <section aria-label="Offre gratuite" className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-extrabold text-neutral-900">Gratuit</h2>
          <p className="mt-1 font-mono text-2xl font-black text-neutral-900">0 €</p>
          <Features items={FREE_FEATURES} />
        </section>

        <section aria-label="Offre Pro" className="rounded-2xl border border-neutral-900 bg-neutral-900 p-5 text-white shadow-sm">
          <h2 className="flex items-center gap-2 text-sm font-extrabold">
            <Crown className="h-4 w-4" aria-hidden="true" /> Pro
          </h2>
          <p className="mt-1 font-mono text-2xl font-black">{open && billing?.priceLabel ? billing.priceLabel : 'Bientôt'}</p>
          <ul className="mt-4 space-y-2 text-xs text-neutral-200">
            {PRO_FEATURES.map((t) => (
              <li key={t} className="flex gap-2">
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>{t}</span>
              </li>
            ))}
          </ul>
          <div className="mt-5 [&_a]:text-white [&_p]:text-neutral-200 [&_p.font-bold]:text-white">{action}</div>
          {error && (
            <p role="alert" className="mt-3 rounded-lg bg-red-100 px-3 py-2 text-xs font-medium text-red-800">
              {error}
            </p>
          )}
        </section>
      </div>

      <p className="text-[11px] leading-relaxed text-neutral-500">
        Paiement sécurisé opéré par Lemon Squeezy (vendeur de l’abonnement, TVA incluse). Nous ne voyons ni ne stockons vos données bancaires.
        Voir les{' '}
        <a href={legalHref('cgu')} className="font-bold underline">
          conditions générales
        </a>{' '}
        et la{' '}
        <a href={legalHref('confidentialite')} className="font-bold underline">
          politique de confidentialité
        </a>
        .
      </p>
    </div>
  )
}
