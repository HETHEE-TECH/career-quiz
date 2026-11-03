"""Career Path Quiz: FastAPI app.

Students open "/" and take the quiz (no login). Their answers are stored in SQLite.
Staff open "/admin" and sign in with a username and password to see the responses.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
import csv
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

# ---------------------------------------------------------------- settings
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")
DB_PATH = Path(os.getenv("DB_PATH", str(BASE / "data" / "responses.db")))
HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "0") == "1"
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"
try:
    TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Kolkata"))
except Exception:  # Windows has no time zone database unless "tzdata" is installed
    TZ = timezone(timedelta(hours=5, minutes=30), "IST")
SUBMIT_LIMIT = int(os.getenv("SUBMIT_LIMIT_PER_HOUR", "200"))  # per IP; a lab shares one IP
MAX_ROWS = 2000

if len(ADMIN_PASSWORD) < 8:
    raise RuntimeError("Set ADMIN_PASSWORD (at least 8 characters) in .env before starting the app.")
if len(SECRET_KEY) < 16:
    raise RuntimeError("Set SECRET_KEY (a long random string) in .env before starting the app.")

# ---------------------------------------------------------------- quiz data (one source for browser and server)
DATA = json.loads((BASE / "static" / "quiz-data.json").read_text(encoding="utf-8"))
Q = DATA["q"]
ORDER = DATA["order"]
CL = DATA["cl"]
GROUPS = DATA["groups"]  # the old 12th-group question; kept so older rows stay readable
DOING = DATA["doing"]
DOING_KEYS = [d["key"] for d in DOING]
LET = "ABCD"


def compute(ans):
    """Same scoring as the browser. Returns per-interest scores and the ranking."""
    score = {c: 0 for c in ORDER}
    tie = {c: 0.0 for c in ORDER}
    max_score = 0
    for i, q in enumerate(Q):
        if "m" not in q:
            continue
        max_score += q["w"]
        a = ans[i] if i < len(ans) else None
        if a is None or not 0 <= a < len(q["m"]):
            continue
        score[q["m"][a]] += q["w"]
    if len(ans) > 2 and ans[2] is not None:
        tie[Q[2]["m"][ans[2]]] += 0.2
    if len(ans) > 1 and ans[1] is not None:
        tie[Q[1]["m"][ans[1]]] += 0.1
    ranked = sorted(ORDER, key=lambda c: score[c] + tie[c], reverse=True)
    return {"score": score, "max": max_score, "ranked": ranked}


# ---------------------------------------------------------------- database
@contextmanager
def conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conn() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                grp TEXT NOT NULL DEFAULT '',
                doing TEXT NOT NULL DEFAULT '',
                answers TEXT NOT NULL,
                top TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )



def migrate_db():
    """Databases made before the "doing now" question get the new column."""
    with conn() as con:
        cols = {r["name"] for r in con.execute("PRAGMA table_info(responses)")}
        if "doing" not in cols:
            con.execute("ALTER TABLE responses ADD COLUMN doing TEXT NOT NULL DEFAULT ''")


init_db()
migrate_db()

# ---------------------------------------------------------------- small helpers
class Limiter:
    """Sliding-window counter kept in memory (resets when the app restarts)."""

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self.hits = defaultdict(deque)

    def _prune(self, key):
        q = self.hits[key]
        cutoff = time.time() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key):
        return len(self._prune(key)) >= self.limit

    def add(self, key):
        self._prune(key).append(time.time())


submit_limiter = Limiter(SUBMIT_LIMIT, 3600)
login_limiter = Limiter(5, 600)  # 5 wrong passwords per 10 minutes per IP


def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_admin(request: Request) -> bool:
    return request.session.get("admin") is True


def check_csrf(request: Request, token: str):
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Bad CSRF token")


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return ""


def csv_safe(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


# ---------------------------------------------------------------- app
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=8 * 3600,
    same_site="lax",
    https_only=HTTPS_ONLY,
    session_cookie="quiz_admin",
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/admin"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- student side
@app.get("/")
def quiz(request: Request):
    return templates.TemplateResponse(request, "quiz.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


class Submission(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phone: str = Field(default="", max_length=15)
    group: str = Field(default="", max_length=60)
    doing: str = Field(default="", max_length=30)
    answers: list[int | None]

    @field_validator("name")
    @classmethod
    def clean_name(cls, v):
        v = re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()
        if not v:
            raise ValueError("name required")
        return v

    @field_validator("phone")
    @classmethod
    def clean_phone(cls, v):
        v = v.strip()
        if not re.fullmatch(r"[0-9+\- ]{0,15}", v):
            raise ValueError("bad phone")
        return v

    @field_validator("group")
    @classmethod
    def clean_group(cls, v):
        if v and v not in GROUPS:
            raise ValueError("unknown group")
        return v

    @field_validator("doing")
    @classmethod
    def clean_doing(cls, v):
        if v and v not in DOING_KEYS:
            raise ValueError("unknown option")
        return v

    @field_validator("answers")
    @classmethod
    def clean_answers(cls, v):
        if len(v) != len(Q):
            raise ValueError("wrong number of answers")
        for i, a in enumerate(v):
            if a is None or not 0 <= a < len(Q[i]["o"]):
                raise ValueError("answer out of range")
        return v


@app.post("/api/submit")
def submit(request: Request, body: Submission):
    ip = client_ip(request)
    if submit_limiter.blocked(ip):
        return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
    submit_limiter.add(ip)
    top = compute(body.answers)["ranked"][0]  # computed here, never trusted from the browser
    with conn() as con:
        con.execute(
            "INSERT INTO responses (name, phone, grp, doing, answers, top, created_at) VALUES (?,?,?,?,?,?,?)",
            (body.name, body.phone, body.group, body.doing, json.dumps(body.answers), top,
             datetime.now(timezone.utc).isoformat()),
        )
    return {"ok": True}


# ---------------------------------------------------------------- admin
def prepare(row) -> dict:
    ans = json.loads(row["answers"])
    res = compute(ans)
    top = res["ranked"][0]

    def pick(labels, i):
        a = ans[i] if i < len(ans) else None
        return labels[a] if a is not None and 0 <= a < len(labels) else "—"

    qa = []
    for i, q in enumerate(Q):
        a = ans[i] if i < len(ans) else None
        text = f"{LET[a]}. {q['o'][a]}" if a is not None and 0 <= a < len(q["o"]) else "—"
        qa.append({"q": q["t"], "a": text})
    return {
        "id": row["id"],
        "name": row["name"],
        "phone": row["phone"],
        "group": row["grp"],
        "doing_key": row["doing"],
        "doing": next((d["en"] for d in DOING if d["key"] == row["doing"]), "—"),
        "when": fmt_time(row["created_at"]),
        "created_at": row["created_at"],
        "ans": ans,
        "top": top,
        "top_label": CL[top]["short"],
        "top_color": CL[top]["color"],
        "pct": {c: round(res["score"][c] / res["max"] * 100) if res["max"] else 0 for c in ORDER},
        "learn": pick(DATA["s_learn"], 6),
        "plan": pick(DATA["s_plan"], 9),
        "factor": pick(DATA["s_factor"], 8),
        "ready": pick(DATA["s_ready"], 0),
        "qa": qa,
    }


def load_rows(q: str, interest: str, sort: str):
    with conn() as con:
        raw = con.execute("SELECT * FROM responses ORDER BY id DESC LIMIT ?", (MAX_ROWS,)).fetchall()
    rows = [prepare(r) for r in raw]
    total_rows = list(rows)
    needle = q.strip().lower()
    if interest in ORDER:
        rows = [r for r in rows if r["top"] == interest]
    if needle:
        rows = [r for r in rows if needle in r["name"].lower() or needle in r["phone"]]
    if sort == "old":
        rows.sort(key=lambda r: r["created_at"])
    elif sort == "name":
        rows.sort(key=lambda r: r["name"].lower())
    else:
        rows.sort(key=lambda r: r["created_at"], reverse=True)
    return total_rows, rows


def panel(title, labels, values, colors=None):
    counts = [0] * len(labels)
    for v in values:
        if v is not None and 0 <= v < len(labels):
            counts[v] += 1
    top = max(counts + [1])
    return {
        "title": title,
        "items": [
            {"label": lab, "n": counts[i], "w": round(counts[i] / top * 100),
             "color": colors[i] if colors else "--brand"}
            for i, lab in enumerate(labels)
        ],
    }


def build_panels(rows):
    doing_labels = [d["en"] for d in DOING] + ["Not given"]
    return [
        panel("Interest", [CL[c]["short"] for c in ORDER], [ORDER.index(r["top"]) for r in rows],
              [CL[c]["color"] for c in ORDER]),
        panel("Learning style", DATA["s_learn"], [r["ans"][6] for r in rows]),
        panel("Study plan", DATA["s_plan"], [r["ans"][9] for r in rows]),
        panel("Picks a course by", DATA["s_factor"], [r["ans"][8] for r in rows]),
        panel("Where they are now", DATA["s_ready"], [r["ans"][0] for r in rows]),
        panel("Doing now", doing_labels,
              [DOING_KEYS.index(r["doing_key"]) if r["doing_key"] in DOING_KEYS else len(DOING_KEYS) for r in rows]),
    ]


@app.get("/admin/login")
def login_page(request: Request):
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/admin/login")
def login(request: Request, username: str = Form(""), password: str = Form("")):
    ip = client_ip(request)
    if login_limiter.blocked(ip):
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Too many wrong attempts. 10 நிமிஷம் கழிச்சு மறுபடி try பண்ணுங்க."},
            status_code=429,
        )
    ok_user = hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
    ok_pass = hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    if ok_user and ok_pass:
        request.session.clear()
        request.session["admin"] = True
        request.session["csrf"] = secrets.token_urlsafe(32)
        return RedirectResponse("/admin", status_code=303)
    login_limiter.add(ip)
    return templates.TemplateResponse(
        request, "login.html", {"error": "Username அல்லது Password தப்பு."}, status_code=401
    )


@app.post("/admin/logout")
def logout(request: Request, csrf: str = Form("")):
    if is_admin(request):
        check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin")
def admin(request: Request, q: str = "", interest: str = "", sort: str = "new", deleted: str = "", error: str = ""):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    all_rows, rows = load_rows(q, interest, sort)
    qs = urlencode({"q": q, "interest": interest, "sort": sort})
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "rows": rows,
            "total": len(all_rows),
            "panels": build_panels(all_rows) if all_rows else [],
            "q": q,
            "interest": interest,
            "sort": sort,
            "qs": qs,
            "csrf": request.session["csrf"],
            "deleted": int(deleted) if deleted.isdigit() else None,
            "error": error,
            "interests": [(c, CL[c]["short"]) for c in ORDER],
        },
    )


@app.get("/admin/export.csv")
def export_csv(request: Request, q: str = "", interest: str = "", sort: str = "new"):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    _, rows = load_rows(q, interest, sort)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        ["Name", "Phone", "Doing now", "Top interest", "Technology %", "Creativity %", "Business %",
         "Science & People %", "Learning style", "Study plan", "Picks course by", "Where they are now",
         "Submitted (IST)"] + [f"Q{i + 1}" for i in range(len(Q))]
    )
    for r in rows:
        w.writerow(
            [csv_safe(r["name"]), r["phone"], r["doing"], r["top_label"],
             r["pct"]["tech"], r["pct"]["creative"], r["pct"]["business"], r["pct"]["people"],
             r["learn"], r["plan"], r["factor"], r["ready"], r["when"]]
            + [LET[a] if a is not None else "" for a in r["ans"]]
        )
    body = "﻿" + out.getvalue()  # BOM so Excel reads Tamil text correctly
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="career-quiz-responses.csv"'},
    )


@app.post("/admin/delete/{rid}")
def delete_response(request: Request, rid: int, csrf: str = Form("")):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    check_csrf(request, csrf)
    with conn() as con:
        n = con.execute("DELETE FROM responses WHERE id = ?", (rid,)).rowcount
    return RedirectResponse(f"/admin?deleted={n}", status_code=303)


@app.post("/admin/delete-many")
def delete_many(request: Request, ids: list[int] = Form([]), csrf: str = Form("")):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    check_csrf(request, csrf)
    ids = list(dict.fromkeys(i for i in ids if i > 0))[:5000]
    if not ids:
        return RedirectResponse("/admin?error=none", status_code=303)
    with conn() as con:
        n = con.execute(
            f"DELETE FROM responses WHERE id IN ({','.join('?' * len(ids))})", ids
        ).rowcount
    return RedirectResponse(f"/admin?deleted={n}", status_code=303)


@app.post("/admin/delete-all")
def delete_all(request: Request, confirm: str = Form(""), csrf: str = Form("")):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    check_csrf(request, csrf)
    if confirm.strip() != "DELETE":
        return RedirectResponse("/admin?error=confirm", status_code=303)
    with conn() as con:
        n = con.execute("DELETE FROM responses").rowcount
    return RedirectResponse(f"/admin?deleted={n}", status_code=303)