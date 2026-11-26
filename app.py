# موقع تصويت لعبة السنة - نسخة Render + Turso (ملف واحد: app.py)
# الملف ده بيتحط على GitHub وRender بيشغّله. قاعدة البيانات على Turso.
# إعدادات Render: Build Command = echo ok  |  Start Command = python app.py
# متغيرات البيئة على Render: TURSO_URL (رابط القاعدة) و TURSO_TOKEN (التوكن)
# من غير المتغيرين دول الموقع بيشتغل على ملف محلي goty.db (للتجربة على جهازك).
import base64, hashlib, hmac, html, json, os, secrets, sqlite3, sys, time, urllib.request, urllib.error
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, quote

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "goty.db")
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")

GAMES = [
    (1, "007 First Light", "IO Interactive"),
    (2, "Control Resonant", "Remedy / Annapurna"),
    (3, "Grand Theft Auto VI", "Rockstar Games"),
    (4, "Phantom Blade Zero", "S-GAME"),
    (5, "Resident Evil Requiem", "Capcom"),
    (6, "The Legend of Zelda: Ocarina of Time", "Nintendo"),
]
GAME_IDS = {g[0] for g in GAMES}


TURSO_URL = os.environ.get("TURSO_URL", "").strip().rstrip("/")
TURSO_URL = TURSO_URL.replace("libsql://", "https://", 1)
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "").strip()


class DBError(Exception):
    pass


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _val(c):
    t = c.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(c["value"])
    if t == "float":
        return float(c["value"])
    if t == "blob":
        return base64.b64decode(c["base64"] + "=" * (-len(c["base64"]) % 4))
    return c["value"]


