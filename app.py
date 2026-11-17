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
from pydantic import BaseModel, Field, field_validator, model_validator
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
LET = "ABCDEFG"  # the longest question has 7 options
# Six quizzes, one per "doing now" choice (DATA["set_of"]): school (after 12th), college, course,
# jobseeker, working, exam. A student only ever gets the quiz that matches the choice they made;
# the server checks the answers against that same quiz, so questions can never be mixed up.
SETS = {"school": Q, **{k: v["q"] for k, v in DATA["sets"].items()}}
SET_NAMES = {"school": DATA["school_name"], **{k: v["name"] for k, v in DATA["sets"].items()}}


def set_for(doing: str) -> str:
    return DATA["set_of"][doing]


def compute(ans):
    """Same scoring as the browser (only the after-12th quiz has interest scoring).
    Questions whose option has no interest (m is None) add nothing."""
    score = {c: 0 for c in ORDER}
    max_score = 0
    for i, q in enumerate(Q):
        if "m" not in q:
            continue
        max_score += q["w"]
        a = ans[i] if i < len(ans) else None
        if a is None or not 0 <= a < len(q["m"]):
            continue
        if q["m"][a]:
            score[q["m"][a]] += q["w"]
    ranked = sorted(ORDER, key=lambda c: score[c], reverse=True)
    return {"score": score, "max": max_score, "ranked": ranked}


# ---------------------------------------------------------------- database
# SQLite file by default (local use). If DATABASE_URL is set to a Postgres address
# (Neon, Supabase, Render Postgres...) the same code stores the data there instead,
# which survives Render restarts and re-deploys.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

STATUSES = [("new", "New"), ("called", "Called"), ("followup", "Follow-up needed"), ("done", "Done")]
STATUS_KEYS = [k for k, _ in STATUSES]


class _PG:
    """Lets the SQLite-style '?' queries below run unchanged on Postgres."""

    def __init__(self, con):
        self.con = con

    def execute(self, sql, params=()):
        return self.con.execute(sql.replace("?", "%s"), params)


@contextmanager
def conn():
    if USE_PG:
        import psycopg
        from psycopg.rows import dict_row

        con = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
        try:
            yield _PG(con)
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
    else:
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()


def init_db():
    if USE_PG:
        with conn() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS responses (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    grp TEXT NOT NULL DEFAULT '',
                    doing TEXT NOT NULL DEFAULT '',
                    qset TEXT NOT NULL DEFAULT 'school',
                    status TEXT NOT NULL DEFAULT 'new',
                    note TEXT NOT NULL DEFAULT '',
                    answers TEXT NOT NULL,
                    top TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
        return
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
                qset TEXT NOT NULL DEFAULT 'school',
                status TEXT NOT NULL DEFAULT 'new',
                note TEXT NOT NULL DEFAULT '',
                answers TEXT NOT NULL,
                top TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )


NEW_COLUMNS = [
    ("doing", "TEXT NOT NULL DEFAULT ''"),
    ("qset", "TEXT NOT NULL DEFAULT 'school'"),
    ("status", "TEXT NOT NULL DEFAULT 'new'"),
    ("note", "TEXT NOT NULL DEFAULT ''"),
]


def migrate_db():
    """Databases made by an older version get the columns added since."""
    with conn() as con:
        if USE_PG:
            for name, ddl in NEW_COLUMNS:
                con.execute(f"ALTER TABLE responses ADD COLUMN IF NOT EXISTS {name} {ddl}")
            return
        cols = {r["name"] for r in con.execute("PRAGMA table_info(responses)")}
        for name, ddl in NEW_COLUMNS:
            if name not in cols:
                con.execute(f"ALTER TABLE responses ADD COLUMN {name} {ddl}")


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
        if v not in DOING_KEYS:
            raise ValueError("unknown option")
        return v

    @field_validator("answers")
    @classmethod
    def clean_answers(cls, v):
        if len(v) != 10 or any(a is None for a in v):
            raise ValueError("wrong number of answers")
        return v

    @model_validator(mode="after")
    def check_against_set(self):
        qs = SETS[set_for(self.doing)]
        if len(self.answers) != len(qs):
            raise ValueError("wrong number of answers")
        for i, a in enumerate(self.answers):
            if not 0 <= a < len(qs[i]["o"]):
                raise ValueError("answer out of range")
        return self


