"""Dashboard und Fernbedienung für den News-Bot – läuft kostenlos auf Render.

Der Server speichert nichts dauerhaft. Die Daten liegen beim Bot auf deinem PC;
der Bot meldet sich alle paar Sekunden hier (/bot/sync), schickt neue Artikel,
Fehler und seinen Status und holt sich dabei offene Befehle ab.
Startet Render den Server neu, ist der Speicher leer – der Server sagt das dem
Bot, und der schickt beim nächsten Sync automatisch seinen kompletten Verlauf.

Umgebungsvariablen (bei Render unter "Environment"):
    BOT_TOKEN           geheimer Schlüssel, den auch der Bot kennt (min. 32 Zeichen)
    DASHBOARD_PASSWORT  dein Login-Passwort für die Seite (min. 10 Zeichen)

Lokal starten:
    BOT_TOKEN=... DASHBOARD_PASSWORT=... uvicorn server:app --reload
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
import re
import time
import uuid
from collections import OrderedDict, deque
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PASSWORT = os.environ.get("DASHBOARD_PASSWORT", "")
if len(BOT_TOKEN) < 32 or len(PASSWORT) < 10:
    raise SystemExit("BOT_TOKEN (mind. 32 Zeichen) und DASHBOARD_PASSWORT (mind. 10 Zeichen) müssen gesetzt sein.")

SCHLUESSEL = hashlib.sha256(f"sitzung|{BOT_TOKEN}|{PASSWORT}".encode()).digest()
COOKIE = "newsbot_sitzung"
SITZUNG_SEKUNDEN = 14 * 24 * 3600
ONLINE_PUFFER_SEKUNDEN = 15  # online = letzter Kontakt vor höchstens 2 Sync-Takten + Puffer
STATIC = Path(__file__).resolve().parent / "static"
SERVER_START = time.time()
# Nur echte Push-Dienste der Browser (gleiche Liste prüft auch der Bot)
ERLAUBTE_PUSH_HOSTS = (".googleapis.com", ".mozilla.com", ".mozaws.net", ".push.apple.com", ".notify.windows.com")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# --------------------------------------------------------------------------- Prüfregeln für Quellen und Tags
# Dieselben Regeln wie in bot/listen.py. Der Bot prüft alles noch einmal selbst –
# hier geht es darum, Unsinn gar nicht erst anzunehmen und klare Fehlermeldungen zu geben.

Wochentag = Literal["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
TAG_MUSTER = re.compile(r"[^\W_][\w .&/'+-]{0,39}")
WORT_MUSTER = re.compile(r"[^\W_][\w .&/'+-]{0,58}\*?")
DOMAIN_MUSTER = re.compile(r"[\w-]+(\.[\w-]+)+")
INTERNE_NAMEN = ("localhost", ".localhost", ".local", ".lan", ".home", ".internal", ".intranet", ".corp", ".arpa")
VERBOTENE_ZEICHEN = set('\\"<>`{}|^')
MAX_PRO_BEFEHL = 50


def _oeffentlich(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _url_pruefen(wert: str) -> str:
    url = wert.strip()
    fehler = ValueError(f"Adresse nicht erlaubt: {url[:80]}")
    if not url or len(url) > 500 or any(c.isspace() or not c.isprintable() or c in VERBOTENE_ZEICHEN for c in url):
        raise fehler
    if "://" not in url:
        url = "https://" + url
    try:
        teile = urlparse(url)
        host = teile.hostname or ""
        teile.port
    except ValueError:
        raise fehler from None
    if teile.scheme not in ("http", "https") or not host or "@" in teile.netloc:
        raise fehler
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None  # keine IP-Adresse, sondern ein Name
    if ip is not None:
        if not _oeffentlich(ip):
            raise fehler
        return url
    if re.fullmatch(r"[\d.]+", host) or not DOMAIN_MUSTER.fullmatch(host) \
            or host == "localhost" or host.endswith(INTERNE_NAMEN):
        raise fehler
    return url


def _tag_pruefen(wert: str) -> str:
    name = " ".join(wert.split())
    if not TAG_MUSTER.fullmatch(name):
        raise ValueError(f"Tag-Name nicht erlaubt: {name[:40]} (nur Buchstaben, Ziffern, Leerzeichen und - . & / ' +)")
    return name


def _wort_pruefen(wert: str) -> str:
    wort = " ".join(wert.split())
    if not WORT_MUSTER.fullmatch(wort):
        raise ValueError(f"Schlagwort nicht erlaubt: {wort[:60]} (nur Buchstaben, Ziffern, Leerzeichen, "
                         "- . & / ' + und * am Ende)")
    return wort


QuellUrl = Annotated[str, Field(max_length=600), AfterValidator(_url_pruefen)]
TagName = Annotated[str, Field(max_length=80), AfterValidator(_tag_pruefen)]
Schlagwort = Annotated[str, Field(max_length=100), AfterValidator(_wort_pruefen)]


# --------------------------------------------------------------------------- Datenmodelle

Kurz = Annotated[str, Field(max_length=300)]


class ArtikelIn(BaseModel):
    url: str = Field(max_length=2000, pattern=r"^https?://")
    titel: str = Field(max_length=300)
    medium: str = Field(max_length=200)
    teaser: str = Field("", max_length=700)
    autor: str = Field("", max_length=200)
    datum: Optional[str] = Field(None, max_length=40)
    datum_art: str = Field("", max_length=20)
    tags: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=20)
    gemeldet: bool = False
    gefunden_um: str = Field(max_length=40)


class FehlerIn(BaseModel):
    zeit: str = Field(max_length=40)
    quelle: str = Field(max_length=2000)
    grund: str = Field(max_length=1000)


class StatusIn(BaseModel):
    pausiert: bool
    intervall_minuten: int = Field(ge=1, le=1440)
    letzter_lauf: Optional[str] = Field(None, max_length=40)
    naechster_lauf: Optional[str] = Field(None, max_length=40)
    letztes_ergebnis: Kurz = ""
    wochentag: Kurz = ""
    quellen_heute: int = Field(0, ge=0, le=100000)
    nur_mit_tags: bool = False
    discord_aktiv: bool = False
    push_geraete: int = Field(0, ge=0, le=100)
    vapid_public_key: Optional[str] = Field(None, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    sync_sekunden: int = Field(30, ge=10, le=3600)


class PruefungIn(BaseModel):
    fertig: int = Field(ge=0, le=100000)
    gesamt: int = Field(ge=0, le=100000)


class PulsIn(BaseModel):
    pruefung: Optional[PruefungIn] = None


class AbmeldenIn(BaseModel):
    grund: Literal["beendet", "fehler"]
    text: Kurz = ""


class ErledigtIn(BaseModel):
    id: str = Field(max_length=40)
    ergebnis: Kurz


class QuelleIn(BaseModel):
    wochentag: Wochentag
    url: str = Field(max_length=600)


class TagIn(BaseModel):
    name: str = Field(max_length=80)
    woerter: list[Annotated[str, Field(max_length=100)]] = Field(max_length=100)


class ListenIn(BaseModel):
    """Quellen und Tags, wie sie gerade in den CSV-Dateien auf dem PC stehen (nur zur Anzeige)."""
    quellen: list[QuelleIn] = Field(max_length=700)
    tags: list[TagIn] = Field(max_length=100)


class SyncIn(BaseModel):
    status: StatusIn
    artikel: list[ArtikelIn] = Field(default_factory=list, max_length=600)
    fehler: list[FehlerIn] = Field(default_factory=list, max_length=300)
    erledigt: list[ErledigtIn] = Field(default_factory=list, max_length=100)
    snapshot: bool = False
    listen: Optional[ListenIn] = None  # nur, wenn sich etwas geändert hat


Aktion = Literal["jetzt_pruefen", "pausieren", "fortsetzen", "intervall", "testnachricht",
                 "quellen_hinzufuegen", "quellen_entfernen", "tag_hinzufuegen", "tag_entfernen"]
QUELLEN_AKTIONEN = {"quellen_hinzufuegen", "quellen_entfernen"}
TAG_AKTIONEN = {"tag_hinzufuegen", "tag_entfernen"}


B64 = Annotated[str, Field(min_length=10, max_length=200, pattern=r"^[A-Za-z0-9_-]+=*$")]


class PushSchluessel(BaseModel):
    p256dh: B64
    auth: B64


class PushAbo(BaseModel):
    endpoint: str = Field(max_length=1000, pattern=r"^https://")
    keys: PushSchluessel

    @model_validator(mode="after")
    def nur_push_dienste(self) -> "PushAbo":
        if not (urlparse(self.endpoint).hostname or "").endswith(ERLAUBTE_PUSH_HOSTS):
            raise ValueError("Unbekannter Push-Dienst.")
        return self


class PushIn(BaseModel):
    aktion: Literal["hinzufuegen", "entfernen"]
    abo: PushAbo


class BefehlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aktion: Aktion
    wert: Optional[int] = Field(None, ge=5, le=240)
    tage: list[Wochentag] = Field(default_factory=list, max_length=7)
    urls: list[QuellUrl] = Field(default_factory=list, max_length=MAX_PRO_BEFEHL)
    tag: Optional[TagName] = None
    woerter: list[Schlagwort] = Field(default_factory=list, max_length=MAX_PRO_BEFEHL)

    @model_validator(mode="after")
    def passt_zur_aktion(self) -> "BefehlIn":
        if self.aktion == "intervall" and self.wert is None:
            raise ValueError("Für 'intervall' bitte eine Minutenzahl (5–240) angeben.")
        if self.aktion in QUELLEN_AKTIONEN and (not self.tage or not self.urls):
            raise ValueError("Bitte mindestens eine Adresse und einen Wochentag angeben.")
        if self.aktion in TAG_AKTIONEN and not self.tag:
            raise ValueError("Bitte einen Tag-Namen angeben.")
        if self.aktion == "tag_hinzufuegen" and not self.woerter:
            raise ValueError("Bitte mindestens ein Schlagwort angeben.")
        return self


# --------------------------------------------------------------------------- Speicher (nur im RAM)

class Speicher:
    MAX_ARTIKEL = 400
    MAX_FEHLER = 150
    MAX_BEFEHLE = 25

    def __init__(self) -> None:
        self.lock = Lock()
        self.artikel: OrderedDict[str, dict] = OrderedDict()
        self.fehler: deque[dict] = deque(maxlen=self.MAX_FEHLER)
        self.befehle: list[dict] = []
        self.status: dict | None = None
        self.letzter_kontakt: float | None = None
        self.pruefung: dict | None = None  # Fortschritt einer laufenden Prüfung
        self.beendet: dict | None = None   # Bot hat sich abgemeldet (beendet oder abgestürzt)
        self.hat_snapshot = False
        self.push_aenderungen: list[dict] = []
        self.listen: dict | None = None  # Quellen und Tags vom Bot

    def artikel_hinzufuegen(self, liste: list[ArtikelIn]) -> None:
        for a in liste:
            self.artikel.pop(a.url, None)
            self.artikel[a.url] = a.model_dump()
        while len(self.artikel) > self.MAX_ARTIKEL:
            self.artikel.popitem(last=False)

    def sync(self, daten: SyncIn) -> dict:
        with self.lock:
            self.letzter_kontakt = time.time()
            self.status = daten.status.model_dump()
            self.beendet = self.pruefung = None  # der Bot synchronisiert nur zwischen zwei Prüfungen
            if daten.snapshot:
                self.artikel.clear()
                self.fehler.clear()
                self.hat_snapshot = True
            self.artikel_hinzufuegen(daten.artikel)
            self.fehler.extend(f.model_dump() for f in daten.fehler)
            if daten.listen is not None:
                self.listen = daten.listen.model_dump()

            erledigt = {e.id: e.ergebnis for e in daten.erledigt}
            abzuholen = []
            for b in self.befehle:
                if b["id"] in erledigt:
                    b["zustand"], b["ergebnis"] = "erledigt", erledigt[b["id"]]
                elif b["zustand"] == "offen":
                    b["zustand"] = "abgeholt"
                    abzuholen.append({k: b[k] for k in ("id", "aktion", "wert", "tage", "urls", "tag", "woerter")})
            push, self.push_aenderungen = self.push_aenderungen, []
            return {"befehle": abzuholen, "snapshot_noetig": not self.hat_snapshot, "push_aenderungen": push}

    def puls(self, p: PulsIn) -> None:
        with self.lock:
            self.letzter_kontakt = time.time()
            self.beendet = None
            self.pruefung = p.pruefung.model_dump() if p.pruefung else None

    def abmelden(self, a: AbmeldenIn) -> None:
        with self.lock:
            self.beendet = {"grund": a.grund, "text": a.text, "zeit": time.time()}
            self.pruefung = None

    def push(self, p: PushIn) -> None:
        with self.lock:
            # Pro Gerät nur die letzte Änderung behalten
            self.push_aenderungen = [x for x in self.push_aenderungen if x["abo"]["endpoint"] != p.abo.endpoint]
            self.push_aenderungen = (self.push_aenderungen + [p.model_dump()])[-20:]

    def befehl(self, b: BefehlIn) -> dict:
        with self.lock:
            # Gleiche offene Steuer-Aktion nicht doppelt einreihen – nur den Wert aktualisieren.
            # (Quellen- und Tag-Befehle haben jeweils eigenen Inhalt und bleiben alle erhalten.)
            if b.aktion not in QUELLEN_AKTIONEN | TAG_AKTIONEN:
                for alt in self.befehle:
                    if alt["zustand"] == "offen" and alt["aktion"] == b.aktion:
                        alt["wert"] = b.wert
                        return alt
            neu = {
                "id": uuid.uuid4().hex[:12],
                **b.model_dump(),
                "zustand": "offen",
                "ergebnis": "",
                "erstellt": time.time(),
            }
            self.befehle.append(neu)
            self.befehle = self.befehle[-self.MAX_BEFEHLE:]
            return neu

    def ansicht(self) -> dict:
        with self.lock:
            vor = None if self.letzter_kontakt is None else time.time() - self.letzter_kontakt
            takt = self.status["sync_sekunden"] if self.status else 30
            online = vor is not None and vor < 2 * takt + ONLINE_PUFFER_SEKUNDEN and self.beendet is None
            return {
                "bot": {
                    "online": online,
                    "letzter_kontakt_vor_sekunden": None if vor is None else round(vor),
                    "status": self.status,
                    "pruefung": self.pruefung if online else None,
                    "beendet": None if self.beendet is None else {
                        **self.beendet, "vor_sekunden": round(time.time() - self.beendet["zeit"])},
                },
                "artikel": list(reversed(self.artikel.values())),
                "fehler": list(reversed(self.fehler)),
                "befehle": list(reversed(self.befehle)),
                "listen": self.listen,
                "server_laeuft_seit_sekunden": round(time.time() - SERVER_START),
            }


speicher = Speicher()


# --------------------------------------------------------------------------- Anmeldung

def _signatur(ablauf: int) -> str:
    return hmac.new(SCHLUESSEL, str(ablauf).encode(), hashlib.sha256).hexdigest()


def eingeloggt(request: Request) -> bool:
    ablauf, _, sig = request.cookies.get(COOKIE, "").partition(".")
    if not ablauf.isdigit() or int(ablauf) < time.time():
        return False
    return hmac.compare_digest(sig, _signatur(int(ablauf)))


def nur_eingeloggt(request: Request) -> None:
    if not eingeloggt(request):
        raise HTTPException(401, "Bitte anmelden.")


_fehlversuche: deque[float] = deque()


def zu_viele_fehlversuche() -> bool:
    """Global maximal 20 falsche Passwörter pro 15 Minuten – macht Durchprobieren sinnlos."""
    grenze = time.time() - 15 * 60
    while _fehlversuche and _fehlversuche[0] < grenze:
        _fehlversuche.popleft()
    return len(_fehlversuche) >= 20


def nur_bot(request: Request) -> None:
    erwartet = f"Bearer {BOT_TOKEN}".encode()
    if not hmac.compare_digest(request.headers.get("authorization", "").encode(), erwartet):
        raise HTTPException(401, "Ungültiger Bot-Token.")


# --------------------------------------------------------------------------- Sicherheits-Header

@app.middleware("http")
async def sicherheits_header(request: Request, call_next):
    antwort = await call_next(request)
    antwort.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    antwort.headers["X-Content-Type-Options"] = "nosniff"
    antwort.headers["Referrer-Policy"] = "no-referrer"
    antwort.headers["Cache-Control"] = "no-store"
    return antwort


# --------------------------------------------------------------------------- Seiten

@app.get("/")
def startseite(request: Request):
    return FileResponse(STATIC / ("index.html" if eingeloggt(request) else "login.html"))


@app.get("/sw.js")
def service_worker():
    # Muss im Hauptverzeichnis liegen, damit er für die ganze Seite gilt
    return FileResponse(STATIC / "sw.js", media_type="text/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


SCHRIFTEN = {f"plex-sans-{w}.woff2" for w in (400, 500, 600, 700)} | {"OFL.txt"}


@app.get("/static/fonts/{datei}")
def schrift(datei: str):
    if datei not in SCHRIFTEN:
        raise HTTPException(404)
    return FileResponse(STATIC / "fonts" / datei)


@app.get("/static/{datei}")
def statisch(datei: str):
    erlaubt = {"app.js", "login.js", "style.css", "icon-192.png", "icon-512.png"}
    if datei not in erlaubt:
        raise HTTPException(404)
    return FileResponse(STATIC / datei)


@app.post("/login")
async def login(request: Request):
    if zu_viele_fehlversuche():
        return RedirectResponse("/?fehler=gesperrt", status_code=303)
    felder = parse_qs((await request.body()).decode("utf-8", "replace")[:2000])
    eingabe = (felder.get("passwort") or [""])[0]
    if not hmac.compare_digest(eingabe.encode(), PASSWORT.encode()):
        _fehlversuche.append(time.time())
        await asyncio.sleep(1)  # bremst automatisiertes Raten zusätzlich
        return RedirectResponse("/?fehler=passwort", status_code=303)
    ablauf = int(time.time()) + SITZUNG_SEKUNDEN
    antwort = RedirectResponse("/", status_code=303)
    antwort.set_cookie(
        COOKIE, f"{ablauf}.{_signatur(ablauf)}", max_age=SITZUNG_SEKUNDEN,
        httponly=True, secure=True, samesite="strict",
    )
    return antwort


@app.post("/logout")
def logout():
    antwort = RedirectResponse("/", status_code=303)
    antwort.delete_cookie(COOKIE)
    return antwort


@app.get("/gesund")
def gesund():
    return {"ok": True}


# --------------------------------------------------------------------------- API für die Seite

@app.get("/api/daten")
def daten(request: Request):
    nur_eingeloggt(request)
    return speicher.ansicht()


def lesbarer_fehler(e: ValueError) -> str:
    if isinstance(e, ValidationError):
        meldungen = [f.get("msg", "").removeprefix("Value error, ") for f in e.errors()]
        return "; ".join(dict.fromkeys(meldungen))[:500]
    return "Ungültige Anfrage."


@app.post("/api/befehl")
async def befehl(request: Request):
    nur_eingeloggt(request)
    # Nur JSON annehmen: fremde Webseiten können ohne CORS-Freigabe kein JSON schicken.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Nur JSON erlaubt.")
    if int(request.headers.get("content-length") or 0) > 100_000:
        raise HTTPException(413, "Zu groß.")
    try:
        b = BefehlIn.model_validate(await request.json())
    except ValueError as e:
        return JSONResponse({"detail": lesbarer_fehler(e)}, status_code=422)
    return speicher.befehl(b)


@app.post("/api/push")
async def push_abo(request: Request):
    nur_eingeloggt(request)
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Nur JSON erlaubt.")
    try:
        p = PushIn.model_validate(await request.json())
    except ValueError as e:
        return JSONResponse({"detail": str(e)[:500]}, status_code=422)
    speicher.push(p)
    return {"ok": True}


# --------------------------------------------------------------------------- API für den Bot

@app.post("/bot/sync")
async def bot_sync(request: Request):
    nur_bot(request)  # zuerst prüfen, erst dann den Inhalt überhaupt lesen
    if int(request.headers.get("content-length") or 0) > 3_000_000:
        raise HTTPException(413, "Zu groß.")
    try:
        daten = SyncIn.model_validate(await request.json())
    except ValueError as e:
        return JSONResponse({"detail": str(e)[:2000]}, status_code=422)
    return speicher.sync(daten)


@app.post("/bot/puls")
async def bot_puls(request: Request):
    nur_bot(request)
    try:
        speicher.puls(PulsIn.model_validate(await request.json()))
    except ValueError as e:
        return JSONResponse({"detail": str(e)[:500]}, status_code=422)
    return {"ok": True}


@app.post("/bot/abmelden")
async def bot_abmelden(request: Request):
    nur_bot(request)
    try:
        speicher.abmelden(AbmeldenIn.model_validate(await request.json()))
    except ValueError as e:
        return JSONResponse({"detail": str(e)[:500]}, status_code=422)
    return {"ok": True}
