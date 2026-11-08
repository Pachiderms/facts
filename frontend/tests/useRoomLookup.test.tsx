import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api/client'

const lookupRoom = vi.fn()
vi.mock('../src/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api/client')>()),
  lookupRoom: (...a: unknown[]) => lookupRoom(...a),
}))

import { useRoomLookup } from '../src/hooks/useRoomLookup'

const LOOKUP = { id: 'room-1', visibility: 'public', requires_code: false, room: null }

describe('useRoomLookup', () => {
  beforeEach(() => {
    lookupRoom.mockReset() // sans `return` : une fonction renvoyée par beforeEach serait exécutée comme nettoyage
  })

  it.each(['', 'a b', '<script>', 'A'.repeat(3), '../x', 'é'])('identifiant vide ou invalide (%j) : aucune requête', (id) => {
    const { result } = renderHook(() => useRoomLookup(id))
    expect(result.current.status).toBe('idle')
    expect(lookupRoom).not.toHaveBeenCalled()
  })

  it('trouve un salon', async () => {
    lookupRoom.mockResolvedValue(LOOKUP)
    const { result } = renderHook(() => useRoomLookup('room-1'))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current).toEqual({ status: 'found', lookup: LOOKUP }))
    expect(lookupRoom.mock.calls[0]![0]).toBe('room-1')
  })

  it('404 : salon inexistant', async () => {
    lookupRoom.mockImplementation(() => Promise.reject(new ApiError(404, 'Salon introuvable.')))
    const { result } = renderHook(() => useRoomLookup('zzzzzzzz'))
    await waitFor(() => expect(result.current.status).toBe('missing'))
  })

  it('autre erreur : message conservé', async () => {
    lookupRoom.mockImplementation(() => Promise.reject(new ApiError(0, 'Serveur injoignable.')))
    const { result } = renderHook(() => useRoomLookup('room-1'))
    await waitFor(() => expect(result.current).toEqual({ status: 'error', message: 'Serveur injoignable.' }))
  })

  it('changer d’identifiant annule la requête précédente : pas de résultat périmé', async () => {
    let signalOfFirst: AbortSignal | undefined
    lookupRoom.mockImplementationOnce((_id: string, signal: AbortSignal) => {
      signalOfFirst = signal
      return new Promise((resolve) => setTimeout(() => resolve({ ...LOOKUP, id: 'room-1' }), 30))
    })
    lookupRoom.mockResolvedValueOnce({ ...LOOKUP, id: 'room-2' })
    const { result, rerender } = renderHook(({ id }) => useRoomLookup(id), { initialProps: { id: 'room-1' } })
    rerender({ id: 'room-2' })
    await waitFor(() => expect(result.current).toMatchObject({ status: 'found', lookup: { id: 'room-2' } }))
    expect(signalOfFirst?.aborted).toBe(true)
    await new Promise((r) => setTimeout(r, 60))
    expect(result.current).toMatchObject({ lookup: { id: 'room-2' } })
  })
})
