/** Chargement à la demande du script « Se connecter avec Google » (Google Identity Services). */

interface GoogleId {
  initialize(config: { client_id: string; callback: (r: { credential?: string }) => void; auto_select?: boolean; ux_mode?: 'popup' }): void
  renderButton(parent: HTMLElement, options: Record<string, string | number>): void
}
declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleId } }
  }
}

export const GOOGLE_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'

let loading: Promise<GoogleId> | null = null

export function loadGoogle(): Promise<GoogleId> {
  const ready = window.google?.accounts?.id
  if (ready) return Promise.resolve(ready)
  loading ??= new Promise<GoogleId>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = GOOGLE_SCRIPT_SRC
    script.async = true
    script.onload = () => {
      const id = window.google?.accounts?.id
      if (id) resolve(id)
      else reject(new Error('google indisponible'))
    }
    script.onerror = () => {
      loading = null // pourra être retenté
      reject(new Error('google bloqué'))
    }
    document.head.appendChild(script)
  })
  return loading
}
