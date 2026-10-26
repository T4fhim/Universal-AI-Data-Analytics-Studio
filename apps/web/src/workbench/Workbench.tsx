// The Instrument workbench shell: chrome band, the C6 dock, status strip.
//
// What it does (plans/phase-4-design-reference.md, decisions 1 and 3): a fixed arrangement of
// five panes (data grid, inspector, rules/report, profile/chart, schema/lineage) whose sizes the
// user changes by dragging a gutter or pressing its arrows; any pane can be collapsed to a
// strip or maximised; sizes persist in localStorage. The five areas (Data, Clean, Analyze,
// Visualize, Report) are views opened from the View menu or the keys 1-5: each reveals,
// focuses or maximises existing panes and never swaps in a different layout.
//
// Why the dock is never unmounted: maximising a pane is pure CSS (the pane is positioned over
// the dock), so every pane keeps its state, its size and its focused element. The only way the
// dock remounts is "Reset layout" (a key bump), because the groups read their saved layout
// once, when they mount.
//
// Focus: a pane's controls can unmount under the user (collapse swaps the pane for a strip), so
// every action that must leave focus somewhere sensible records a *focus request*; one effect
// moves focus after the render that made the target exist. Actions are also announced through a
// polite live region, because collapse, maximise and area changes are otherwise silent.
//
// Single-character shortcuts (1-5) can be switched off from the View menu (WCAG 2.1.4); F6 and
// Escape are not character keys.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Group, Panel, Separator, useDefaultLayout, usePanelRef } from 'react-resizable-panels'
import './workbench.css'
import { ChromeBand } from './ChromeBand.tsx'
import { Pane } from './Pane.tsx'
import { StatusStrip } from './StatusStrip.tsx'
import { AREAS, DEFAULT_SIZES, GROUP_IDS, PANES, PANE_ORDER, STORAGE_PREFIX } from './panes.ts'
import type { AreaDef, AreaId, PaneId } from './panes.ts'
import { paneBody } from './views/index.tsx'

type ByPane<T> = Record<PaneId, T>
type PanelRefs = ByPane<ReturnType<typeof usePanelRef>>

const COLLAPSED_SIZE = '1.5rem'
const NOT_COLLAPSED: ByPane<boolean> = { data: false, inspector: false, rules: false, profile: false, schema: false }
const FIRST_TABS = Object.fromEntries(PANE_ORDER.map((id) => [id, PANES[id].tabs[0].id])) as ByPane<string>
const SINGLE_KEYS_KEY = 'uadas-single-key-shortcuts'
// Keys typed into these must never be taken as shortcuts.
const TYPING_TARGETS =
  'input, textarea, select, [contenteditable=""], [contenteditable="true"], [role="menu"], [role="textbox"], [role="combobox"], [role="listbox"], [role="slider"]'

// localStorage can throw (private windows, blocked site data): the setting then is not remembered.
const storage = {
  getItem(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },
  setItem(key: string, value: string): void {
    try {
      localStorage.setItem(key, value)
    } catch {
      /* not remembered */
    }
  },
}

function clearSavedLayouts(): void {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.includes(STORAGE_PREFIX)) localStorage.removeItem(key)
    }
  } catch {
    /* nothing stored */
  }
}

// The panel handles are stable objects, so the bundle is created once per mount.
function usePaneRefs(): PanelRefs {
  const data = usePanelRef()
  const inspector = usePanelRef()
  const rules = usePanelRef()
  const profile = usePanelRef()
  const schema = usePanelRef()
  return useMemo(() => ({ data, inspector, rules, profile, schema }), [data, inspector, rules, profile, schema])
}

// Moves focus into a pane: its section when expanded, its expand button when collapsed.
function focusPane(id: PaneId): void {
  const pane = document.getElementById(`pane-${id}`)
  if (!pane) return
  if (pane.classList.contains('pane-collapsed')) pane.querySelector<HTMLElement>('button')?.focus()
  else pane.focus()
}

interface DockProps {
  refs: PanelRefs
  tabs: ByPane<string>
  focused: PaneId
  collapsed: ByPane<boolean>
  maximised: PaneId | null
  onTab: (pane: PaneId, tab: string) => void
  onFocusPane: (pane: PaneId) => void
  onToggleCollapse: (pane: PaneId) => void
  onToggleMaximise: (pane: PaneId) => void
  onCollapsedChange: (pane: PaneId) => void
}

