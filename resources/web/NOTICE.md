# Provenance: `plotly.min.js`

Vendored verbatim from the `plotly` Python package's own `package_data/plotly.min.js`
(the same bundle `figure.to_html(include_plotlyjs=True)` already inlines into every chart
render today — see `PLOTLY_VERSION.txt` for the exact version it was copied from).

## Why a vendored copy instead of `include_plotlyjs=True`

Milestone 15's `chart_view.py` wrote a fresh ~4.7 MB HTML file per rendered chart, inlining
this same bundle every time, and never deleted the file (`tempfile.NamedTemporaryFile(...,
delete=False)`) — the "R2" temp-file leak the UI overhaul plan names as a live defect.
Milestone 16 fixes this by loading a static `chart_host.html` page once per process (staged
into a single process-lifetime temp directory — see `src/ui/web/web_assets.py`) that
`<script src="plotly.min.js">`-references this file, then pushing new figure data into the
already-loaded page over `QWebChannel`/`runJavaScript` (`Plotly.react`) instead of writing
a new file and reloading the page for every chart.

## Updating

Re-run:

```powershell
Copy-Item .venv\Lib\site-packages\plotly\package_data\plotly.min.js resources\web\plotly.min.js
python -c "import plotly; print(plotly.__version__)" | Out-File resources\web\PLOTLY_VERSION.txt -Encoding ascii -NoNewline
```

after bumping the `plotly` dependency in `requirements.txt`, so the vendored copy and the
Python package version stay in lockstep — a mismatch would mean the Python side
(`figure.to_json()`) and the JS side (`Plotly.newPlot`/`Plotly.react`) speak different
figure-schema versions.
