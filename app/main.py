from __future__ import annotations

import hashlib
import html
import secrets
import sqlite3
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "trainme.db"
STATIC_DIR = BASE_DIR / "app" / "static"


TRACKS: dict[str, dict[str, Any]] = {
    "atlet": {
        "name": "Atlet",
        "tagline": "For dig som vill hoja prestationen och fatta smartare beslut fran din traningsdata.",
        "focus": [
            "Prestationsanalys med Strava som underlag",
            "AI-tips for belastning, aterhamtning och progression",
            "Forslag pa traningsformer som bygger kapacitet",
        ],
        "accent": "performance",
        "subcategories": {
            "styrka": "Explosivitet, maxstyrka och kompletterande pass som stottar idrottsprestation.",
            "blandat": "Periodiserade veckor med teknik, rorlighet, aterhamtning och kvalitetspass.",
            "kondition": "Intervaller, distans, zoner och Strava-baserad uppfoljning av form.",
        },
    },
    "aktiv": {
        "name": "Aktiv",
        "tagline": "For dig som tranar regelbundet och vill halla kroppen frisk, stark och pigg.",
        "focus": [
            "Allmanna traningstips for en hallbar vardag",
            "Kostrad for energi, ork och aterhamtning",
            "Balans mellan styrka, kondition och vila",
        ],
        "accent": "active",
        "subcategories": {
            "styrka": "Trygga basovningar, smart progression och rutiner som gar att halla over tid.",
            "blandat": "Veckoupplagg med styrka, rorlighet, promenader, cykel eller grupptraning.",
            "kondition": "Konditionspass for hjarta, energi och battre aterhamtning i vardagen.",
        },
    },
    "komma-igang": {
        "name": "Komma igang",
        "tagline": "For dig som vill borja lugnt, skapa vanor och fa extra stod kring kost.",
        "focus": [
            "Allman motion som kanns mojlig att starta med",
            "Mycket fokus pa enkla kostvanor",
            "Sma steg som bygger sjalvfortroende",
        ],
        "accent": "start",
        "subcategories": {
            "styrka": "Kroppsvikt, enkla hemmapass och skonsam styrka for att komma igang.",
            "blandat": "Promenader, rorlighet och korta pass som passar en ny rutin.",
            "kondition": "Lugna konditionspass med tydlig startniva och fokus pa kontinuitet.",
        },
    },
}


SUBCATEGORY_NAMES = {
    "styrka": "Styrka",
    "blandat": "Blandat",
    "kondition": "Kondition",
}


