# Trace Viewer

Open `index.html` in a browser and load a trace JSON file using the file picker,
or run the Python server for `/api/trace`.

For stateful-aware scheduling visualization, prefer loading traces through
`/api/trace?path=...`. That path enriches the trace with viewer metadata derived
from the benchmark `deploy_config`, so the graph can distinguish serialized
stateful tool chains from later stateless fan-out and report tool-graph depth
and width.

Example (serve with Python endpoint):

```bash
$ uv run python -m tools.trace_viewer_server --port 8000
```

Then open `http://localhost:8000/web/trace_viewer/` and click **Load URL**.
