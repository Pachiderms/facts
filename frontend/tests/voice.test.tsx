import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchFeatures, transcribeAudio } from '../src/api/client'
import { Composer } from '../src/components/arena/Composer'
import { pickMimeType } from '../src/lib/voice'

class FakeRecorder {
  static instances: FakeRecorder[] = []
  static supported = ['audio/webm;codecs=opus', 'audio/mp4']
  static isTypeSupported = (m: string) => FakeRecorder.supported.includes(m)
  state: 'inactive' | 'recording' = 'inactive'
  mimeType: string
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  constructor(
    public stream: MediaStream,
    opts?: { mimeType?: string },
  ) {
    this.mimeType = opts?.mimeType ?? 'audio/webm'
    FakeRecorder.instances.push(this)
  }
  start() {
    this.state = 'recording'
  }
  stop() {
    if (this.state !== 'recording') return
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['audio-bytes'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

const trackStop = vi.fn()
let getUserMedia: ReturnType<typeof vi.fn>

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(() => {
  FakeRecorder.instances = []
  trackStop.mockClear()
  getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: trackStop }] })
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const renderComposer = (onSend = vi.fn(() => true)) => {
  render(<Composer role="A" status="open" onSend={onSend} voiceEnabled />)
  return onSend
}

describe('bouton de dictée', () => {
  it('est absent si la voix est indisponible', () => {
    render(<Composer role="A" status="open" onSend={() => true} />)
    expect(screen.queryByRole('button', { name: /dicter/i })).toBeNull()
  })

  it('demande le consentement avant le premier enregistrement et ne touche pas au micro avant', async () => {
    const user = userEvent.setup()
    renderComposer()
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    expect(screen.getByRole('dialog')).toHaveTextContent(/envoyée à Groq/)
    expect(getUserMedia).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /refuser/i }))
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(localStorage.getItem('facts.voice-consent')).toBeNull()
  })

  it('enregistre, transcrit, place le texte dans le champ SANS l’envoyer, et libère le micro', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ text: 'Le chômage a baissé.', duration_seconds: 3 }))
    const onSend = renderComposer()
    await user.type(screen.getByRole('textbox'), 'Début.')
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    await user.click(screen.getByRole('button', { name: /j.accepte/i }))
    await screen.findByRole('button', { name: /terminer l'enregistrement/i })
    await user.click(screen.getByRole('button', { name: /terminer l'enregistrement/i }))
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue('Début. Le chômage a baissé.'))
    expect(onSend).not.toHaveBeenCalled()
    expect(trackStop).toHaveBeenCalled()
    expect(localStorage.getItem('facts.voice-consent')).toBe('1')
    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url)).toMatch(/\/api\/v1\/transcribe$/)
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers['X-Participant-Token']).toMatch(/^[A-Za-z0-9_-]{22,64}$/)
    expect(headers['Content-Type']).toBe('audio/webm;codecs=opus')
  })

  it('annuler ne contacte pas le serveur', async () => {
    localStorage.setItem('facts.voice-consent', '1')
    const user = userEvent.setup()
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    renderComposer()
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    await screen.findByRole('button', { name: /annuler l'enregistrement/i })
    await user.click(screen.getByRole('button', { name: /annuler l'enregistrement/i }))
    await screen.findByRole('button', { name: /dicter/i })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(trackStop).toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it("s'arrête seul après 30 secondes", async () => {
    localStorage.setItem('facts.voice-consent', '1')
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ text: 'ok', duration_seconds: 30 }))
      renderComposer()
      await act(async () => {
        screen.getByRole('button', { name: /dicter/i }).click()
      })
      await screen.findByRole('button', { name: /terminer/i })
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000)
      })
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
      expect(FakeRecorder.instances[0]!.state).toBe('inactive')
    } finally {
      vi.useRealTimers()
    }
  })

  it('affiche un message clair si le micro est refusé', async () => {
    localStorage.setItem('facts.voice-consent', '1')
    getUserMedia.mockRejectedValue(new DOMException('no', 'NotAllowedError'))
    const user = userEvent.setup()
    renderComposer()
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/accès au micro refusé/i)
  })

  it('affiche l’erreur serveur (quota) sans détail technique et garde le texte saisi', async () => {
    localStorage.setItem('facts.voice-consent', '1')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'Limite quotidienne de messages vocaux atteinte. Écrivez votre message.' }, 429))
    const user = userEvent.setup()
    renderComposer()
    await user.type(screen.getByRole('textbox'), 'Mon texte')
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    await user.click(await screen.findByRole('button', { name: /terminer l'enregistrement/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/limite quotidienne/i)
    expect(screen.getByRole('textbox')).toHaveValue('Mon texte')
  })

  it('libère le micro si le composant est démonté en cours d’enregistrement', async () => {
    localStorage.setItem('facts.voice-consent', '1')
    const user = userEvent.setup()
    const { unmount } = render(<Composer role="A" status="open" onSend={() => true} voiceEnabled />)
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    await screen.findByRole('button', { name: /terminer/i })
    unmount()
    expect(trackStop).toHaveBeenCalled()
  })

  it('le texte dicté respecte la longueur maximale', async () => {
    localStorage.setItem('facts.voice-consent', '1')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ text: 'a'.repeat(900), duration_seconds: 20 }))
    const user = userEvent.setup()
    renderComposer()
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    await user.click(await screen.findByRole('button', { name: /terminer/i }))
    await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value.length).toBe(500))
  })
})

describe('dictée et réponse combinées', () => {
  it('un message dicté en réponse garde le message cité, et rien ne part avant le clic', async () => {
    localStorage.setItem('facts.voice-consent', '1')
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ text: 'Je réponds oralement.', duration_seconds: 4 }))
    const onSend = vi.fn(() => true)
    const user = userEvent.setup()
    render(<Composer role="A" status="open" onSend={onSend} voiceEnabled replyTo={{ id: 7, speaker: 2, preview: 'Cité' }} />)
    await user.click(screen.getByRole('button', { name: /dicter/i }))
    await user.click(await screen.findByRole('button', { name: /terminer/i }))
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue('Je réponds oralement.'))
    expect(onSend).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /^envoyer$/i }))
    expect(onSend).toHaveBeenCalledWith('Je réponds oralement.', 7)
  })
})

describe('client vocal', () => {
  it('pickMimeType choisit le premier format pris en charge', () => {
    expect(pickMimeType()).toBe('audio/webm;codecs=opus')
    FakeRecorder.supported = ['audio/mp4']
    expect(pickMimeType()).toBe('audio/mp4')
    FakeRecorder.supported = ['audio/webm;codecs=opus', 'audio/mp4']
  })

  it('fetchFeatures retombe sur « sans voix » en cas d’erreur ou de réponse hors contrat', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('réseau'))
    expect((await fetchFeatures()).voice).toBe(false)
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse({ voice: 'yes' }))
    expect((await fetchFeatures()).voice).toBe(false)
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(jsonResponse({ voice: true }))
    expect((await fetchFeatures()).voice).toBe(true)
  })

  it('transcribeAudio rejette une réponse sans texte', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ text: '  ' }))
    await expect(transcribeAudio(new Blob(['x'], { type: 'audio/webm' }))).rejects.toThrow()
  })
})
