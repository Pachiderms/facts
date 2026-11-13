import { Mail } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useAuth } from '../hooks/useAuth'

const EMAIL_RE = /^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+$/
const RESEND_SECONDS = 30

/** Connexion par code : adresse e-mail, puis code à 6 chiffres reçu par e-mail (aucun mot de passe). */
export function EmailLoginForm({ onDone }: { onDone?: () => void }) {
  const auth = useAuth()
  const [step, setStep] = useState<'email' | 'code'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wait, setWait] = useState(0)
  const inFlight = useRef(false)
  const ids = { email: useId(), code: useId() }
  const address = email.trim().toLowerCase()

  useEffect(() => {
    if (wait <= 0) return
    const timer = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(timer)
  }, [wait])

  const send = async () => {
    if (inFlight.current) return
    if (!EMAIL_RE.test(address) || address.length > 254) {
      setError('Adresse e-mail invalide.')
      return
    }
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const problem = await auth.requestCode(address)
      if (problem) {
        setError(problem)
        return
      }
      setStep('code')
      setCode('')
      setWait(RESEND_SECONDS)
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const verify = async () => {
    if (inFlight.current || !/^\d{6}$/.test(code)) return
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      const problem = await auth.signInWithEmail(address, code)
      if (problem) {
        setError(problem)
        setCode('')
        return
      }
      onDone?.()
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void (step === 'email' ? send() : verify())
  }

  const input =
    'w-full rounded-xl border border-neutral-300 bg-neutral-50 px-3 py-2 text-sm text-neutral-900 focus:bg-white focus:outline-none focus:ring-2 focus:ring-neutral-900'

  return (
    <form onSubmit={submit} noValidate aria-label="Connexion par e-mail" className="space-y-3 text-xs">
      {step === 'email' ? (
        <div className="space-y-1.5">
          <label htmlFor={ids.email} className="font-bold text-neutral-800">
            Votre adresse e-mail
          </label>
          <input
            id={ids.email}
            type="email"
            inputMode="email"
            autoComplete="email"
            maxLength={254}
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              setError(null)
            }}
            placeholder="vous@exemple.fr"
            className={input}
          />
          <p className="text-[11px] text-neutral-500">Nous vous envoyons un code à 6 chiffres. Pas de mot de passe.</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <label htmlFor={ids.code} className="font-bold text-neutral-800">
            Code reçu à <span className="font-mono">{address}</span>
          </label>
          <input
            id={ids.code}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => {
              setCode(e.target.value.replace(/\D/g, '').slice(0, 6))
              setError(null)
            }}
            placeholder="123456"
            className={`${input} text-center font-mono text-lg tracking-[0.4em]`}
          />
          <p className="text-[11px] text-neutral-500">Valable 10 minutes. Pensez à regarder vos courriers indésirables.</p>
        </div>
      )}

      {error && (
        <p role="alert" className="font-medium text-red-800">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={busy || (step === 'email' ? !email.trim() : code.length !== 6)}
          className="flex items-center gap-2 rounded-xl bg-neutral-900 px-4 py-2 font-bold text-white transition hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 focus-visible:ring-offset-2"
        >
          <Mail className="h-3.5 w-3.5" aria-hidden="true" />
          {step === 'email' ? (busy ? 'Envoi…' : 'Recevoir un code') : busy ? 'Vérification…' : 'Se connecter'}
        </button>
        {step === 'code' && (
          <>
            <button
              type="button"
              onClick={() => void send()}
              disabled={busy || wait > 0}
              className="rounded-xl border border-neutral-300 bg-white px-3 py-2 font-bold text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {wait > 0 ? `Renvoyer le code (${wait} s)` : 'Renvoyer le code'}
            </button>
            <button
              type="button"
              onClick={() => {
                setStep('email')
                setError(null)
                setCode('')
              }}
              className="px-1 py-2 font-bold text-neutral-600 underline"
            >
              Changer d’adresse
            </button>
          </>
        )}
      </div>
    </form>
  )
}
