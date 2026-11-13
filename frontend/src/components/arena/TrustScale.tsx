import { useEffect, useRef } from 'react'

/** Inclinaison maximale du fléau (degrés) : 100 → côté « vérifié » baissé, 0 → côté « non étayé » baissé. */
export const MAX_TILT = 15

/** Angle cible du fléau ; sans donnée (`null`) la balance est à plat. 50 = équilibre. */
export function scaleAngle(score: number | null): number {
  if (score === null || !Number.isFinite(score)) return 0
  const clamped = Math.max(0, Math.min(100, score))
  return ((clamped - 50) / 50) * MAX_TILT
}

/** Libellé court, aligné sur les seuils de couleur de `trustTone` (75 / 50). */
export function scaleCaption(score: number | null): string {
  if (score === null) return 'Aucun message vérifié'
  if (score >= 75) return 'Plutôt vérifié'
  if (score >= 50) return 'Équilibré'
  return 'Plutôt non étayé'
}

const PIVOT_X = 200
const PIVOT_Y = 63
const HALF_BEAM = 170
const STIFFNESS = 38
const DAMPING = 5.2

function panTransform(side: -1 | 1, angle: number, velocity: number): string {
  const rad = (angle * Math.PI) / 180
  const x = PIVOT_X + side * HALF_BEAM * Math.cos(rad)
  const y = PIVOT_Y + side * HALF_BEAM * Math.sin(rad)
  return `translate(${x.toFixed(2)} ${y.toFixed(2)}) rotate(${(-velocity * 0.35).toFixed(2)})`
}

/**
 * Mini-balance décorative (le score est déjà annoncé par la barre `progressbar`) : le fléau penche
 * avec un ressort amorti ; les plateaux restent horizontaux et se balancent. Immobile si
 * « réduire les animations » est demandé.
 */
export function TrustScale({ score }: { score: number | null }) {
  const beam = useRef<SVGGElement>(null)
  const left = useRef<SVGGElement>(null)
  const right = useRef<SVGGElement>(null)
  const state = useRef({ angle: scaleAngle(score), velocity: 0 })
  const target = scaleAngle(score)

  useEffect(() => {
    const paint = () => {
      const { angle, velocity } = state.current
      beam.current?.setAttribute('transform', `rotate(${angle.toFixed(2)} ${PIVOT_X} ${PIVOT_Y})`)
      left.current?.setAttribute('transform', panTransform(-1, angle, velocity))
      right.current?.setAttribute('transform', panTransform(1, angle, velocity))
    }
    const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce || typeof requestAnimationFrame !== 'function') {
      state.current = { angle: target, velocity: 0 }
      paint()
      return
    }
    let frame = 0
    let last = performance.now()
    const step = (now: number) => {
      const dt = Math.min(0.032, (now - last) / 1000)
      last = now
      const s = state.current
      s.velocity += (-STIFFNESS * (s.angle - target) - DAMPING * s.velocity) * dt
      s.angle += s.velocity * dt
      if (Math.abs(s.angle - target) < 0.02 && Math.abs(s.velocity) < 0.05) {
        s.angle = target
        s.velocity = 0
        paint()
        return
      }
      paint()
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target])

  // Position de montage figée : React ne doit pas réécrire la transformation à chaque score, c’est l’animation qui la pilote.
  const mounted = useRef(scaleAngle(score)).current
  const pan = (ref: typeof left, side: -1 | 1) => (
    <g ref={ref} transform={panTransform(side, mounted, 0)}>
      <line x1="0" y1="0" x2="-40" y2="62" stroke="#171717" strokeWidth="5" />
      <line x1="0" y1="0" x2="40" y2="62" stroke="#171717" strokeWidth="5" />
      <path d="M-48 62 H48 Q42 90 0 90 Q-42 90 -48 62 Z" fill="#171717" />
    </g>
  )

  return (
    <svg
      viewBox="0 0 400 200"
      width="104"
      height="52"
      aria-hidden="true"
      focusable="false"
      data-testid="trust-scale"
      data-angle={target.toFixed(2)}
      className={`flex-none transition-opacity duration-500 ${score === null ? 'opacity-50' : ''}`}
    >
      <path d="M160 190 Q200 172 240 190 Z" fill="#171717" />
      <rect x="195" y="63" width="10" height="122" rx="4" fill="#171717" />
      <g ref={beam} transform={`rotate(${mounted.toFixed(2)} ${PIVOT_X} ${PIVOT_Y})`}>
        <rect x="30" y="56" width="340" height="14" rx="7" fill="#171717" />
        <circle cx="200" cy="63" r="14" fill="#171717" />
      </g>
      <circle cx="200" cy="63" r="4" fill="#fafafa" />
      {pan(left, -1)}
      {pan(right, 1)}
    </svg>
  )
}