function Dock(props: DockProps) {
  const { refs, tabs, focused, collapsed, maximised, onTab, onFocusPane, onToggleCollapse, onToggleMaximise, onCollapsedChange } = props
  const main = useDefaultLayout({ id: GROUP_IDS.main, storage })
  const left = useDefaultLayout({ id: GROUP_IDS.left, storage })
  const top = useDefaultLayout({ id: GROUP_IDS.top, storage })
  const right = useDefaultLayout({ id: GROUP_IDS.right, storage })

  const pane = (id: PaneId) => (
    <Pane
      def={PANES[id]}
      activeTab={tabs[id]}
      onTab={(tab) => onTab(id, tab)}
      focused={focused === id}
      collapsed={collapsed[id]}
      maximised={maximised === id}
      hidden={maximised !== null && maximised !== id}
      onFocusPane={() => onFocusPane(id)}
      onToggleCollapse={() => onToggleCollapse(id)}
      onToggleMaximise={() => onToggleMaximise(id)}
      body={(tab) => paneBody(id, tab)}
    />
  )
  const collapsible = (id: PaneId, defaultSize: string) => ({
    id,
    panelRef: refs[id],
    collapsible: true,
    collapsedSize: COLLAPSED_SIZE,
    minSize: '12%',
    defaultSize,
    className: 'fill',
    onResize: () => onCollapsedChange(id),
  })

  return (
    <Group id={GROUP_IDS.main} orientation="horizontal" className="fill" defaultLayout={main.defaultLayout} onLayoutChanged={main.onLayoutChanged}>
      <Panel id="left" defaultSize={DEFAULT_SIZES.main.left} minSize="30%" className="fill">
        <Group id={GROUP_IDS.left} orientation="vertical" className="fill" defaultLayout={left.defaultLayout} onLayoutChanged={left.onLayoutChanged}>
          <Panel id="top" defaultSize={DEFAULT_SIZES.left.top} minSize="25%" className="fill">
            <Group id={GROUP_IDS.top} orientation="horizontal" className="fill" defaultLayout={top.defaultLayout} onLayoutChanged={top.onLayoutChanged}>
              <Panel {...collapsible('data', DEFAULT_SIZES.top.data)}>{pane('data')}</Panel>
              <Separator className="sep" aria-label="Resize data and inspector" />
              <Panel {...collapsible('inspector', DEFAULT_SIZES.top.inspector)}>{pane('inspector')}</Panel>
            </Group>
          </Panel>
          <Separator className="sep" aria-label="Resize data panes and schema" />
          <Panel {...collapsible('schema', DEFAULT_SIZES.left.bottom)}>{pane('schema')}</Panel>
        </Group>
      </Panel>
      <Separator className="sep" aria-label="Resize left and right panes" />
      <Panel id="right" defaultSize={DEFAULT_SIZES.main.right} minSize="15%" className="fill">
        <Group id={GROUP_IDS.right} orientation="vertical" className="fill" defaultLayout={right.defaultLayout} onLayoutChanged={right.onLayoutChanged}>
          <Panel {...collapsible('rules', DEFAULT_SIZES.right.rules)}>{pane('rules')}</Panel>
          <Separator className="sep" aria-label="Resize rules and profile" />
          <Panel {...collapsible('profile', DEFAULT_SIZES.right.profile)}>{pane('profile')}</Panel>
        </Group>
      </Panel>
    </Group>
  )
}

