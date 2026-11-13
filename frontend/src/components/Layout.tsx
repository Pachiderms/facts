import { Bot, Flame, Scale } from 'lucide-react'
import type { ReactNode } from 'react'
import { AccountMenu } from './AccountMenu'

export type PageId = 'check' | 'arena'

const TABS: { id: PageId; label: string; short: string; icon: typeof Bot }[] = [
  { id: 'check', label: 'Vérificateur IA', short: 'Vérifier', icon: Bot },
  { id: 'arena', label: 'Arène de débat', short: 'Arène', icon: Flame },
]

export function Header({ page, onNavigate }: { page: PageId; onNavigate: (page: PageId) => void }) {
  return (
    <header className="sticky top-0 z-50 border-b border-neutral-200 bg-white shadow-sm">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex items-center space-x-3">
          <button
            type="button"
            onClick={() => onNavigate('check')}
            aria-label="CaFaitDebat, retour à l’accueil (Vérificateur IA)"
            className="flex items-center space-x-3 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900"
          >
            <span
              aria-hidden="true"
              className="flex h-9 min-w-9 items-center justify-center rounded-lg bg-neutral-900 px-1.5 font-mono text-[13px] font-black tracking-tight text-white shadow-md"
            >
              CFD
            </span>
            <span className="flex flex-col text-left leading-tight">
              <span className="hidden font-mono text-xl font-extrabold tracking-tight text-neutral-900 sm:block">
                CaFaitDebat<span className="text-neutral-400">.</span>
              </span>
              <span className="hidden text-[10px] font-medium uppercase tracking-wider text-neutral-500 sm:block">
                Vérification de faits &amp; arène neutre
              </span>
            </span>
          </button>
        </div>

        <nav aria-label="Navigation principale" className="flex items-center rounded-xl border border-neutral-200 bg-neutral-100 p-1">
          {TABS.map(({ id, label, short, icon: Icon }) => {
            const active = page === id
            return (
              <button
                key={id}
                type="button"
                onClick={() => onNavigate(id)}
                aria-current={active ? 'page' : undefined}
                aria-label={label}
                className={`flex items-center space-x-2 rounded-lg px-3 py-2 text-xs font-bold transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900 sm:px-4 ${
                  active ? 'border border-neutral-200 bg-white text-neutral-900 shadow-sm' : 'text-neutral-600 hover:text-neutral-900'
                }`}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">{label}</span>
                <span className="sm:hidden">{short}</span>
              </button>
            )
          })}
        </nav>

        <AccountMenu />

        <div className="hidden items-center space-x-2 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-xs text-neutral-600 xl:flex">
          <Scale className="h-3.5 w-3.5 text-neutral-500" aria-hidden="true" />
          <span>
            Recherche web en direct · <strong className="text-neutral-900">sources classées par type</strong>
          </span>
        </div>
      </div>
    </header>
  )
}

export function Footer() {
  return (
    <footer className="mt-16 border-t border-neutral-200 bg-white py-6 text-xs text-neutral-500">
      <div className="mx-auto max-w-7xl px-4">
        <p>
          <span className="font-bold text-neutral-900">CaFaitDebat.</span> Vérification assistée par IA. Les verdicts peuvent comporter des
          erreurs : consultez toujours les sources.
        </p>
      </div>
    </footer>
  )
}

export function Page({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">{children}</main>
}
