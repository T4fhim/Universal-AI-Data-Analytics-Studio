// The calm first-run pane (decision 10): what to do when there is no data yet, and nothing else.
//
// Why so little: a new user's first minute should be one obvious action. There is no tour, no
// sample-data picker and no empty chart; the same pane also shows the progress of the upload
// that ends it, so the transition from "nothing" to "a grid" happens in place.
//
// Why the button stays (aria-disabled, not removed) while an upload runs: a focused button that
// disappears or becomes `disabled` drops keyboard focus to the page; this one keeps it.
import { Button } from '../../components/controls.tsx'
import { useWorkbenchData } from '../dataContext.ts'

export function FirstRun() {
  const { upload, openPicker } = useWorkbenchData()
  const busy = upload.status === 'busy'

  return (
    <div className="view view-center">
      <div className="first-run">
        {busy ? (
          <>
            <h2 className="view-title">
              {upload.step === 'uploading' ? 'Sending' : 'Reading'} {upload.name}
            </h2>
            <progress className="meter" aria-label="Progress" max={100} value={upload.step === 'processing' ? upload.progress : undefined} />
          </>
        ) : (
          <>
            <h2 className="view-title">No data yet</h2>
            <p className="dim">Open a file, or drop one anywhere in this pane. CSV, Excel, JSON, Parquet and other common formats work.</p>
          </>
        )}
        <div className="form-actions">
          <Button onClick={busy ? undefined : openPicker} aria-disabled={busy || undefined}>
            Open a file...
          </Button>
        </div>
      </div>
    </div>
  )
}