@app.post("/api/submit")
def submit(request: Request, body: Submission):
    ip = client_ip(request)
    if submit_limiter.blocked(ip):
        return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
    submit_limiter.add(ip)
    qset = set_for(body.doing)
    # only the 12th quiz has interest scoring; computed here, never trusted from the browser
    top = compute(body.answers)["ranked"][0] if qset == "school" else "-"
    with conn() as con:
        con.execute(
            "INSERT INTO responses (name, phone, grp, doing, qset, answers, top, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (body.name, body.phone, body.group, body.doing, qset, json.dumps(body.answers), top,
             datetime.now(timezone.utc).isoformat()),
        )
    return {"ok": True}


# ---------------------------------------------------------------- admin
def prepare(row) -> dict:
    ans = json.loads(row["answers"])
    qset = row["qset"] if row["qset"] in SETS else "school"
    school = qset == "school"
    res = compute(ans) if school else {"score": {}, "max": 0, "ranked": [None]}
    top = res["ranked"][0]

    def key_answer(pos):
        """The answer to the pos-th highlighted question of this quiz (see quiz-data.json "highlights")."""
        hl = DATA["highlights"].get(qset, [])
        if not hl:
            return "—"
        qi = hl[pos][0] if pos >= 0 else hl[-1][0]
        a = ans[qi] if qi < len(ans) else None
        opts = SETS[qset][qi]["o"]
        return opts[a] if a is not None and 0 <= a < len(opts) else "—"

    qa = []
    for i, q in enumerate(SETS[qset]):
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
        "qset": qset,
        "qset_name": SET_NAMES[qset],
        "status": row["status"] if row["status"] in STATUS_KEYS else "new",
        "status_label": dict(STATUSES).get(row["status"], "New"),
        "note": row["note"] or "",
        "top": top,
        "top_label": CL[top]["short"] if school else "—",
        "top_color": CL[top]["color"] if school else "--muted",
        "pct": {c: round(res["score"][c] / res["max"] * 100) if res["max"] else 0 for c in ORDER} if school else {},
        "main": key_answer(0),
        "help": key_answer(-1),
        "qa": qa,
    }


def local_date(iso: str):
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).date()
    except ValueError:
        return None


