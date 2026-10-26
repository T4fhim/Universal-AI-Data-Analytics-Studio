// Which view fills which pane tab.
//
// Why a lookup and not JSX inside Pane: Pane is the C6 frame (tab strip, collapse, maximise) and
// should not know what the panes contain. A tab with no entry here keeps its hint text, which is
// how panes whose views are not built yet (rules, report, chart) stay honest placeholders.
import type { ReactNode } from 'react'
import type { PaneId } from '../panes.ts'
import { DataView } from './DataView.tsx'
import { InspectorView } from './InspectorView.tsx'
import { ProfileView } from './ProfileView.tsx'
import { LineageView, SchemaView } from './SchemaView.tsx'
import './views.css'

export function paneBody(pane: PaneId, tab: string): ReactNode {
  switch (`${pane}/${tab}`) {
    case 'data/grid':
      return <DataView />
    case 'inspector/inspector':
      return <InspectorView />
    case 'schema/schema':
      return <SchemaView />
    case 'schema/lineage':
      return <LineageView />
    case 'profile/profile':
      return <ProfileView />
    default:
      return null
  }
}
