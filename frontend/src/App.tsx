import { useCallback, useEffect, useState } from 'react'
import { warmUp } from './api/client'
import { Footer, Header, Page, type PageId } from './components/Layout'
import { ArenaPage } from './pages/ArenaPage'
import { CheckPage } from './pages/CheckPage'

const fromHash = (): PageId => (window.location.hash === '#/arena' ? 'arena' : 'check')

export default function App() {
  const [page, setPage] = useState<PageId>(fromHash)

  useEffect(() => {
    warmUp() // réveille l'hébergeur gratuit pendant que l'utilisateur lit la page
    const onHash = () => setPage(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const navigate = useCallback((next: PageId) => {
    window.location.hash = next === 'arena' ? '#/arena' : '#/check'
    setPage(next)
  }, [])

  return (
    <div className="min-h-screen bg-neutral-100/70 font-sans text-neutral-900 selection:bg-neutral-900 selection:text-white">
      <Header page={page} onNavigate={navigate} />
      <Page>{page === 'check' ? <CheckPage /> : <ArenaPage />}</Page>
      <Footer />
    </div>
  )
}