def parse_day(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_rows(q: str, interest: str, sort: str, quiz: str = "", frm: str = "", to: str = "", status: str = ""):
    with conn() as con:
        raw = con.execute("SELECT * FROM responses ORDER BY id DESC LIMIT ?", (MAX_ROWS,)).fetchall()
    rows = [prepare(r) for r in raw]
    total_rows = list(rows)
    needle = q.strip().lower()
    if quiz in SETS:
        rows = [r for r in rows if r["qset"] == quiz]
    if status in STATUS_KEYS:
        rows = [r for r in rows if r["status"] == status]
    d1, d2 = parse_day(frm), parse_day(to)
    if d1:
        rows = [r for r in rows if (d := local_date(r["created_at"])) and d >= d1]
    if d2:
        rows = [r for r in rows if (d := local_date(r["created_at"])) and d <= d2]
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


def dashboard(rows):
    today = datetime.now(TZ).date()
    days = [local_date(r["created_at"]) for r in rows]
    return {
        "total": len(rows),
        "today": sum(1 for d in days if d == today),
        "week": sum(1 for d in days if d and d >= today - timedelta(days=6)),
        "by_quiz": [(k, SET_NAMES[k], sum(1 for r in rows if r["qset"] == k)) for k in SETS],
        "by_status": [(k, lab, sum(1 for r in rows if r["status"] == k)) for k, lab in STATUSES],
        "today_str": today.isoformat(),
        "week_str": (today - timedelta(days=6)).isoformat(),
    }


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
    out = []
    school = [r for r in rows if r["qset"] == "school"]
    if school:
        out.append(panel("Interest (After 12th quiz)", [CL[c]["short"] for c in ORDER],
                         [ORDER.index(r["top"]) for r in school], [CL[c]["color"] for c in ORDER]))
    for key in SETS:  # every quiz: first and last question
        sub = [r for r in rows if r["qset"] == key]
        if not sub:
            continue
        for qi in (0, 9):
            labels = [o[:38] + ("…" if len(o) > 38 else "") for o in SETS[key][qi]["o"]]
            out.append(panel(f"{SET_NAMES[key]}: Q{qi + 1}", labels, [r["ans"][qi] for r in sub]))
    out.append(panel("Doing now", doing_labels,
                     [DOING_KEYS.index(r["doing_key"]) if r["doing_key"] in DOING_KEYS else len(DOING_KEYS) for r in rows]))
    out.append(panel("Quiz taken", list(SET_NAMES.values()), [list(SET_NAMES).index(r["qset"]) for r in rows]))
    return out


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
def admin(request: Request, q: str = "", interest: str = "", sort: str = "new", deleted: str = "", error: str = "",
          quiz: str = "", frm: str = "", to: str = "", status: str = "", saved: str = ""):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    all_rows, rows = load_rows(q, interest, sort, quiz, frm, to, status)
    qs = urlencode({"q": q, "interest": interest, "sort": sort, "quiz": quiz, "frm": frm, "to": to, "status": status})
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "rows": rows,
            "total": len(all_rows),
            "panels": build_panels(all_rows) if all_rows else [],
            "q": q,
            "quiz": quiz,
            "frm": frm,
            "to": to,
            "status": status,
            "saved": saved == "1",
            "stats": dashboard(all_rows),
            "quizzes": [(k, SET_NAMES[k]) for k in SETS],
            "statuses": STATUSES,
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
def export_csv(request: Request, q: str = "", interest: str = "", sort: str = "new",
               quiz: str = "", frm: str = "", to: str = "", status: str = ""):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    _, rows = load_rows(q, interest, sort, quiz, frm, to, status)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        ["Name", "Phone", "Doing now", "Quiz", "Top interest", "Technology %", "Creativity %", "Business %",
         "Science & People %", "Main answer", "Help needed first",
         "Submitted (IST)", "Status", "Note"] + [f"Q{i + 1}" for i in range(10)]
    )
    for r in rows:
        w.writerow(
            [csv_safe(r["name"]), r["phone"], r["doing"], r["qset_name"], r["top_label"],
             r["pct"].get("tech", ""), r["pct"].get("creative", ""), r["pct"].get("business", ""), r["pct"].get("people", ""),
             csv_safe(r["main"]), csv_safe(r["help"]), r["when"], dict(STATUSES)[r["status"]], csv_safe(r["note"])]
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


@app.post("/admin/note/{rid}")
def save_note(request: Request, rid: int, status: str = Form("new"), note: str = Form(""),
              back: str = Form(""), csrf: str = Form("")):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    check_csrf(request, csrf)
    if status not in STATUS_KEYS:
        status = "new"
    note = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", note).strip()[:500]
    with conn() as con:
        con.execute("UPDATE responses SET status = ?, note = ? WHERE id = ?", (status, note, rid))
    back = back if re.fullmatch(r"[A-Za-z0-9_=&%.+\-]{0,300}", back) else ""
    return RedirectResponse("/admin?" + (back + "&" if back else "") + "saved=1", status_code=303)


@app.get("/admin/print/{rid}")
def print_one(request: Request, rid: int):
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    with conn() as con:
        row = con.execute("SELECT * FROM responses WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    r = prepare(row)
    bars = [(CL[c]["short"], CL[c]["color"], r["pct"][c]) for c in ORDER] if r["qset"] == "school" else []
    return templates.TemplateResponse(request, "print.html", {"r": r, "bars": bars})