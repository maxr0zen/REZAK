# Rezak frontend

React with Vite. FastAPI remains the backend and serves the production build from
`rezak/static/react`; no Node.js server is needed to run the desktop application.

Build from the project root:

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
```

For development, start the normal FastAPI application on port 8765, then run
`npm.cmd --prefix frontend run dev` and open Vite's `/static/react/` URL.
The dev server proxies `/api` and shared static assets to FastAPI.

`src/App.jsx` owns application state and status polling; `components.jsx` contains
the stable journal and queue controls; `TwitchSettings.jsx` contains channel/LIVE
and secret settings forms; `Editor.jsx` handles prompt edits, trimming and ROI.
No legacy DOM patcher or HTML-string rendering is used by the React application.
The existing shared CSS and local fonts retain the studio's visual design.

Status polling never keys forms, dialogs or video by API snapshot. The journal
uses stable log IDs, incremental requests, explicit follow mode and instant scroll.
Client secrets are sent only to FastAPI; the settings API returns a saved flag.
