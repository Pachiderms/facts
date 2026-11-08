import type { BadgeType, Verdict } from '../api/types'

/** Ne produit un lien que pour http(s) : jamais javascript:, data:, etc. dans un href. */
export function safeHref(url: string): string | null {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch {
    return null
  }
}

export interface Tone {
  badge: string
  bar: string
  text: string
}

const GREEN: Tone = { badge: 'bg-emerald-100 text-emerald-900 border-emerald-300', bar: 'bg-emerald-600', text: 'text-emerald-800' }
const AMBER: Tone = { badge: 'bg-amber-100 text-amber-900 border-amber-300', bar: 'bg-amber-500', text: 'text-amber-800' }
const RED: Tone = { badge: 'bg-red-100 text-red-900 border-red-300', bar: 'bg-red-600', text: 'text-red-800' }
const GRAY: Tone = { badge: 'bg-neutral-100 text-neutral-800 border-neutral-300', bar: 'bg-neutral-400', text: 'text-neutral-700' }

export function verdictTone(verdict: Verdict): Tone {
  switch (verdict) {
    case 'VRAI':
      return GREEN
    case 'FAUX':
      return RED
    case 'À NUANCER':
      return AMBER
    case 'NON VÉRIFIABLE':
      return GRAY
  }
}

export function badgeTone(type: BadgeType): Tone {
  return { green: GREEN, amber: AMBER, red: RED, gray: GRAY }[type] ?? GRAY
}

/** Score de fiabilité d'un salon ; `null` = pas encore de donnée (jamais affiché comme 0 %). */
export function trustTone(score: number | null): Tone {
  if (score === null) return GRAY
  if (score >= 75) return GREEN
  if (score >= 50) return AMBER
  return RED
}

export function formatScore(score: number | null): string {
  return score === null ? '—' : `${score}`
}

/** Couleur réservée AUX BADGES de thème : les cartes restent blanches, les participants sans étiquette. */
export const THEME_BADGES: Record<string, { name: string; badge: string }> = {
  social: { name: 'Économie sociale', badge: 'bg-red-50 text-red-700 border-red-200' },
  liberal: { name: 'Fiscalité & marché', badge: 'bg-blue-50 text-blue-700 border-blue-200' },
  ecologie: { name: 'Écologie & climat', badge: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  citoyen: { name: 'Mouvement citoyen', badge: 'bg-amber-50 text-amber-700 border-amber-200' },
  souverain: { name: 'Souveraineté & UE', badge: 'bg-neutral-900 text-white border-neutral-900' },
  techno: { name: 'Institutions & droit', badge: 'bg-gray-100 text-gray-700 border-gray-300' },
}

/** Thèmes proposables à la création d'un salon (liste blanche côté serveur : `THEMES`). */
export const CREATABLE_THEMES = ['social', 'souverain', 'ecologie', 'techno'] as const

export function themeBadge(theme: string) {
  return THEME_BADGES[theme] ?? THEME_BADGES.techno!
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

export interface Hint {
  kind: 'info' | 'warning' | 'success'
  text: string
}

// Reflet du filtre « message vérifiable » du backend (message_checker._CHECKABLE_RE).
// `\b` JavaScript ne reconnaît pas les lettres accentuées (« étude », « trésor ») : on utilise des
// bornes Unicode explicites, équivalentes au `\b` de Python.
const L = '(?<![\\p{L}\\p{N}_])'
const R = '(?![\\p{L}\\p{N}_])'
const word = (alternatives: string) => `${L}(?:${alternatives})${R}`
const CHECKABLE_RE = new RegExp(
  `\\d|%|d['’]après|${word('selon|étude|etude|rapport|insee|ofce|trésor|tresor')}|cour des comptes`,
  'iu',
)
const SOURCE_RE = new RegExp(
  `d['’]après|${word('selon|insee|ofce|trésor|tresor|rapport|étude|etude|rte|aie|cor|hcc')}|cour des comptes`,
  'iu',
)

/** Aide à la rédaction, indicative : la vérification réelle est faite par le serveur. */
export function composeHint(text: string): Hint | null {
  const value = text.trim()
  if (!value) return null
  if (!CHECKABLE_RE.test(value)) {
    return { kind: 'info', text: 'Argument sans fait chiffré : il sera publié sans vérification.' }
  }
  if (/\d|%/.test(value) && !SOURCE_RE.test(value)) {
    return {
      kind: 'warning',
      text: 'Chiffre sans source citée : il risque d’être classé « non étayé ». Citez l’INSEE, le Trésor, l’OFCE…',
    }
  }
  return { kind: 'success', text: 'Ce message contient des éléments vérifiables : l’agent va le contrôler.' }
}

/** « il y a 5 min » : repère d'ancienneté pour l'historique. */
export function timeAgo(timestamp: number, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - timestamp) / 1000))
  if (seconds < 60) return 'à l’instant'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `il y a ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `il y a ${hours} h`
  const days = Math.floor(hours / 24)
  return `il y a ${days} j`
}
