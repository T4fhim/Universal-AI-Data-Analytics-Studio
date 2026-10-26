// The status strip (C6, T2/T5 K7): 17 px plus a 2 px separator: key/value pairs on the left, the clock on the right.
//
// The clock is UTC and refreshes every 15 s: a status clock needs minute accuracy, and a
// per-second timer would re-render the strip 60x more for nothing.
import { useEffect, useState } from 'react'
import { useWorkbenchData } from './dataContext.ts'
import { AREAS } from './panes.ts'
import type { AreaId } from './panes.ts'

function utcClock(): string {
  return new Date().toISOString().slice(11, 16)
}

export function StatusStrip({ area }: { area: AreaId }) {
  const [clock, setClock] = useState(utcClock)
  useEffect(() => {
    const timer = window.setInterval(() => setClock(utcClock()), 15_000)
    return () => window.clearInterval(timer)
  }, [])
  const label = AREAS.find((a) => a.id === area)?.label ?? ''
  const { active, upload } = useWorkbenchData()
  return (
    <footer className="status" aria-label="Status">
      <span>
        <span className="dim">View</span> {label}
      </span>
      <span>
        <span className="dim">Dataset</span>{' '}
        {active ? `${active.name} (${active.row_count.toLocaleString('en')} x ${active.column_count})` : 'none'}
      </span>
      <span>
        <span className="dim">Jobs</span> {upload.status === 'busy' ? 1 : 0}
      </span>
      <span className="status-clock">
        <span className="dim">UTC</span> {clock}
      </span>
    </footer>
  )
}
