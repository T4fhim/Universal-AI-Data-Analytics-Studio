// The 36 px chrome band: a menu row and a toolbar row in one flat colour (C6, T2/T5 K4).
//
// Only the View menu exists. File, Edit and Help are left out on purpose until they have real
// actions: a menu of disabled placeholders would be a control that names an action it cannot
// perform. View carries the five areas (decision 3: opened from the menu and keys 1-5, no
// separate nav control), pane visibility, the switch for single-key shortcuts (WCAG 2.1.4),
// and "Reset layout".
import * as Menubar from '@radix-ui/react-menubar'
import { Button } from '../components/controls.tsx'
import { useWorkbenchData } from './dataContext.ts'
import { CheckIcon, DotIcon } from './icons.tsx'
import { AREAS, PANES, PANE_ORDER } from './panes.ts'
import type { AreaId, PaneId } from './panes.ts'

interface ChromeBandProps {
  area: AreaId
  maximised: PaneId | null
  collapsed: Record<PaneId, boolean>
  singleKeys: boolean
  onOpenArea: (area: AreaId) => void
  onTogglePane: (pane: PaneId) => void
  onSingleKeys: (on: boolean) => void
  onReset: () => void
  onMenuClosed: (event: Event) => void
}

export function ChromeBand({
  area,
  maximised,
  collapsed,
  singleKeys,
  onOpenArea,
  onTogglePane,
  onSingleKeys,
  onReset,
  onMenuClosed,
}: ChromeBandProps) {
  const { phase, user, datasets, active, setActiveId, upload, openPicker, signOut } = useWorkbenchData()
  const empty = datasets.length === 0
  const unavailable = phase !== 'ready' || upload.status === 'busy'
  return (
    <header className="chrome">
      <Menubar.Root className="menubar" aria-label="Application menu">
        <Menubar.Menu>
          <Menubar.Trigger className="menu-trigger">View</Menubar.Trigger>
          <Menubar.Portal>
            <Menubar.Content className="menu" align="start" sideOffset={0} loop onCloseAutoFocus={onMenuClosed}>
              <Menubar.Group aria-label="Areas">
                <Menubar.Label className="menu-label" aria-hidden>
                  Areas
                </Menubar.Label>
                <Menubar.RadioGroup value={area}>
                  {AREAS.map((a) => (
                    <Menubar.RadioItem
                      key={a.id}
                      className="menu-item"
                      value={a.id}
                      aria-keyshortcuts={singleKeys ? a.key : undefined}
                      onSelect={() => onOpenArea(a.id)}
                    >
                      <span className="menu-indicator">
                        <Menubar.ItemIndicator>
                          <DotIcon />
                        </Menubar.ItemIndicator>
                      </span>
                      <span>{a.label}</span>
                      {singleKeys && (
                        <span className="menu-shortcut" aria-hidden>
                          {a.key}
                        </span>
                      )}
                    </Menubar.RadioItem>
                  ))}
                </Menubar.RadioGroup>
              </Menubar.Group>
              <Menubar.Separator className="menu-separator" />
              <Menubar.Group aria-label="Panes">
                <Menubar.Label className="menu-label" aria-hidden>
                  Panes
                </Menubar.Label>
                {PANE_ORDER.map((id) => (
                  <Menubar.CheckboxItem
                    key={id}
                    className="menu-item"
                    checked={!collapsed[id]}
                    disabled={maximised !== null}
                    onCheckedChange={() => onTogglePane(id)}
                  >
                    <span className="menu-indicator">
                      <Menubar.ItemIndicator>
                        <CheckIcon />
                      </Menubar.ItemIndicator>
                    </span>
                    <span>{PANES[id].title}</span>
                  </Menubar.CheckboxItem>
                ))}
              </Menubar.Group>
              <Menubar.Separator className="menu-separator" />
              <Menubar.CheckboxItem className="menu-item" checked={singleKeys} onCheckedChange={onSingleKeys}>
                <span className="menu-indicator">
                  <Menubar.ItemIndicator>
                    <CheckIcon />
                  </Menubar.ItemIndicator>
                </span>
                <span>Single-key shortcuts (1-5)</span>
              </Menubar.CheckboxItem>
              <Menubar.Item className="menu-item" onSelect={onReset}>
                <span className="menu-indicator" />
                <span>Reset layout</span>
              </Menubar.Item>
            </Menubar.Content>
          </Menubar.Portal>
        </Menubar.Menu>
      </Menubar.Root>
      <div className="toolbar">
        {/* aria-disabled, not disabled: a disabled button that has focus drops it to the page. */}
        <Button id="open-file" onClick={unavailable ? undefined : openPicker} aria-disabled={unavailable || undefined}>
          Open file...
        </Button>
        <select
          className="field"
          aria-label="Dataset"
          aria-describedby={empty ? 'dataset-reason' : undefined}
          disabled={empty}
          value={active?.id ?? ''}
          onChange={(event) => setActiveId(event.target.value)}
        >
          {empty ? (
            <option value="">No dataset loaded</option>
          ) : (
            datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))
          )}
        </select>
        {empty && (
          <span id="dataset-reason" className="visually-hidden">
            Upload a dataset to enable this list.
          </span>
        )}
        {user && (
          <>
            <span className="toolbar-user">{user.email}</span>
            <Button onClick={() => void signOut()}>Sign out</Button>
          </>
        )}
      </div>
    </header>
  )
}
