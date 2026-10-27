# 48hd-hover-plot
Create manhattan plots where you can hover and select sequences

Supports two config file layouts (detected automatically):
- **GS** — has an `SDB` column. Rows with `Input_CPM == 0` are dropped on load, and an SDB filter dropdown is shown.
- **R3** — no `SDB` column. All rows are kept.

## Run locally
```
pip install -r requirements.txt
python app.py            # set DASH_DEBUG=1 for debug mode
```

## Deploy on Render
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:server --workers 2 --threads 2 --timeout 180`
  (the long timeout covers parsing the ~50 MB GS xlsx)

Optional env vars:
- `CACHE_DIR` — where uploaded data is cached server-side (default `cache`)
- `DASH_DEBUG` — `1` to run `python app.py` in debug mode
