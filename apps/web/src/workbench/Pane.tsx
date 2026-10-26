// One workbench pane: a tab strip that doubles as the title bar, a body, and collapse/maximise
// controls (the C6 pane, plans/phase-4-design-reference.md T5 K1/K3).
//
// Why Radix Tabs: the tab strip needs the full ARIA tabs pattern (roving focus, arrow keys,
// Home/End); Radix supplies behaviour only, every pixel of styling is ours (decision 11).
// A pane has three tab colours: focused-active, unfocused-active and inactive; the pane-level
// `data-focused` attribute selects between the first two in CSS.
//
// A maximised pane is the same element positioned over the dock by CSS (data-maximised), so it
// keeps its state and its focused control. While another pane is maximised this one is `inert`.
import * as Tabs from '@radix-ui/react-tabs'
import type { ReactNode } from 'react'
import { ChevronDownIcon, ChevronRightIcon, MaximiseIcon, RestoreIcon } from './icons.tsx'
import type { PaneDef } from './panes.ts'

interface PaneProps {
  def: PaneDef
  activeTab: string
  onTab: (tab: string) => void
  focused: boolean
  collapsed: boolean
  maximised: boolean
  hidden: boolean
  onFocusPane: () => void
  onToggleCollapse: () => void
  onToggleMaximise: () => void
  // The view for a tab, or null to show the tab's hint (a placeholder for a view not built yet).
  body: (tab: string) => ReactNode
}

export function Pane({
  def,
  activeTab,
  onTab,
  focused,
  collapsed,
  maximised,
  hidden,
  onFocusPane,
  onToggleCollapse,
  onToggleMaximise,
  body,
}: PaneProps) {
  const id = `pane-${def.id}`

  if (collapsed && !maximised) {
    return (
      <section
        id={id}
        className="pane pane-collapsed"
        data-collapses={def.collapses}
        aria-label={def.title}
        inert={hidden}
      >
        <button type="button" className="collapsed-button" aria-label={`Expand ${def.title}`} onClick={onToggleCollapse}>
          {def.collapses === 'width' ? <ChevronRightIcon /> : <ChevronDownIcon />}
          <span>{def.title}</span>
        </button>
      </section>
    )
  }

  return (
    <section
      id={id}
      className="pane"
      aria-label={def.title}
      tabIndex={-1}
      inert={hidden}
      data-focused={focused || undefined}
      data-maximised={maximised || undefined}
      onFocusCapture={onFocusPane}
      onPointerDownCapture={onFocusPane}
    >
      <Tabs.Root className="pane-root" value={activeTab} onValueChange={onTab}>
        <div className="pane-strip">
          <Tabs.List className="pane-tablist" aria-label={`${def.title} views`}>
            {def.tabs.map((tab) => (
              <Tabs.Trigger key={tab.id} className="tab" value={tab.id}>
                <span className="tab-label">{tab.label}</span>
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <div className="pane-actions">
            <button
              type="button"
              className="icon-button"
              aria-label={`Collapse ${def.title}`}
              disabled={maximised}
              onClick={onToggleCollapse}
            >
              <ChevronDownIcon />
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label={`Maximise ${def.title}`}
              aria-pressed={maximised}
              onClick={onToggleMaximise}
            >
              {maximised ? <RestoreIcon /> : <MaximiseIcon />}
            </button>
          </div>
        </div>
        {def.tabs.map((tab) => (
          <Tabs.Content key={tab.id} className="pane-body" value={tab.id}>
            {body(tab.id) ?? <p className="empty">{tab.hint}</p>}
          </Tabs.Content>
        ))}
      </Tabs.Root>
    </section>
  )
}
