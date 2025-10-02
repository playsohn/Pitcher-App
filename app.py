# app.py
# FastAPI web app: Techno Playlist Finder – API-Key protected
import os, time, json, threading, queue, re, base64, csv
import urllib.parse, urllib.request, urllib.error
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

APP_TITLE = "Techno Playlist Finder – Web"
USER_AGENT = "TechnoPlaylistFinder/Server-1.1"
HTTP_TIMEOUT = 8
HTTP_RETRIES = 2

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
DUCKDUCKGO_HTML = "https://duckduckgo.com/html/?q={q}&kl=wt-wde&kp=1"

MAX_SPOTIFY_PAGES = int(os.getenv("MAX_SPOTIFY_PAGES", "3"))
MAX_LINKS_PER_QUERY = int(os.getenv("MAX_LINKS_PER_QUERY", "6"))
PER_DOMAIN_COOLDOWN = float(os.getenv("PER_DOMAIN_COOLDOWN", "0.8"))
GLOBAL_COOLDOWN = float(os.getenv("GLOBAL_COOLDOWN", "0.15"))

API_KEY = os.getenv("API_KEY", "")  # required for protected routes

TECHNO_GENRES = [
    "Techno","Hard Techno","Industrial Techno","Peak Time Techno","Dark Techno",
    "Acid Techno","Melodic Techno","Warehouse Techno","Rave Techno","Schranz",
    "Driving Techno","Raw Techno","Hypnotic Techno","Minimal Techno"
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+")
URL_RE = re.compile(r"(https?://[^\s\"'<>]+)")
SOCIAL_REGEXES = [
    re.compile(r"(https?://(www\.)?instagram\.com/[A-Za-z0-9_.]+)/?"),
    re.compile(r"(https?://(www\.)?facebook\.com/[A-Za-z0-9_.-]+)/?"),
    re.compile(r"(https?://(www\.)?x\.com/[A-Za-z0-9_.-]+)/?"),
    re.compile(r"(https?://(www\.)?twitter\.com/[A-Za-z0-9_.-]+)/?"),
    re.compile(r"(https?://(www\.)?soundcloud\.com/[A-Za-z0-9_.-]+)/?"),
    re.compile(r"(https?://(www\.)?bandcamp\.com/[A-Za-z0-9_.-]+)/?"),
    re.compile(r"(https?://(www\.)?youtube\.com/[A-Za-z0-9_.\-/?=&]+)"),
]

TRUSTED_PLATFORMS = {"soundplate.com","dailyplaylists.com","groover.co","artist.tools","droptrack.com","electronicradar.com","imusician.pro"}
FREE_EMAILS = {"gmail.com","outlook.com","hotmail.com","yahoo.com","proton.me","protonmail.com","gmx.de","web.de","icloud.com","me.com"}

# ---- Globals ----
JOBS: Dict[str, Dict[str, Any]] = {}
TOK_CACHE: Dict[str, Any] = {"access_token":"","exp":0}

# ---- Security ----
def require_key(x_api_key: str = Header(None)):
    if not API_KEY:
        return  # open for local testing if unset
    if x_api_key != API_KEY:
        raise HTTPException(401, "unauthorized")

# ---- Utils ----
_last_hit_by_domain = {}
def _cooldown_for(url: str):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        host = ""
    now = time.time()
    last = _last_hit_by_domain.get(host, 0.0)
    wait_needed = PER_DOMAIN_COOLDOWN - (now - last)
    if wait_needed > 0:
        time.sleep(wait_needed)
    _last_hit_by_domain[host] = time.time()
    time.sleep(GLOBAL_COOLDOWN)

def _with_retries(func, *args, **kwargs):
    last = None
    for i in range(HTTP_RETRIES+1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last = e
            time.sleep(0.25 * (i+1))
    raise last

def http_post(url, data, headers=None, timeout=8):
    def do():
        _cooldown_for(url)
        payload = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers or {}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    return _with_retries(do)

def http_get(url, headers=None, timeout=8):
    def do():
        _cooldown_for(url)
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    return _with_retries(do)

def get_spotify_token():
    now = time.time()
    if TOK_CACHE["access_token"] and TOK_CACHE["exp"] > now + 30:
        return TOK_CACHE["access_token"]
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        raise RuntimeError("Spotify credentials missing")
    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
    raw = http_post("https://accounts.spotify.com/api/token", {"grant_type":"client_credentials"}, headers=headers)
    data = json.loads(raw)
    TOK_CACHE["access_token"] = data.get("access_token","")
    TOK_CACHE["exp"] = now + int(data.get("expires_in", 3600))
    return TOK_CACHE["access_token"]

def spotify_get(path, token, params=None):
    url = f"https://api.spotify.com/v1{path}"
    if params: url += "?" + urllib.parse.urlencode(params)
    headers = {"Authorization": f"Bearer {token}"}
    raw = http_get(url, headers=headers); return json.loads(raw or "{}")

def search_playlists(query, token, limit=20, offset=0):
    return spotify_get("/search", token, params={"q":query, "type":"playlist", "limit":limit, "offset":offset})

def get_playlist(playlist_id, token):
    return spotify_get(f"/playlists/{playlist_id}", token)

def duckduckgo_search(query):
    url = "https://duckduckgo.com/html/?q={q}&kl=wt-wde&kp=1".format(q=urllib.parse.quote(query))
    try:
        html_text = http_get(url, headers={"User-Agent": USER_AGENT}, timeout=8) or ""
    except Exception:
        return []
    links = re.findall(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"', html_text)
    out = []
    for href in links:
        try:
            href = urllib.parse.unquote(href)
            parsed = urllib.parse.urlparse(href); qs = urllib.parse.parse_qs(parsed.query)
            real = qs.get('uddg',[href])[0]
            if real.startswith("http"):
                out.append(real.split("#")[0])
        except Exception:
            continue
    return out[:6]

def extract_contacts_from_html(html_text):
    emails = set(re.findall(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+", html_text or ""))
    socials = set()
    for rx in [
        re.compile(r"(https?://(www\.)?instagram\.com/[A-Za-z0-9_.]+)/?"),
        re.compile(r"(https?://(www\.)?facebook\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?x\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?twitter\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?soundcloud\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?bandcamp\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?youtube\.com/[A-Za-z0-9_.\-/?=&]+)"),
    ]:
        for m in rx.findall(html_text or ""):
            socials.add(m[0])
    return sorted(emails), sorted(socials)

def extract_from_spotify_description(desc_text):
    emails = set(re.findall(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9.\-]+", desc_text or ""))
    urls = set(re.findall(r"(https?://[^\s\"'<>]+)", desc_text or ""))
    socials = set()
    for rx in [
        re.compile(r"(https?://(www\.)?instagram\.com/[A-Za-z0-9_.]+)/?"),
        re.compile(r"(https?://(www\.)?facebook\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?x\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?twitter\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?soundcloud\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?bandcamp\.com/[A-Za-z0-9_.-]+)/?"),
        re.compile(r"(https?://(www\.)?youtube\.com/[A-Za-z0-9_.\-/?=&]+)"),
    ]:
        for m in rx.findall(desc_text or ""):
            socials.add(m[0])
    return sorted(emails), sorted(urls | socials)

def domain_from_url(u):
    try:
        host = urllib.parse.urlparse(u).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""

def verify_email(email, source_url, owner_name=""):
    FREE_EMAILS = {"gmail.com","outlook.com","hotmail.com","yahoo.com","proton.me","protonmail.com","gmx.de","web.de","icloud.com","me.com"}
    TRUSTED_PLATFORMS = {"soundplate.com","dailyplaylists.com","groover.co","artist.tools","droptrack.com","electronicradar.com","imusician.pro"}
    em_dom = (email.split("@")[-1] or "").lower()
    src_dom = domain_from_url(source_url)
    if em_dom == src_dom or (src_dom and em_dom.endswith("." + src_dom)) or em_dom in TRUSTED_PLATFORMS:
        return True
    if owner_name and any(tok for tok in owner_name.lower().split() if tok and tok in em_dom):
        return True
    if em_dom in FREE_EMAILS:
        return False
    if src_dom in TRUSTED_PLATFORMS:
        return True
    return False

def flatten_rows(results: List[dict]) -> List[dict]:
    rows = []
    for base in results:
        contacts = base.get("contacts", [])
        if not contacts:
            rows.append({
                "genre": base.get("genre",""),
                "playlist_name": base.get("playlist_name",""),
                "playlist_url": base.get("playlist_url",""),
                "followers": base.get("followers",0),
                "owner_name": base.get("owner_name",""),
                "owner_url": base.get("owner_url",""),
                "owner_id": base.get("owner_id",""),
                "contact_source": "",
                "contact_emails": "",
                "contact_socials": "",
                "contact_verified": False,
            })
        else:
            for c in contacts:
                rows.append({
                    "genre": base.get("genre",""),
                    "playlist_name": base.get("playlist_name",""),
                    "playlist_url": base.get("playlist_url",""),
                    "followers": base.get("followers",0),
                    "owner_name": base.get("owner_name",""),
                    "owner_url": base.get("owner_url",""),
                    "owner_id": base.get("owner_id",""),
                    "contact_source": c.get("source_url",""),
                    "contact_emails": "; ".join(c.get("emails",[])),
                    "contact_socials": "; ".join(c.get("socials",[])),
                    "contact_verified": c.get("verified", False),
                })
    return rows

def run_job(job):
    job["status"] = "running"
    job["progress"] = 0
    job["log"].put("Starte Job …")
    try:
        token = get_spotify_token()
    except Exception as e:
        job["status"] = "error"
        job["log"].put(f"Auth-Fehler: {e}")
        return
    genres = job["params"]["genres"]
    min_followers = job["params"]["min_followers"]
    queries = [f"{g} playlist" for g in genres]
    results = []
    seen_playlists = set()
    step_total = max(len(queries),1)
    job["total_steps"] = step_total
    for q in queries:
        if job["cancel"]: break
        job["log"].put(f"Spotify-Suche: {q}")
        for page in range(3):
            if job["cancel"]: break
            try:
                data = search_playlists(q, token, limit=20, offset=page*20) or {}
            except Exception as e:
                job["log"].put(f"Spotify API Fehler: {e}")
                break
            items = (((data.get("playlists") or {}).get("items")) or [])
            if not items: break
            for idx, it in enumerate(items):
                if job["cancel"]: break
                if not isinstance(it, dict): continue
                plid = it.get("id")
                if not plid or plid in seen_playlists: continue
                seen_playlists.add(plid)
                try:
                    det = get_playlist(plid, token) or {}
                except Exception:
                    continue
                followers = int(((det.get("followers") or {}).get("total")) or 0)
                if followers < min_followers: continue
                owner = (det.get("owner") or {})
                owner_id = owner.get("id","")
                owner_name = owner.get("display_name") or owner_id or ""
                owner_urls = owner.get("external_urls") or {}
                owner_url = owner_urls.get("spotify","")
                pl_urls = det.get("external_urls") or {}
                pl_url = pl_urls.get("spotify","")
                row = {
                    "genre": q.replace(" playlist",""),
                    "playlist_name": det.get("name",""),
                    "playlist_url": pl_url,
                    "followers": followers,
                    "owner_name": owner_name, "owner_id": owner_id, "owner_url": owner_url,
                    "contacts": []
                }
                desc = det.get("description") or ""
                desc_emails, desc_urls = extract_from_spotify_description(desc)
                if desc_emails or desc_urls:
                    verified = [e for e in desc_emails if verify_email(e, "https://open.spotify.com", owner_name)]
                    row["contacts"].append({
                        "source_url": "spotify:description",
                        "emails": verified,
                        "raw_emails": desc_emails,
                        "socials": [u for u in desc_urls if any(dom in u for dom in ["instagram.com","facebook.com","x.com","twitter.com","soundcloud.com","bandcamp.com","youtube.com"])],
                        "verified": bool(verified),
                    })
                for rq in [f"{owner_name} contact OR kontakt OR impressum email submit music",
                           f"{row['playlist_name']} contact OR kontakt OR submit music email"][:2]:
                    if job["cancel"]: break
                    links = duckduckgo_search(rq)
                    for link in links:
                        try:
                            html = http_get(link, headers={"User-Agent": USER_AGENT}, timeout=8)
                        except Exception:
                            continue
                        emails, socials = extract_contacts_from_html(html)
                        verified = [e for e in emails if verify_email(e, link, owner_name)]
                        if verified or socials:
                            row["contacts"].append({
                                "source_url": link,
                                "emails": verified,
                                "raw_emails": emails,
                                "socials": socials,
                                "verified": bool(verified),
                            })
                        time.sleep(0.03)
                results.append(row)
                job["last_item"] = {"playlist": row["playlist_name"], "owner": owner_name, "url": row["playlist_url"]}
            time.sleep(0.05)
        job["progress"] += 1
    job["results"] = results
    job["status"] = "cancelled" if job["cancel"] else "done"
    job["log"].put("Job beendet." if not job["cancel"] else "Job abgebrochen.")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title=APP_TITLE)
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def html_page():
    genres_options = "".join([f'<label><input type="checkbox" name="genre" value="{g}" {"checked" if g in ["Techno","Hard Techno","Melodic Techno","Peak Time Techno"] else ""}/> {g}</label><br/>' for g in TECHNOGENRES]) if False else ""
    # Simplify: regenerate options:
    gopts = "".join([f'<label><input type="checkbox" name="genre" value="{g}" {"checked" if g in ["Techno","Hard Techno","Melodic Techno","Peak Time Techno"] else ""}/> {g}</label><br/>' for g in TECHNOGENRES]) if False else ""
    # Build manually to avoid variable name typo:
    opts = ""
    for g in ["Techno","Hard Techno","Industrial Techno","Peak Time Techno","Dark Techno","Acid Techno","Melodic Techno","Warehouse Techno","Rave Techno","Schranz","Driving Techno","Raw Techno","Hypnotic Techno","Minimal Techno"]:
        checked = "checked" if g in ["Techno","Hard Techno","Melodic Techno","Peak Time Techno"] else ""
        opts += f'<label><input type="checkbox" name="genre" value="{g}" {checked}/> {g}</label><br/>'
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{APP_TITLE}</title></head>
<body><h3>{APP_TITLE}</h3>
<label>Min. Follower: <input type="number" id="minf" value="2500" min="0"/></label>
<button onclick="startJob()">Suche starten</button>
<button onclick="cancelJob()">Abbrechen</button>
<button onclick="exportNow()">Jetzt exportieren</button>
<h4>Genres</h4><div id="genres">{opts}</div>
<pre id="log"></pre>
<script>
let JOB_ID = null, es=null;
async function startJob(){{
  const genres=[...document.querySelectorAll('input[name=genre]:checked')].map(x=>x.value);
  const minf=parseInt(document.getElementById('minf').value||'0');
  const res=await fetch('/start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{genres,min_followers:minf}})}});
  const data=await res.json(); JOB_ID=data.job_id; log('Job '+JOB_ID);
  es = new EventSource('/progress/'+JOB_ID);
  es.onmessage=(ev)=>{{ const d=JSON.parse(ev.data); if(d.type==='log') log(d.msg);}};
}}
function log(s){{ const el=document.getElementById('log'); el.textContent+=s+"\\n"; el.scrollTop=el.scrollHeight;}}
async function cancelJob(){{ if(!JOB_ID) return; await fetch('/cancel/'+JOB_ID,{{method:'POST'}}); log('Abbruch angefordert'); }}
function exportNow(){{ if(!JOB_ID) return alert('Kein Job'); window.open('/export/html/'+JOB_ID,'_blank'); }}
</script></body></html>"""
@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(html_page())

from fastapi import Depends

@app.post("/start")
def start_job(req: dict, _=Depends(require_key)):
    genres = req.get("genres") or []
    min_followers = int(req.get("min_followers") or 0)
    if not genres: raise HTTPException(400, "genres required")
    job_id = f"job_{int(time.time()*1000)}"
    job = {"id":job_id,"status":"queued","progress":0,"total_steps":0,"params":{"genres":genres,"min_followers":min_followers},"results":[],"cancel":False,"log":queue.Queue(),"last_item":{}}
    JOBS[job_id]=job
    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return {"job_id": job_id}

@app.post("/cancel/{job_id}")
def cancel_job(job_id: str, _=Depends(require_key)):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(404, "job not found")
    job["cancel"] = True
    return {"ok": True}

@app.get("/progress/{job_id}")
def progress(job_id: str):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(404, "job not found")
    def gen():
        yield f"data {{\"type\":\"log\",\"msg\":\"connect\"}}\n\n"
        while True:
            try:
                while True:
                    msg = job['log'].get_nowait()
                    yield f"data {json.dumps({'type':'log','msg':msg})}\n\n"
            except queue.Empty:
                pass
            if job.get("status") in ("done","cancelled","error"):
                yield f"data {json.dumps({'type':'done','status':job.get('status')})}\n\n"
                break
            time.sleep(0.8)
    return StreamingResponse(gen(), media_type="text/event-stream")

def rows_for_export(job_id: str):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(404, "job not found")
    return flatten_rows(job.get("results", []))

from fastapi.responses import HTMLResponse

@app.get("/export/html/{job_id}", response_class=HTMLResponse)
def export_html(job_id: str):
    rows = rows_for_export(job_id)
    def esc(s): return (str(s) or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    html=["<html><head><meta charset='utf-8'><title>Export</title></head><body><table border='1' cellpadding='6'>"]
    html.append("<tr><th>Genre</th><th>Playlist</th><th>Follower</th><th>Owner</th><th>Kontakt</th></tr>")
    for r in rows or []:
        html.append("<tr><td>"+esc(r.get("genre",""))+"</td><td>"+esc(r.get("playlist_name",""))+"</td><td>"+str(int(r.get("followers",0)))+"</td><td>"+esc(r.get("owner_name",""))+"</td><td>"+esc(r.get("contact_emails",""))+"</td></tr>")
    html.append("</table></body></html>")
    return HTMLResponse("".join(html))
