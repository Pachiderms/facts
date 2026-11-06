import { useRef, useState } from 'react'
import { RoomList } from '../components/arena/RoomList'
import { RoomView } from '../components/arena/RoomView'
import { useRooms } from '../hooks/useRooms'

export function ArenaPage() {
  const { rooms, error } = useRooms()
  const [chosen, setChosen] = useState<string | null>(null)
  const roomRef = useRef<HTMLDivElement>(null)

  // Écran étroit : la liste des salons est au-dessus du débat ; on amène le débat choisi à l'écran.
  const choose = (id: string) => {
    setChosen(id)
    if (window.matchMedia?.('(max-width: 1023px)').matches) {
      requestAnimationFrame(() => roomRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }))
    }
  }

  // Sans choix explicite, on ouvre le premier salon disponible ; si le salon choisi disparaît, idem.
  const selectedId = rooms?.find((r) => r.id === chosen)?.id ?? rooms?.[0]?.id ?? null
  const selected = rooms?.find((r) => r.id === selectedId)

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
      <div className="lg:col-span-1">
        <RoomList rooms={rooms} error={error} selectedId={selectedId} onSelect={choose} />
      </div>
      <div ref={roomRef} className="scroll-mt-20 lg:col-span-3">
        {selectedId ? (
          <RoomView key={selectedId} roomId={selectedId} fallback={selected} />
        ) : (
          <p className="rounded-2xl border border-neutral-200 bg-white p-8 text-center text-sm text-neutral-500">
            {rooms && rooms.length === 0 ? 'Aucun salon ouvert pour le moment.' : 'Connexion au serveur…'}
          </p>
        )}
      </div>
    </div>
  )
}