def ensure_db() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username VARCHAR UNIQUE,
                email VARCHAR UNIQUE,
                password VARCHAR,
                category VARCHAR,
                height FLOAT,
                weight FLOAT,
                goal VARCHAR
            )
            """
        )


def query_one(sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        return db.execute(sql, params).fetchone()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_password: str | None) -> bool:
    if not stored_password:
        return False
    if "$" not in stored_password:
        return secrets.compare_digest(password, stored_password)
    salt, digest = stored_password.split("$", 1)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return secrets.compare_digest(candidate.hex(), digest)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def check_items(items: list[str]) -> str:
    return "".join(f"<li>{esc(item)}</li>" for item in items)


def header(user: sqlite3.Row | None) -> str:
    auth = (
        """
        <a class="ghost-button" href="/ai-coach">AI coach</a>
        <form method="post" action="/logga-ut"><button class="icon-button" type="submit" aria-label="Logga ut" title="Logga ut">↗</button></form>
        """
        if user
        else """
        <a class="ghost-button" href="/logga-in">Logga in</a>
        <a class="primary-button compact" href="/registrera">Skapa konto</a>
        """
    )
    return f"""
    <header class="site-header">
        <a class="brand" href="/"><span class="brand-mark">T</span><span>TrainMe</span></a>
        <nav class="nav-links" aria-label="Huvudmeny">
            <a href="/spar/atlet">Atlet</a>
            <a href="/spar/aktiv">Aktiv</a>
            <a href="/spar/komma-igang">Komma igang</a>
        </nav>
        <div class="account-actions">{auth}</div>
    </header>
    """


def page(title: str, body: str, user: sqlite3.Row | None = None) -> bytes:
    document = f"""
    <!DOCTYPE html>
    <html lang="sv">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{esc(title)}</title>
        <link rel="stylesheet" href="/static/css/style.css">
    </head>
    <body>
        {header(user)}
        <main>{body}</main>
    </body>
    </html>
    """
    return document.encode("utf-8")


def track_cards() -> str:
    cards = []
    for track_id, track in TRACKS.items():
        chips = "".join(f"<span>{esc(SUBCATEGORY_NAMES[sub_id])}</span>" for sub_id in track["subcategories"])
        cards.append(
            f"""
            <article class="track-card {track["accent"]}">
                <div class="track-card-header">
                    <p class="eyebrow">{esc(track["name"])}</p>
                    <h2>{esc(track["name"])}</h2>
                </div>
                <p>{esc(track["tagline"])}</p>
                <ul class="check-list">{check_items(track["focus"])}</ul>
                <div class="chip-row">{chips}</div>
                <a class="text-link" href="/spar/{track_id}">Oppna {esc(track["name"])}</a>
            </article>
            """
        )
    return "".join(cards)


def home_page(user: sqlite3.Row | None) -> bytes:
    body = f"""
    <section class="hero">
        <div class="hero-copy">
            <p class="eyebrow">Traningshjalp for olika nivaer</p>
            <h1>TrainMe</h1>
            <p class="lead">Valj om du ar Atlet, Aktiv eller vill Komma igang. Du kan utforska gratis,
            och med konto far du AI-hjalp och Strava-baserade insikter.</p>
            <div class="hero-actions">
                <a class="primary-button" href="/registrera">Skapa konto</a>
                <a class="ghost-button" href="#spar">Utforska utan konto</a>
            </div>
        </div>
        <div class="hero-panel" aria-label="TrainMe sammanfattning">
            <div><span class="metric">3</span><span class="metric-label">traningsspar</span></div>
            <div><span class="metric">9</span><span class="metric-label">subkategorier</span></div>
            <div><span class="metric">AI</span><span class="metric-label">med konto</span></div>
        </div>
    </section>
    <section class="track-grid" id="spar" aria-label="TrainMe spar">{track_cards()}</section>
    <section class="access-band">
        <div><p class="eyebrow">Gratis eller konto</p><h2>Borja direkt. Skapa konto nar du vill ha mer hjalp.</h2></div>
        <div class="access-grid">
            <div><h3>Utan konto</h3><p>Las om spar, subkategorier, traningsformer och grundtips.</p></div>
            <div><h3>Med konto</h3><p>Fa AI-coachning, spara mal och koppla Strava for battre rekommendationer.</p></div>
        </div>
    </section>
    """
    return page("TrainMe", body, user)


def track_page(track_id: str, user: sqlite3.Row | None) -> bytes:
    track = TRACKS[track_id]
    account_actions = (
        '<a class="primary-button" href="/ai-coach">Oppna AI coach</a><a class="ghost-button" href="/strava">Koppla Strava</a>'
        if user
        else '<a class="primary-button" href="/registrera">Skapa konto for AI</a><a class="ghost-button" href="#subkategorier">Fortsatt gratis</a>'
    )
    subcards = []
    for sub_id, copy in track["subcategories"].items():
        subcards.append(
            f"""
            <article class="subcategory-card">
                <span class="sub-icon">{len(subcards) + 1}</span>
                <h2>{esc(SUBCATEGORY_NAMES[sub_id])}</h2>
                <p>{esc(copy)}</p>
                <a class="text-link" href="/spar/{track_id}/{sub_id}">Se upplagg</a>
            </article>
            """
        )
    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">TrainMe spar</p>
        <h1>{esc(track["name"])}</h1>
        <p class="lead">{esc(track["tagline"])}</p>
        <div class="hero-actions">{account_actions}</div>
    </section>
    <section class="content-grid">
        <div class="focus-panel"><h2>Fokus</h2><ul class="check-list">{check_items(track["focus"])}</ul></div>
        <div class="locked-panel"><h2>AI + Strava</h2><p>{'Din AI-coach kan anvanda ditt valda spar, mal och framtida Strava-data for mer personliga tips.' if user else 'Skapa konto for att lata TrainMe spara profil, mal och Strava-underlag till AI-hjalpen.'}</p></div>
    </section>
    <section class="subcategory-grid" id="subkategorier">{"".join(subcards)}</section>
    """
    return page(f"{track['name']} | TrainMe", body, user)


