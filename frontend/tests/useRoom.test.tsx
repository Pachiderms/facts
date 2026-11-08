import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

interface Handlers {
  onEvent: (e: unknown) => void
  onStatus: (s: string) => void
}
const mocks = vi.hoisted(() => {
  const instances: Array<{
    roomId: string
    handlers: Handlers
    options: { code?: string }
    closed: boolean
    connect: ReturnType<typeof vi.fn>
  }> = []
  class FakeSocket {
    closed = false
    connect = vi.fn()
    send = vi.fn().mockReturnValue(true)
    constructor(
      public roomId: string,
      public handlers: Handlers,
      public options: { code?: string },
    ) {
      instances.push(this)
    }
    close() {
      this.closed = true
    }
  }
  return { instances, FakeSocket }
})
const instances = mocks.instances
vi.mock('../src/api/socket', () => ({ RoomSocket: mocks.FakeSocket }))

import { useRoom } from '../src/hooks/useRoom'

describe('useRoom', () => {
  beforeEach(() => {
    instances.length = 0
  })

  it('se connecte avec le code d’accès fourni', () => {
    renderHook(() => useRoom('abcd2345', 'k7m2xq'))
    expect(instances).toHaveLength(1)
    expect(instances[0]!.roomId).toBe('abcd2345')
    expect(instances[0]!.options).toEqual({ code: 'k7m2xq', spectate: false })
    expect(instances[0]!.connect).toHaveBeenCalled()
  })

  it('changer le code ferme l’ancienne connexion et en ouvre une nouvelle', () => {
    const { rerender } = renderHook(({ code }) => useRoom('abcd2345', code), { initialProps: { code: undefined as string | undefined } })
    rerender({ code: 'k7m2xq' })
    expect(instances).toHaveLength(2)
    expect(instances[0]!.closed).toBe(true)
    expect(instances[1]!.options.code).toBe('k7m2xq')
  })

  it('un refus d’accès du serveur est exposé sans notification générique', () => {
    const { result } = renderHook(() => useRoom('abcd2345'))
    act(() => instances[0]!.handlers.onEvent({ type: 'error', code: 'invalid_code', detail: 'x' }))
    expect(result.current.denied).toBe('invalid_code')
    expect(result.current.notice).toBeNull()
  })

  it('se ferme au démontage', () => {
    const { unmount } = renderHook(() => useRoom('abcd2345'))
    unmount()
    expect(instances[0]!.closed).toBe(true)
  })
})
