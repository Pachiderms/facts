import { useCallback, useEffect, useState } from 'react'
import { warmUp } from './api/client'
import { Footer, Header, Page, type PageId } from './components/Layout'
import { ArenaPage } from './pages/ArenaPage'
import { CheckPage } from './pages/CheckPage'
import { RoomPage } from './pages/RoomPage'
import { parseHash, type Route } from './lib/route'

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    warmUp() // réveille l'hébergeur gratuit pendant que l'utilisateur lit la page
    const onHash = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const navigate = useCallback((next: PageId) => {
    window.location.hash = next === 'arena' ? '#/arena' : '#/check'
  }, [])

  const page: PageId = route.name === 'check' ? 'check' : 'arena'

  return (
    <div className="min-h-screen bg-neutral-100/70 font-sans text-neutral-900 selection:bg-neutral-900 selection:text-white">
      <Header page={page} onNavigate={navigate} />
      <Page>
        {route.name === 'check' && <CheckPage />}
        {route.name === 'arena' && <ArenaPage />}
        {route.name === 'room' && <RoomPage key={route.id} id={route.id} inviteCode={route.code} />}
      </Page>
      <Footer />
    </div>
  )
}
