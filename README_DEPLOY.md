# Techno Playlist Finder – Web (API-Key geschützt)
Siehe Anleitung im Chat. Kurz:
- Render Web Service erstellen, ENV setzen: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `API_KEY`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- iPhone Safari öffnen: `https://<dein-host>/`
- Shortcut nutzt `POST /start` mit Header `X-API-Key`.