def run(stmts):
    """stmts: list of (sql, args). Returns list of results; each result is a list of dict rows
    (plus attribute-less). Everything goes to Turso over HTTPS. If TURSO_URL is not set,
    a local file goty.db is used (for testing on your own PC)."""
    if not TURSO_URL:
        c = sqlite3.connect(DB)
        c.row_factory = sqlite3.Row
        out = []
        try:
            for sql, args in stmts:
                try:
                    out.append([dict(r) for r in c.execute(sql, args).fetchall()])
                except sqlite3.IntegrityError as e:
                    raise DBError("UNIQUE " + str(e))
            c.commit()
        finally:
            c.close()
        return out
    reqs = [{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}} for sql, args in stmts]
    reqs.append({"type": "close"})
    req = urllib.request.Request(TURSO_URL + "/v2/pipeline", data=json.dumps({"requests": reqs}).encode(),
                                 headers={"Authorization": "Bearer " + TURSO_TOKEN, "Content-Type": "application/json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            raise DBError("HTTP %s %s" % (e.code, e.read()[:200]))
        except Exception as e:
            last = e
            time.sleep(0.5)
    else:
        raise DBError("network: %s" % last)
    out = []
    for item in data["results"][:-1]:
        if item.get("type") != "ok":
            raise DBError(json.dumps(item.get("error", item)))
        res = item["response"]["result"]
        names = [c["name"] for c in res["cols"]]
        out.append([dict(zip(names, [_val(x) for x in row])) for row in res["rows"]])
    return out


def q(sql, args=()):
    return run([(sql, args)])[0]


SCHEMA = [
    "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, salt BLOB NOT NULL, pw BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL)",
    "CREATE TABLE IF NOT EXISTS votes(user_id INTEGER PRIMARY KEY, game_id INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS reviews(user_id INTEGER NOT NULL, game_id INTEGER NOT NULL, rating INTEGER NOT NULL, text TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(user_id, game_id))",
]


def init():
    run([(x, ()) for x in SCHEMA])


def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)


E = html.escape

CSS = """
body{font-family:Tahoma,Arial,sans-serif;background:#12141c;color:#eee;margin:0}
.w{max-width:760px;margin:0 auto;padding:16px}
h1{color:#ffd24a}a{color:#7cc4ff}
.card{background:#1d2130;border-radius:12px;padding:14px;margin:12px 0}
button{background:#ffd24a;border:0;border-radius:8px;padding:8px 14px;font-weight:bold;cursor:pointer}
input,select,textarea{width:100%;box-sizing:border-box;padding:8px;border-radius:8px;border:1px solid #444;background:#0e1018;color:#eee;margin:4px 0 10px}
.rev{border-top:1px solid #333;padding:8px 0;margin-top:12px}.m{color:#999;font-size:13px}
.err{background:#5a1f1f;padding:8px;border-radius:8px}.ok{background:#1f5a2c;padding:8px;border-radius:8px}
form{margin:10px 0}
nav{display:flex;justify-content:space-between;align-items:center}
"""


def page(body, user=None, msg="", kind="ok"):
    nav = ("<span>أهلاً %s</span><form method=post action=/logout style='margin:0'><button>خروج</button></form>" % E(user["username"])
           if user else "<span><a href=/login>دخول</a> | <a href=/register>حساب جديد</a></span>")
    m = "<div class=%s>%s</div>" % (kind, E(msg)) if msg else ""
    return ("<!doctype html><html lang=ar dir=rtl><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'><title>لعبة السنة</title>"
            "<style>%s</style></head><body><div class=w><nav><h1><a href=/ style='color:#ffd24a;text-decoration:none'>🏆 لعبة السنة</a></h1>%s</nav>%s%s</div></body></html>"
            % (CSS, nav, m, body)).encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def user(self):
        ck = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if "s" not in ck:
            return None
        r = q("SELECT u.id, u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.created>?",
              (ck["s"].value, time.time() - 30 * 86400))
        return r[0] if r else None

    def send(self, body, code=200, headers=()):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, to, headers=()):
        self.send_response(303)
        self.send_header("Location", quote(to, safe="/?=&%"))
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def form(self):
        n = min(int(self.headers.get("Content-Length", 0) or 0), 20000)
        d = parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        return {k: v[0] for k, v in d.items()}

    def same_origin(self):
        o = self.headers.get("Origin")
        return not o or urlparse(o).netloc == self.headers.get("Host")

    def do_GET(self):
        u = self.user()
        p = urlparse(self.path)
        q = parse_qs(p.query)
        msg = q.get("m", [""])[0][:100]
        if p.path == "/healthz":
            return self.send(b"ok")
        if p.path == "/":
            return self.send(self.home(u, msg))
        if p.path == "/login":
            return self.send(page(AUTH % ("دخول", "/login", "دخول"), u, msg, "err"))
        if p.path == "/register":
            return self.send(page(AUTH % ("حساب جديد", "/register", "سجّل"), u, msg, "err"))
        self.send(page("<p>الصفحة مش موجودة</p>", u), 404)

    def home(self, u, msg):
        uid = u["id"] if u else -1
        cnt, avg, mine, revs, myrevs = run([
            ("SELECT game_id, COUNT(*) n FROM votes GROUP BY game_id", ()),
            ("SELECT game_id, AVG(rating) a FROM reviews GROUP BY game_id", ()),
            ("SELECT game_id FROM votes WHERE user_id=?", (uid,)),
            ("SELECT r.game_id, r.rating, r.text, u.username FROM reviews r JOIN users u ON u.id=r.user_id ORDER BY r.created DESC", ()),
            ("SELECT game_id, rating, text FROM reviews WHERE user_id=?", (uid,)),
        ])
        counts = {r["game_id"]: r["n"] for r in cnt}
        avgs = {r["game_id"]: r["a"] for r in avg}
        myvote = mine[0]["game_id"] if mine else None
        myrev_by = {r["game_id"]: r for r in myrevs}
        out = []
        for gid, name, dev in GAMES:
            myrev = myrev_by.get(gid)
            a = avgs.get(gid)
            h = "<div class=card><h2><bdi>%s</bdi></h2><div class=m><bdi>%s</bdi> | أصوات: %d | متوسط التقييم: %s</div>" % (
                E(name), E(dev), counts.get(gid, 0), ("%.1f/5" % a) if a else "لسه مفيش")
            if u:
                h += ("<p>✅ ده صوتك</p>" if myvote == gid else
                      "<form method=post action=/vote><input type=hidden name=game value=%d><button>صوّت للعبة دي</button></form>" % gid)
                h += ("<form method=post action=/review><input type=hidden name=game value=%d>"
                      "<select name=rating>%s</select><textarea name=text rows=3 maxlength=1000 required placeholder='اكتب تقييمك'>%s</textarea>"
                      "<button>%s</button></form>") % (
                    gid, "".join("<option value=%d%s>%d نجوم</option>" % (i, " selected" if myrev and myrev["rating"] == i else "", i) for i in range(5, 0, -1)),
                    E(myrev["text"]) if myrev else "", "عدّل تقييمي" if myrev else "انشر تقييمي")
            for r in [x for x in revs if x["game_id"] == gid][:50]:
                h += "<div class=rev style=color:#ffd24a><b style=color:#eee>%s</b> %s<br><span style=color:#eee>%s</span></div>" % (
                    E(r["username"]), "★" * r["rating"] + "☆" * (5 - r["rating"]), E(r["text"]).replace("\n", "<br>"))
            out.append(h + "</div>")
        intro = "" if u else "<p>سجّل حساب أو ادخل عشان تصوّت وتكتب تقييم.</p>"
        return page(intro + "".join(out), u, msg, "ok")

    def do_POST(self):
        if not self.same_origin():
            return self.send(page("<p>طلب مرفوض</p>"), 403)
        f = self.form()
        u = self.user()
        path = urlparse(self.path).path
        if path == "/register":
            name, pw = f.get("username", "").strip(), f.get("password", "")
            if not (3 <= len(name) <= 20) or not name.replace("_", "").isalnum():
                return self.redirect("/register?m=الاسم 3 لـ 20 حرف أو رقم")
            if len(pw) < 6:
                return self.redirect("/register?m=الباسورد لازم 6 حروف على الأقل")
            salt = secrets.token_bytes(16)
            try:
                q("INSERT INTO users(username,salt,pw) VALUES(?,?,?)", (name, salt, hash_pw(pw, salt)))
            except DBError as e:
                if "UNIQUE" in str(e):
                    return self.redirect("/register?m=الاسم ده واخده حد")
                raise
            return self.login_as(q("SELECT id FROM users WHERE username=?", (name,))[0]["id"])
        if path == "/login":
            r = q("SELECT * FROM users WHERE username=?", (f.get("username", "").strip(),))
            if not r or not hmac.compare_digest(r[0]["pw"], hash_pw(f.get("password", ""), r[0]["salt"])):
                return self.redirect("/login?m=الاسم أو الباسورد غلط")
            return self.login_as(r[0]["id"])
        if path == "/logout":
            ck = cookies.SimpleCookie(self.headers.get("Cookie", ""))
            if "s" in ck:
                q("DELETE FROM sessions WHERE token=?", (ck["s"].value,))
            return self.redirect("/", [("Set-Cookie", "s=; Max-Age=0; Path=/")])
        if not u:
            return self.redirect("/login?m=سجّل دخول الأول")
        try:
            gid = int(f.get("game", 0))
        except ValueError:
            gid = 0
        if gid not in GAME_IDS:
            return self.redirect("/")
        if path == "/vote":
            q("INSERT INTO votes(user_id,game_id) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET game_id=excluded.game_id", (u["id"], gid))
            return self.redirect("/?m=تم تسجيل صوتك")
        if path == "/review":
            text = f.get("text", "").strip()[:1000]
            try:
                rating = max(1, min(5, int(f.get("rating", 5))))
            except ValueError:
                rating = 5
            if not text:
                return self.redirect("/?m=اكتب تقييم الأول")
            q("INSERT INTO reviews(user_id,game_id,rating,text,created) VALUES(?,?,?,?,?) "
              "ON CONFLICT(user_id,game_id) DO UPDATE SET rating=excluded.rating,text=excluded.text,created=excluded.created",
              (u["id"], gid, rating, text, time.time()))
            return self.redirect("/?m=تم نشر تقييمك")
        self.send(page("<p>مش موجود</p>", u), 404)

    def login_as(self, uid):
        tok = secrets.token_urlsafe(32)
        q("INSERT INTO sessions VALUES(?,?,?)", (tok, uid, time.time()))
        sec = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        self.redirect("/", [("Set-Cookie", "s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d%s" % (tok, 30 * 86400, sec))])

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except DBError as e:
            print("DB error:", e, file=sys.stderr)
            try:
                self.send(page("<p>في مشكلة مؤقتة في قاعدة البيانات، جرّب كمان شوية.</p>"), 503)
            except Exception:
                pass


AUTH = ("<div class=card><h2>%s</h2><form method=post action=%s>اسم المستخدم<input name=username required maxlength=20>"
        "الباسورد<input name=password type=password required minlength=6><button>%s</button></form></div>")

if __name__ == "__main__":
    init()
    print("قاعدة البيانات:", "Turso" if TURSO_URL else "ملف محلي goty.db")
    print("الموقع شغال على: http://localhost:%d  (اقفل النافذة دي عشان توقفه)" % PORT)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