def subcategory_page(track_id: str, sub_id: str, user: sqlite3.Row | None) -> bytes:
    track = TRACKS[track_id]
    personal = (
        '<p>Du ar inloggad. AI-coachen kan anvanda ditt spar och dina mal for att ge mer relevanta forslag.</p><a class="primary-button compact" href="/ai-coach">Oppna AI coach</a>'
        if user
        else '<p>Det har fungerar utan konto. Skapa konto for AI-hjalp, sparade mal och Strava-koppling.</p><a class="primary-button compact" href="/registrera">Skapa konto</a>'
    )
    third_step = {
        "komma-igang": "Bygg kosten runt enkla rutiner: protein, gronsaker och regelbundna maltider.",
        "aktiv": "Justera kost och vila sa kroppen haller sig frisk over tid.",
    }.get(track_id, "Anvand data fran pass for att styra belastning och kvalitet.")
    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">{esc(track["name"])}</p>
        <h1>{esc(SUBCATEGORY_NAMES[sub_id])}</h1>
        <p class="lead">{esc(track["subcategories"][sub_id])}</p>
    </section>
    <section class="program-layout">
        <div>
            <h2>Startforslag</h2>
            <div class="step-list">
                <div><span>01</span><p>Valj 2-4 pass per vecka utifran din nuvarande niva.</p></div>
                <div><span>02</span><p>Folj upp energi, aterhamtning och progression efter varje vecka.</p></div>
                <div><span>03</span><p>{esc(third_step)}</p></div>
            </div>
        </div>
        <aside class="locked-panel"><h2>Personlig hjalp</h2>{personal}</aside>
    </section>
    """
    return page(f"{SUBCATEGORY_NAMES[sub_id]} | TrainMe", body, user)


def register_page(user: sqlite3.Row | None, error: bool = False) -> bytes:
    options = "".join(f'<option value="{track_id}">{esc(track["name"])}</option>' for track_id, track in TRACKS.items())
    message = '<p class="form-error">E-post eller anvandarnamn finns redan.</p>' if error else ""
    body = f"""
    <section class="form-shell">
        <div><p class="eyebrow">TrainMe konto</p><h1>Skapa konto</h1><p class="lead">Kontot laser upp AI-hjalp, sparade mal och mojlighet att koppla Strava.</p></div>
        <form class="form-card" method="post" action="/registrera">
            {message}
            <label>Anvandarnamn<input name="username" type="text" autocomplete="username" required></label>
            <label>E-post<input name="email" type="email" autocomplete="email" required></label>
            <label>Losenord<input name="password" type="password" autocomplete="new-password" minlength="6" required></label>
            <label>Spar<select name="category" required>{options}</select></label>
            <div class="two-fields">
                <label>Langd cm<input name="height" type="number" min="80" max="240" step="0.5"></label>
                <label>Vikt kg<input name="weight" type="number" min="20" max="300" step="0.1"></label>
            </div>
            <label>Mal<textarea name="goal" rows="4" placeholder="Exempel: springa 10 km, bli starkare, fa battre kostvanor"></textarea></label>
            <button class="primary-button" type="submit">Skapa konto</button>
            <a class="text-link" href="/logga-in">Jag har redan konto</a>
        </form>
    </section>
    """
    return page("Skapa konto | TrainMe", body, user)


def login_page(user: sqlite3.Row | None, error: bool = False) -> bytes:
    message = '<p class="form-error">Fel e-post eller losenord.</p>' if error else ""
    body = f"""
    <section class="form-shell narrow">
        <div><p class="eyebrow">Valkommen tillbaka</p><h1>Logga in</h1><p class="lead">Fortsatt med AI-coachning och Strava-underlag.</p></div>
        <form class="form-card" method="post" action="/logga-in">
            {message}
            <label>E-post<input name="email" type="email" autocomplete="email" required></label>
            <label>Losenord<input name="password" type="password" autocomplete="current-password" required></label>
            <button class="primary-button" type="submit">Logga in</button>
            <a class="text-link" href="/registrera">Skapa konto</a>
        </form>
    </section>
    """
    return page("Logga in | TrainMe", body, user)


def ai_page(user: sqlite3.Row) -> bytes:
    track_id = user["category"] or "aktiv"
    track = TRACKS.get(track_id, TRACKS["aktiv"])
    body = f"""
    <section class="page-hero {track["accent"]}">
        <p class="eyebrow">Endast med konto</p>
        <h1>AI coach for {esc(track["name"])}</h1>
        <p class="lead">Har samlas personliga traningstips baserat pa ditt spar, dina mal och framtida Strava-data.</p>
    </section>
    <section class="coach-grid">
        <article class="coach-panel"><h2>Dagens riktning</h2><p>AI-funktionen ar redo som yta. Nasta steg ar att koppla in en riktig AI-modell och skicka med profil, mal och Strava-sammanfattning.</p></article>
        <article class="coach-panel"><h2>Datakallor</h2><p>Profil: {esc(user["username"])}. Spar: {esc(track["name"])}. Strava: vantar pa koppling.</p><a class="text-link" href="/strava">Koppla Strava</a></article>
    </section>
    """
    return page("AI coach | TrainMe", body, user)


def strava_page(user: sqlite3.Row) -> bytes:
    body = """
    <section class="page-hero performance">
        <p class="eyebrow">Strava</p>
        <h1>Koppla Strava</h1>
        <p class="lead">Alla tre spar kan anvanda Strava for att ge AI-coachen battre information om din traning.</p>
    </section>
    <section class="content-grid">
        <div class="focus-panel"><h2>Vad TrainMe kan anvanda</h2><ul class="check-list"><li>Passhistorik och frekvens</li><li>Distans, tid, intensitet och utveckling</li><li>Underlag for smartare tips om belastning och aterhamtning</li></ul></div>
        <div class="locked-panel"><h2>Integration</h2><p>Strava-knappen ar forberedd. For riktig koppling behovs Strava API-nycklar och OAuth-flode.</p><button class="primary-button" type="button" disabled>Koppla Strava snart</button></div>
    </section>
    """
    return page("Strava | TrainMe", body, user)


class TrainMeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        ensure_db()
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        query = parse_qs(parsed.query)
        user = self.current_user()

        if path.startswith("/static/"):
            self.serve_static(path)
        elif path == "/":
            self.send_html(home_page(user))
        elif path == "/registrera":
            self.send_html(register_page(user, error="fel" in query))
        elif path == "/logga-in":
            self.send_html(login_page(user, error="fel" in query))
        elif path == "/ai-coach":
            self.redirect("/registrera") if not user else self.send_html(ai_page(user))
        elif path == "/strava":
            self.redirect("/registrera") if not user else self.send_html(strava_page(user))
        elif path.startswith("/spar/"):
            parts = path.strip("/").split("/")
            self.handle_track(parts, user)
        else:
            self.redirect("/")

    def do_POST(self) -> None:
        ensure_db()
        parsed = urlparse(self.path)
        if parsed.path == "/registrera":
            self.register()
        elif parsed.path == "/logga-in":
            self.login()
        elif parsed.path == "/logga-ut":
            self.redirect("/", clear_cookie=True)
        else:
            self.redirect("/")

    def handle_track(self, parts: list[str], user: sqlite3.Row | None) -> None:
        if len(parts) < 2 or parts[1] not in TRACKS:
            self.redirect("/")
            return
        track_id = parts[1]
        if len(parts) == 2:
            self.send_html(track_page(track_id, user))
            return
        sub_id = parts[2]
        if sub_id not in TRACKS[track_id]["subcategories"]:
            self.redirect(f"/spar/{track_id}")
            return
        self.send_html(subcategory_page(track_id, sub_id, user))

    def register(self) -> None:
        form = self.form_data()
        category = form.get("category", "aktiv")
        if category not in TRACKS:
            category = "aktiv"

        try:
            height = float(form["height"]) if form.get("height") else None
            weight = float(form["weight"]) if form.get("weight") else None
            with sqlite3.connect(DB_PATH) as db:
                cursor = db.execute(
                    """
                    INSERT INTO users (username, email, password, category, height, weight, goal)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        form.get("username", "").strip(),
                        form.get("email", "").strip().lower(),
                        hash_password(form.get("password", "")),
                        category,
                        height,
                        weight,
                        form.get("goal", "").strip(),
                    ),
                )
                user_id = cursor.lastrowid
        except (sqlite3.IntegrityError, ValueError):
            self.redirect("/registrera?fel=finns")
            return

        self.redirect(f"/spar/{category}", user_id=user_id)

    def login(self) -> None:
        form = self.form_data()
        user = query_one("SELECT * FROM users WHERE email = ?", (form.get("email", "").strip().lower(),))
        if not user or not verify_password(form.get("password", ""), user["password"]):
            self.redirect("/logga-in?fel=1")
            return
        self.redirect(f"/spar/{user['category'] or 'aktiv'}", user_id=user["id"])

    def current_user(self) -> sqlite3.Row | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        jar = cookies.SimpleCookie(raw_cookie)
        morsel = jar.get("trainme_user")
        if not morsel:
            return None
        return query_one("SELECT * FROM users WHERE id = ?", (morsel.value,))

    def form_data(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return {key: values[0] for key, values in parse_qs(body).items()}

    def serve_static(self, path: str) -> None:
        requested = (STATIC_DIR / path.removeprefix("/static/")).resolve()
        if STATIC_DIR.resolve() not in requested.parents or not requested.exists():
            self.send_error(404)
            return
        content_type = "text/css; charset=utf-8" if requested.suffix == ".css" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(requested.read_bytes())

    def send_html(self, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, location: str, user_id: int | None = None, clear_cookie: bool = False) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if user_id is not None:
            self.send_header("Set-Cookie", f"trainme_user={user_id}; HttpOnly; SameSite=Lax; Path=/")
        if clear_cookie:
            self.send_header("Set-Cookie", "trainme_user=; Max-Age=0; Path=/")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return


def run() -> None:
    ensure_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), TrainMeHandler)
    print("TrainMe running on http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    run()
