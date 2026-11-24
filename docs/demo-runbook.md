# Demo runbook

Two ways to run: a **demo family** (made-up history, for rehearsal and for the look of the app) and the
**real station**. For the pitch, the newest wash must come from the real station. Everything older in the demo
family is made up and tagged "Demo data".

## Once

    make install                                   # Python env from uv.lock
    cp .env.example .env                           # set CONVERGENT_API_TOKEN to a long random string
    cd web && npm ci && npm run build && cd ..     # builds web/dist, which the backend serves

## A. Demo family (no camera)

Shortcut: double-click `START_SCRUBBLE_DEMO.command` (or `bash START_SCRUBBLE_DEMO.command`). It builds the app, starts a demo
backend on port 8010, seeds the family, opens the browser and prints the developer links. The manual steps:

Terminal 1:

    CONVERGENT_DEMO_MODE=true CONVERGENT_DATABASE_URL=sqlite:///./scrubble_demo.db .venv/bin/python -m convergent.cli backend

Terminal 2:

    .venv/bin/python scripts/seed_demo_family.py --url http://127.0.0.1:8000 --reset

Open http://127.0.0.1:8000/ (grown-up view) or http://127.0.0.1:8000/kid (kid view). You see Sam with Mia (active) and Leo. Mia has 24 washes, about 1,000 points,
one germ bought, and is one wash away from Soap Canyon on the map.

Send a simulated wash to watch the app react live (tagged "Demo data", never claim it as real):

    .venv/bin/python scripts/send_test_wash.py --url http://127.0.0.1:8000 --miss thumbs

Reset: run the seed command with `--reset` again. Both scripts refuse a backend that is not in demo mode, and
the reset endpoint does not exist outside demo mode. To throw the demo away, delete `scrubble_demo.db`.

## B. Real station feeding the demo family (the pitch)

Keep Terminal 1 and the seeded family from A. Check that Mia is the selected child (the Child picker). Then, from your own
Terminal app (the camera needs its permission):

    .venv/bin/python -m convergent.cli camera --device 1 --show --game --auto-wash --save-results --backend http

`--backend http` uses `backend.base_url` in `configs/development.yaml` (port 8000). The Pi, calibration and
projector steps are unchanged: `docs/HARDWARE_DAY_RUNBOOK.md`.

Wash. Four seconds after the hands leave, the wash is saved. Expected in the open app, with no reload:

1. Kid view, Live: the step tiles fill while the hands scrub, then the result shows.
2. Toast "New wash from the sink" in either view.
3. Kid view, Home: the goal count and points go up.
4. Grown-up view, Station: step 3 and 4 show the new wash, and it is the top row of the sync log tagged "Sink",
   with the delay between the wash ending and the app receiving it. Its wash ID matches
   `runs/<session>/washes.jsonl` on the laptop.
5. Grown-up view, Washes: the new row opens the score arithmetic and the zones table.

Proof to capture separately (not for the video):

    tail -1 runs/*/washes.jsonl | head -c 300
    sqlite3 scrubble_demo.db "select wash_id, source, points, reward_points, created_utc from washes order by created_utc desc limit 1"
    .venv/bin/python -m convergent.cli wash-queue

## 30 second click path

Desktop layout on the laptop, or Phone layout to show the phone frame. Start in the kid view on Live, Mia selected.

| Time | Do | Say only if true |
| --- | --- | --- |
| 0 to 8 s | Kid view, Live, while someone washes. Tiles fill, then the result. | "That is coming from the sink right now." |
| 8 to 13 s | Kid Home, then Germs. | "Germs are game characters tied to parts of the hand." |
| 13 to 20 s | Switch to Grown-up. Overview: score line, hand heatmap. | Name a weak zone only if the heatmap shows one. |
| 20 to 26 s | Station. The four steps, the sync log's top row. | "Only numbers are sent. No video leaves the laptop." |
| 26 to 30 s | Open that wash. The score arithmetic. | "The score is recognized scrubbing time." |

Do not say: clean, germ-free, bacteria removed, clinically, detects soap. The score is recognized scrubbing
time. Accuracy for Q&A is in `docs/PITCH_INFO.md`.

## If something fails

| Problem | Do |
| --- | --- |
| No toast, app says Offline | The browser lost the backend. Reload. Washes are not lost. |
| Wash finished, nothing arrives | `convergent.cli wash-queue`. Waiting: the backend was unreachable, it uploads when back (`--send` forces it). Parked: read the reason (wrong token is the usual one), fix, `--retry-dead`. |
| Backend was off during the wash | Start it. The next camera run uploads the queued wash, or use `wash-queue --send`. Say it is a replay if you show it. |
| Wrong child got the wash | The wash went to whoever was selected. Select the right child before washing. There is no move button. |
| Camera or model trouble | Show a simulated wash and say so, or play recorded footage and say it is a recording. |

## Phone on the same Wi-Fi

Start the backend with `CONVERGENT_API_HOST=0.0.0.0` and open `http://<laptop-ip>:8000/`. The app has no
login, so anyone on that network can open it. Do this on a hotspot or home network only, not campus Wi-Fi.
