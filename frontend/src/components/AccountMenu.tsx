import { ChevronDown, Download, LogOut, Trash2, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../hooks/useAuth'
import { GoogleSignInButton } from './GoogleSignInButton'

/** Connexion facultative : sans compte, tout fonctionne comme avant (identité anonyme du navigateur). */
export function AccountMenu() {
  const auth = useAuth()
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) {
        setOpen(false)
        setConfirming(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        setConfirming(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!auth.enabled || auth.loading) return null

  if (!auth.user) {
    return (
      <div className="flex flex-col items-end gap-1">
        {auth.googleClientId && <GoogleSignInButton clientId={auth.googleClientId} onCredential={(c) => void auth.signIn(c)} />}
        {auth.error && (
          <p role="alert" className="max-w-[16rem] text-right text-[11px] font-medium text-red-800">
            {auth.error}
          </p>
        )}
      </div>
    )
  }

  const download = async () => {
    const blob = await auth.download()
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'facts-mes-donnees.json'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Mon compte"
        className="flex max-w-[11rem] items-center gap-1.5 rounded-lg border border-neutral-300 bg-white px-2.5 py-1.5 text-xs font-bold text-neutral-800 hover:bg-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
      >
        <User className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate">{auth.user.email}</span>
        <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-72 space-y-1 rounded-xl border border-neutral-200 bg-white p-2 text-xs shadow-lg">
          <p className="truncate px-2 py-1 text-neutral-500">{auth.user.email}</p>
          <button type="button" role="menuitem" onClick={() => void download()} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left font-medium hover:bg-neutral-100">
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            Télécharger mes données
          </button>
          <button type="button" role="menuitem" onClick={() => void auth.signOut()} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left font-medium hover:bg-neutral-100">
            <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
            Se déconnecter
          </button>
          <button type="button" role="menuitem" onClick={() => void auth.signOutEverywhere()} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left font-medium hover:bg-neutral-100">
            <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
            Se déconnecter partout
          </button>
          {!confirming ? (
            <button type="button" role="menuitem" onClick={() => setConfirming(true)} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left font-medium text-red-800 hover:bg-red-50">
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              Supprimer mon compte
            </button>
          ) : (
            <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-2 text-red-900">
              <p>Votre compte, vos sessions et vos données seront effacés définitivement. Cette action est irréversible.</p>
              <div className="flex gap-2">
                <button type="button" onClick={() => void auth.remove()} className="rounded-lg bg-red-800 px-3 py-1.5 font-bold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-red-800 focus-visible:ring-offset-2">
                  Supprimer définitivement
                </button>
                <button type="button" onClick={() => setConfirming(false)} className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 font-bold text-neutral-700">
                  Annuler
                </button>
              </div>
            </div>
          )}
          {auth.error && (
            <p role="alert" className="px-2 py-1 font-medium text-red-800">
              {auth.error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
