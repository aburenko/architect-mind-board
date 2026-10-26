# Mind Board

A small self-hosted sticky-note board: **FastAPI + SQLite**, plain HTML/JavaScript,
no Node.js, frontend build, external database, AI account, or internet connection
needed at runtime. Python 3.10+; Raspberry Pi OS Bookworm or newer recommended.

## Features

- Multiple named boards, editable notes, colours, hierarchy, and categories.
- Drag/pan/zoom, manual connections, circle/category sorting, and undo sort.
- Automatic SQLite saves, JSON import/export, and a visible save indicator.
- Optimistic revision checks prevent another tab/device from silently overwriting
  your work. Use **one editor at a time** and reload before editing elsewhere.
  On a conflict, export unsaved changes, reload, then import that backup as new
  boards. This is not a real-time collaboration app.
- The original embedded-Claude AI controls have been removed. Imported existing
  analysis remains readable. Fonts use local system fallbacks.

## Run locally

Create a virtual environment with `python3 -m venv .venv`, install dependencies
with `.venv/bin/pip install -r requirements.txt`, then start with
`.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1`.

Open <http://localhost:8000>. Run from the project directory; do not open the HTML
directly. The database is created automatically under the ignored data directory.
Set `MINDBOARD_DB` to an absolute database path to store it elsewhere.

Saves are debounced by 400 ms. **Wait for “Saved to SQLite” before closing a tab**.
If the server is offline, keep the tab open: saves retry, and export still works.
The complete collection is saved atomically per edit batch (8 MiB request limit),
which keeps the implementation small and suits personal, modest-sized boards.

## Install on a Raspberry Pi

These commands are for the Pi itself. Copy this project into `/opt/mindboard`
first (for example using Git or SCP). Its contents must be readable by the service
account. Installation commands require administrator privileges.

1. Install Python and virtual-environment support: `sudo apt update` and
   `sudo apt install -y python3 python3-venv`.
2. Create the service account:
   `sudo useradd --system --user-group --home-dir /var/lib/mindboard --shell /usr/sbin/nologin mindboard`.
   Skip this step if that account already exists.
3. Create the environment: `sudo python3 -m venv /opt/mindboard/.venv`.
4. Install dependencies:
   `sudo /opt/mindboard/.venv/bin/pip install -r /opt/mindboard/requirements.txt`.
5. Install the supplied [systemd service](deploy/mindboard.service):
   `sudo cp /opt/mindboard/deploy/mindboard.service /etc/systemd/system/mindboard.service`.
6. Run `sudo systemctl daemon-reload`, then `sudo systemctl enable --now mindboard`.
7. Open `http://<pi-ip-address>:8000` from a browser on your LAN. Use `hostname -I`
   on the Pi to find its address. Permit TCP port 8000 on your LAN firewall if needed.

Check status with `sudo systemctl status mindboard`; view logs with
`sudo journalctl -u mindboard -n 100 --no-pager`. The service starts on boot and
stores its database in `/var/lib/mindboard/mindboard.sqlite3`; systemd creates and
owns that directory. The app runs as an unprivileged user with a read-only system
filesystem apart from its state directory. One Uvicorn worker is sufficient.

**Trusted LAN only:** there is no login, user isolation, or HTTPS. Anyone who can
reach the app can read and edit all boards. Do not port-forward it to the internet.
For remote access, use a private VPN or an authenticated HTTPS reverse proxy.

## Backups and existing boards

Use **Export all boards** to download a portable JSON backup; **Import file** adds
boards without replacing existing ones. Original Mind Board JSON exports work.
Browser-only boards are not automatically transferred from the original page;
import an existing export to move them to the server. If the original page cannot
export outside its embedded environment, its browser data is still untouched.

For a full database backup on the Pi, stop the service with
`sudo systemctl stop mindboard`, copy the database to a safe location, and restart
with `sudo systemctl start mindboard`. Do not copy only the main database file
while the service is running: committed data may still be in SQLite's WAL file.
To restore, stop the service, replace the database with your backup, ensure it is
owned by `mindboard:mindboard`, and start the service again.

## Development and API

Install test dependencies with `.venv/bin/pip install -r requirements-dev.txt` and
run `.venv/bin/python -m pytest -q`. Tests use isolated temporary databases.

- `GET /health`: database connectivity check.
- `GET /api/state`: collection snapshot and revision.
- `PUT /api/state`: validated, atomic snapshot save; requires the current revision
  and `X-Mindboard: 1` with JSON content. Stale revisions return HTTP 409.
- `/docs`: generated API documentation (set the custom header for writes).

SQLite stores the editor's versioned JSON values in a key/value table and a
separate revision counter, retaining all note/layout fields without an ORM.
Only the HTML and browser storage script are served; the database is never exposed
as a static file.