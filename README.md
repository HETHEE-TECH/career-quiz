# Career Path Quiz (FastAPI)

12th முடிஞ்ச students-க்கான 10 கேள்வி Quiz, அதோட Admin பார்க்க username/password login உள்ள page.

- **Students:** `/` திறந்து Quiz எழுதுவாங்க (login வேண்டாம்). பதில்கள் SQLite-ல save ஆகும்.
- **Admin:** `/admin` திறந்து login பண்ணா, எல்லா Responses, summary, search, CSV export, delete எல்லாம் கிடைக்கும்.

## 6 Quiz வகைகள்

Start screen-ல "இப்போ என்ன செய்றீங்க?" Dropdown-ல தேர்ந்தெடுக்கறதை வச்சு, அதுக்குரிய Quiz மட்டும் வரும் (`set_of` in `static/quiz-data.json`).
ஒரு Option = ஒரு Quiz. Server-ம் அதே Quiz-ஓட Answers-ஐ Check பண்றதால Questions கலக்காது.

| Dropdown | Quiz |
|---|---|
| 12-ஆம் வகுப்பு முடித்து படிப்பு / கல்லூரி தேடுகிறேன் | After 12th (interest result + TATTI courses) |
| கல்லூரியில் படிக்கிறேன் | College student |
| சான்றிதழ் படிப்பு / பயிற்சி | Certificate course |
| வேலை தேடுகிறேன் | Job seeker |
| வேலை செய்கிறேன் | Working professional |
| போட்டித் தேர்வுக்குத் தயாராகிறேன் | Exam preparation |

Questions மாத்தினா பழைய Responses-ஐ Admin-ல "Delete all" பண்ணுங்க (Export CSV எடுத்த பிறகு). இல்லன்னா பழைய Answers புது Questions-ஓட தப்பாப் பொருந்தும்.

## Local-ல ஓட்டறது

Python 3.10 அல்லது அதுக்கு மேல வேணும்.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# .env-ஐ திறந்து ADMIN_PASSWORD, SECRET_KEY நிரப்புங்க
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY-க்கு இதை paste பண்ணுங்க

uvicorn app:app --reload --port 8000
```

Browser-ல `http://localhost:8000` (Quiz), `http://localhost:8000/admin` (Admin).
`ADMIN_PASSWORD` அல்லது `SECRET_KEY` இல்லன்னா app Start ஆகாது. இது வேணும்னே வச்சது.

## Security-ல என்ன இருக்கு

- Admin pages எல்லாத்துக்கும் server-ல login check. Login இல்லாம `/admin`, CSV, Delete எதுவும் வேலை செய்யாது.
- Wrong password 5 தடவை போனா, அந்த IP-க்கு 10 நிமிஷம் Lock.
- Login cookie signed, 8 மணி நேரத்துல Expire. Delete / Logout-க்கு CSRF token.
- Students அனுப்பற data-ஐ server-ல Validate பண்றோம் (பெயர் நீளம், Phone format, பதில் எண்கள்). Interest Result-ஐயும் server-ஏ கணக்கிடுது, browser சொல்றதை நம்பாது.
- Admin page-ல எல்லா Text-ம் auto-escape ஆகுது. CSV-ல `=`, `+`, `@` -ல ஆரம்பிக்கற Text-க்கு முன்னாடி `'` சேர்ந்துடும் (Excel formula Injection-ஐத் தடுக்க).
- Students-ஓட Phone Number இருக்கறதால, Website-ஐ https-ல மட்டும் போடுங்க, அப்போ `.env`-ல `SESSION_HTTPS_ONLY=1`.

## Deploy பண்றது

Python ஓடற எந்த இடமும் ஓகே (Render, Railway, ஒரு VPS...). Start command:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

- Platform-ல `.env` values-ஐ Environment Variables-ஆ போடுங்க (`ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SESSION_HTTPS_ONLY=1`, Proxy பின்னாடி இருந்தா `TRUST_PROXY=1`).
- **Database file:** SQLite file `data/responses.db`. சில Free hosting-ல Restart ஆனா Files அழிஞ்சிடும். அங்க Persistent Disk சேர்த்து `DB_PATH` அந்த Disk-ஐ காட்டணும். வாராவாரம் `/admin`-ல இருந்து CSV Export பண்ணி Backup எடுத்துக்கோங்க.
- Rate limit (Students Submit, Login Attempts) Memory-ல இருக்கு. App Restart ஆனா Reset ஆகும். ஒரே ஒரு Server Process-க்கு இது போதும். `--workers 1` வச்சுக்கோங்க.
- ஒரு Computer Lab-ல எல்லாரும் ஒரே IP-ல வருவாங்க. அதுக்காக Submit limit மணிக்கு 200. தேவைன்னா `SUBMIT_LIMIT_PER_HOUR` மாத்துங்க.

## Files

```
app.py                  Routes, scoring, SQLite, login, CSV
templates/              base, quiz, login, admin (Jinja2)
static/quiz-data.json   கேள்விகள், Labels, Courses (Browser, Server ரெண்டுக்கும் ஒரே Source)
static/quiz.js          Student Quiz
static/style.css        Styles
```

கேள்விகளையோ Course list-ஐயோ மாத்தணும்னா `static/quiz-data.json`-ஐ மட்டும் Edit பண்ணுங்க.
ஒரு Question-ஐ Add / Remove பண்ணா `"m"` (Interest mapping) மற்றும் `"w"` (Weight) சரியா இருக்கான்னு பாருங்க,
`app.py`-ல Q2, Q3 (Index 1, 2) Tie-break-க்கு பயன்படுது.
