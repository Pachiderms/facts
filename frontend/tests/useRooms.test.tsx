import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const listRooms = vi.fn()
vi.mock('../src/api/client', () => ({ listRooms: (...a: unknown[]) => listRooms(...a) }))

import { useRooms } from '../src/hooks/useRooms'

const flush = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

describe('useRooms : recherche', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    listRooms.mockReset()
    listRooms.mockResolvedValue([])
  })
  afterEach(() => vi.useRealTimers())

  it('transmet la recherche au serveur et relance la requête quand elle change', async () => {
    const { rerender } = renderHook(({ q }) => useRooms(q), { initialProps: { q: '' } })
    await flush(0)
    expect(listRooms.mock.calls[0]![0]).toBe('')
    rerender({ q: 'smic' })
    await flush(0)
    expect(listRooms).toHaveBeenCalledTimes(2)
    expect(listRooms.mock.calls[1]![0]).toBe('smic')
  })

  it('l’ancienne recherche est annulée quand la nouvelle démarre', async () => {
    const { rerender } = renderHook(({ q }) => useRooms(q), { initialProps: { q: 'a' } })
    await flush(0)
    const firstSignal = listRooms.mock.calls[0]![1] as AbortSignal
    rerender({ q: 'ab' })
    expect(firstSignal.aborted).toBe(true)
  })
})

describe('useRooms : rafraîchissement poli', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    listRooms.mockReset()
  })
  afterEach(() => {
    vi.useRealTimers()
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
  })

  it('rafraîchit toutes les 15 s', async () => {
    listRooms.mockResolvedValue([])
    renderHook(() => useRooms())
    await flush(0)
    expect(listRooms).toHaveBeenCalledTimes(1)
    await flush(15_000)
    expect(listRooms).toHaveBeenCalledTimes(2)
  })

  it('espace les tentatives après des erreurs (30 s puis 60 s) au lieu d’insister', async () => {
    listRooms.mockRejectedValue(new Error('Trop de requêtes.'))
    renderHook(() => useRooms())
    await flush(0)
    expect(listRooms).toHaveBeenCalledTimes(1)
    await flush(29_000)
    expect(listRooms).toHaveBeenCalledTimes(1)
    await flush(1_000)
    expect(listRooms).toHaveBeenCalledTimes(2)
    await flush(59_000)
    expect(listRooms).toHaveBeenCalledTimes(2)
    await flush(1_000)
    expect(listRooms).toHaveBeenCalledTimes(3)
  })

  it('revient au rythme normal après un succès', async () => {
    listRooms.mockRejectedValueOnce(new Error('x')).mockResolvedValue([])
    renderHook(() => useRooms())
    await flush(0)
    await flush(30_000)
    expect(listRooms).toHaveBeenCalledTimes(2)
    await flush(15_000)
    expect(listRooms).toHaveBeenCalledTimes(3)
  })

  it('suspend les appels quand l’onglet est caché', async () => {
    listRooms.mockResolvedValue([])
    renderHook(() => useRooms())
    await flush(0)
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    await flush(60_000)
    expect(listRooms).toHaveBeenCalledTimes(1)
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    await flush(15_000)
    expect(listRooms).toHaveBeenCalledTimes(2)
  })

  it('arrête tout au démontage', async () => {
    listRooms.mockResolvedValue([])
    const { unmount } = renderHook(() => useRooms())
    await flush(0)
    unmount()
    await flush(60_000)
    expect(listRooms).toHaveBeenCalledTimes(1)
  })
})