export function Workbench() {
  const [area, setArea] = useState<AreaId>('data')
  const [focused, setFocused] = useState<PaneId>('data')
  const [maximised, setMaximised] = useState<PaneId | null>(null)
  const [collapsed, setCollapsed] = useState(NOT_COLLAPSED)
  const [tabs, setTabs] = useState(FIRST_TABS)
  const [layoutVersion, setLayoutVersion] = useState(0)
  const [singleKeys, setSingleKeys] = useState(() => storage.getItem(SINGLE_KEYS_KEY) !== 'off')
  const [announcement, setAnnouncement] = useState({ text: '', n: 0 })
  const [focusTick, setFocusTick] = useState(0)
  const focusTarget = useRef<PaneId | null>(null)
  const menuPicked = useRef(false)
  const refs = usePaneRefs()

  const announce = useCallback((text: string) => setAnnouncement((a) => ({ text, n: a.n + 1 })), [])

  const requestFocus = useCallback((id: PaneId) => {
    focusTarget.current = id
    setFocusTick((t) => t + 1)
  }, [])

  // Moves focus after the render that made the target exist; sets no state.
  useEffect(() => {
    const id = focusTarget.current
    if (!id) return
    focusTarget.current = null
    focusPane(id)
  }, [focusTick])

  const syncCollapsed = (id: PaneId) => {
    const panel = refs[id].current
    if (!panel) return // the panel is unmounting
    const value = panel.isCollapsed()
    setCollapsed((prev) => (prev[id] === value ? prev : { ...prev, [id]: value }))
  }

  // Collapsing and expanding set the flag at once (the panel's own resize report follows) so the
  // pane swaps to its strip, or back, in the same render that focus is requested for.
  const setPaneCollapsed = useCallback(
    (id: PaneId, value: boolean) => {
      const panel = refs[id].current
      if (!panel) return
      if (value) panel.collapse()
      else panel.expand()
      setCollapsed((prev) => (prev[id] === value ? prev : { ...prev, [id]: value }))
    },
    [refs],
  )

  const togglePane = (id: PaneId) => {
    const next = !collapsed[id]
    setPaneCollapsed(id, next)
    announce(`${PANES[id].title} ${next ? 'collapsed' : 'expanded'}`)
    requestFocus(id)
  }

  const toggleMaximise = (id: PaneId) => {
    const next = maximised === id ? null : id
    setMaximised(next)
    setFocused(id)
    announce(`${PANES[id].title} ${next ? 'maximised' : 'restored'}`)
    requestFocus(id)
  }

  const openArea = useCallback(
    (def: AreaDef) => {
      setArea(def.id)
      setMaximised(def.maximise ?? null)
      if (def.tab) {
        const { pane, tab } = def.tab
        setTabs((prev) => ({ ...prev, [pane]: tab }))
      }
      for (const id of def.reveal) setPaneCollapsed(id, false)
      setFocused(def.focus)
      announce(`${def.label} area opened`)
      requestFocus(def.focus)
    },
    [setPaneCollapsed, announce, requestFocus],
  )

  const reset = () => {
    clearSavedLayouts()
    setCollapsed(NOT_COLLAPSED)
    setMaximised(null)
    setTabs(FIRST_TABS)
    setArea('data')
    setLayoutVersion((v) => v + 1)
    announce('Layout reset')
  }

  const changeSingleKeys = (on: boolean) => {
    setSingleKeys(on)
    storage.setItem(SINGLE_KEYS_KEY, on ? 'on' : 'off')
    announce(on ? 'Single-key shortcuts on' : 'Single-key shortcuts off')
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return
      // Typing into a field or driving a menu must not trigger a character or Escape shortcut; F6 is
      // not typed text, so it must keep working there (it is how a keyboard user leaves a field).
      const typing = Boolean((event.target as HTMLElement | null)?.closest(TYPING_TARGETS))
      const def = singleKeys && !typing ? AREAS.find((a) => a.key === event.key) : undefined
      if (def) {
        event.preventDefault()
        openArea(def)
      } else if (event.key === 'Escape' && maximised && !typing) {
        event.preventDefault()
        toggleMaximise(maximised)
      } else if (event.key === 'F6') {
        event.preventDefault()
        const visible = maximised ? [maximised] : PANE_ORDER.filter((id) => !collapsed[id])
        if (visible.length === 0) return
        const index = visible.indexOf(focused)
        const step = event.shiftKey ? -1 : 1
        const next = index === -1 ? visible[step === 1 ? 0 : visible.length - 1] : visible[(index + step + visible.length) % visible.length]
        setFocused(next)
        requestFocus(next)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="workbench">
      <ChromeBand
        area={area}
        maximised={maximised}
        collapsed={collapsed}
        singleKeys={singleKeys}
        onOpenArea={(id) => {
          menuPicked.current = true
          openArea(AREAS.find((a) => a.id === id)!)
        }}
        onTogglePane={togglePane}
        onSingleKeys={changeSingleKeys}
        onReset={reset}
        onMenuClosed={(event) => {
          // A menu-picked area moves focus itself; stop Radix returning it to the trigger.
          if (menuPicked.current) event.preventDefault()
          menuPicked.current = false
        }}
      />
      <main className="dock" aria-label="Workbench" data-has-maximised={maximised ? true : undefined}>
        <h1 className="visually-hidden">Instrument workbench</h1>
        <Dock
          key={layoutVersion}
          refs={refs}
          tabs={tabs}
          focused={focused}
          collapsed={collapsed}
          maximised={maximised}
          onTab={(pane, tab) => setTabs((prev) => ({ ...prev, [pane]: tab }))}
          onFocusPane={setFocused}
          onToggleCollapse={togglePane}
          onToggleMaximise={toggleMaximise}
          onCollapsedChange={syncCollapsed}
        />
      </main>
      <StatusStrip area={area} />
      <div className="visually-hidden" role="status">
        <span key={announcement.n}>{announcement.text}</span>
      </div>
    </div>
  )
}
