"""News-Bot (Hobby-Version) – läuft auf deinem PC.

Liest aus einer Excel-Datei die Quellen für den heutigen Wochentag, prüft deren
RSS/Atom-Feeds auf neue Artikel (max. 24 h alt) und meldet sie als
Browser-Benachrichtigung über dein Dashboard auf Render und/oder an Discord.
Das Dashboard zeigt Status, Artikel und Fehler und nimmt Befehle entgegen.
Alles Gemerkte liegt in state.json.

Aufruf:
    python news_bot.py            # läuft dauerhaft (empfohlen, mit Dashboard)
    python news_bot.py --einmal   # genau ein Durchlauf (z. B. für die Aufgabenplanung)
    python news_bot.py --test     # ein Durchlauf, nur Ausgabe in der Konsole, nichts senden/speichern
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import sys
import threading
import time
import tomllib
from datetime import datetime, timedelta, timezone
from html import unescape
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import feedparser
import requests
from openpyxl import load_workbook

import webpush

BASIS = Path(__file__).resolve().parent
CONFIG_DATEI = BASIS / "config.toml"
STATE_DATEI = BASIS / "state.json"
LOCK_DATEI = BASIS / "newsbot.lock"
LOG_DATEI = BASIS / "newsbot.log"
VAPID_DATEI = BASIS / "vapid_privat.pem"  # geheimer Schlüssel für Browser-Benachrichtigungen

WOCHENTAGE = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
USER_AGENT = "PrivaterNewsBot/1.2 (Hobbyprojekt, RSS-Leser)"
TIMEOUT = 20
SYNC_TIMEOUT = 90  # Render-Free braucht nach dem Schlafen ca. 1 Minute zum Aufwachen
PAUSE_ZWISCHEN_ABRUFEN = 1.0
GESEHEN_BEHALTEN_TAGE = 14
VERLAUF_MAX = 300
FEHLER_VERLAUF_MAX = 100
FEED_PFADE = ["/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml"]
TRACKING = re.compile(r"^(utm_\w*|fbclid|gclid|dclid|mc_cid|mc_eid|ref|ref_src|ito|xtor|wt_mc|ns_\w+)$", re.I)
ERLAUBTE_AKTIONEN = {"jetzt_pruefen", "pausieren", "fortsetzen", "intervall", "testnachricht"}

log = logging.getLogger("newsbot")
session = requests.Session()
session.headers["User-Agent"] = USER_AGENT


class AbrufFehler(Exception):
    pass


def jetzt_utc() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- Konfiguration & Zustand

def lade_config() -> dict:
    if not CONFIG_DATEI.exists():
        sys.exit(f"Konfigurationsdatei fehlt: {CONFIG_DATEI}")
    with CONFIG_DATEI.open("rb") as f:
        cfg = tomllib.load(f)
    standard = {
        "excel_datei": "quellen.xlsx", "discord_webhook": "", "discord_webhook_fehler": "",
        "zeitzone": "Europe/Vienna", "max_alter_stunden": 24, "intervall_minuten": 15,
        "nur_mit_tags": False, "max_meldungen_pro_lauf": 25, "tags": {},
    }
    for k, v in standard.items():
        cfg.setdefault(k, v)
    cfg["discord_webhook"] = cfg["discord_webhook"].strip()
    cfg["discord_webhook_fehler"] = cfg["discord_webhook_fehler"].strip()
    d = cfg.setdefault("dashboard", {})
    d.setdefault("url", "")
    d.setdefault("bot_token", "")
    d.setdefault("sync_sekunden", 30)
    d["url"] = d["url"].strip().rstrip("/")
    if d["url"] and not (d["url"].startswith("https://") or d["url"].startswith("http://localhost")
                         or d["url"].startswith("http://127.0.0.1")):
        sys.exit("dashboard.url muss mit https:// beginnen (z. B. https://mein-newsbot.onrender.com).")
    if d["url"] and len(d["bot_token"]) < 32:
        sys.exit("dashboard.bot_token fehlt oder ist zu kurz – kopiere BOT_TOKEN von Render.")
    d["sync_sekunden"] = max(10, int(d["sync_sekunden"]))
    return cfg


def lade_state() -> dict:
    leer = {
        "gesehen": {}, "feeds": {}, "fehler_gemeldet": {}, "fehler_dashboard": {},
        "verlauf": [], "fehler_verlauf": [], "sync_artikel": [], "sync_fehler": [], "sync_erledigt": [],
        "pausiert": False, "intervall_minuten": None, "sofort": False,
        "letzter_lauf": None, "naechster_lauf": None, "letztes_ergebnis": "",
        "wochentag": "", "quellen_heute": 0, "push_abos": [],
    }
    if not STATE_DATEI.exists():
        return leer
    try:
        daten = json.loads(STATE_DATEI.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        sicherung = STATE_DATEI.with_suffix(f".kaputt-{int(time.time())}.json")
        STATE_DATEI.replace(sicherung)
        log.error("state.json unlesbar (%s) – gesichert als %s, starte leer.", e, sicherung.name)
        return leer
    for k, v in leer.items():
        daten.setdefault(k, v)
    return daten


def speichere_state(state: dict) -> None:
    tmp = STATE_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_DATEI)  # atomar: nie halb geschriebene Datei


def intervall(cfg: dict, state: dict) -> int:
    return int(state.get("intervall_minuten") or cfg["intervall_minuten"])


# --------------------------------------------------------------------------- Excel

def lese_quellen(excel: Path, wochentag: str) -> list[str]:
    """Sucht in allen Tabellenblättern eine Kopfzelle mit dem Wochentag und sammelt die URLs darunter."""
    if not excel.exists():
        raise FileNotFoundError(f"Excel-Datei nicht gefunden: {excel}")
    wb = load_workbook(excel, read_only=True, data_only=True)
    rohwerte: list = []
    try:
        for ws in wb.worksheets:
            zeilen = list(ws.iter_rows(values_only=True))
            for z_idx, zeile in enumerate(zeilen[:15]):
                for s_idx, zelle in enumerate(zeile):
                    if isinstance(zelle, str) and zelle.strip().lower() == wochentag:
                        rohwerte += [z[s_idx] for z in zeilen[z_idx + 1:] if s_idx < len(z)]
    finally:
        wb.close()
    return bereinige_urls(rohwerte)


def bereinige_urls(werte: list) -> list[str]:
    ergebnis: list[str] = []
    for wert in werte:
        if wert is None or not str(wert).strip():
            continue
        url = str(wert).strip()
        if "://" not in url:
            url = "https://" + url
        teile = urlparse(url)
        if teile.scheme not in ("http", "https") or "." not in teile.netloc or " " in url:
            log.warning("Ungültige URL in Excel übersprungen: %r", wert)
            continue
        if url not in ergebnis:
            ergebnis.append(url)
    return ergebnis


# --------------------------------------------------------------------------- Netzwerk

_robots: dict[str, RobotFileParser] = {}


def erlaubt(url: str) -> bool:
    """Respektiert die robots.txt der jeweiligen Seite."""
    teile = urlparse(url)
    basis = f"{teile.scheme}://{teile.netloc}"
    rp = _robots.get(basis)
    if rp is None:
        rp = RobotFileParser()
        try:
            r = session.get(basis + "/robots.txt", timeout=TIMEOUT)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[basis] = rp
    return rp.can_fetch(USER_AGENT, url)


def hole(url: str) -> requests.Response:
    if not erlaubt(url):
        raise AbrufFehler(f"robots.txt verbietet den Abruf von {url}")
    time.sleep(PAUSE_ZWISCHEN_ABRUFEN)
    try:
        r = session.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AbrufFehler(f"{url}: {type(e).__name__}") from e
    if r.status_code != 200:
        raise AbrufFehler(f"{url}: HTTP {r.status_code}")
    return r


# --------------------------------------------------------------------------- Feeds finden & lesen

def ist_feed(inhalt: bytes) -> bool:
    d = feedparser.parse(inhalt)
    return bool(d.version) and bool(d.entries)


def finde_feed(url: str) -> str:
    """Ist die URL selbst ein Feed? Sonst <link rel=alternate> auf der Seite, sonst übliche Pfade."""
    r = hole(url)
    if ist_feed(r.content):
        return url
    for tag in re.findall(r"<link\b[^>]*>", r.text, re.I):
        if re.search(r"rel=[\"']?alternate", tag, re.I) and re.search(
            r"type=[\"']?application/(rss|atom)\+xml", tag, re.I
        ):
            href = re.search(r"href=[\"']([^\"']+)", tag, re.I)
            if href:
                return urljoin(r.url, unescape(href.group(1)))
    for pfad in FEED_PFADE:
        kandidat = urljoin(r.url, pfad)
        try:
            if ist_feed(hole(kandidat).content):
                return kandidat
        except AbrufFehler:
            continue
    raise AbrufFehler(f"Kein RSS/Atom-Feed gefunden für {url} – trage die Feed-URL direkt in die Excel ein.")


def normalisiere_url(url: str) -> str:
    t = urlparse(url.strip())
    query = sorted((k, v) for k, v in parse_qsl(t.query, keep_blank_values=True) if not TRACKING.match(k))
    return urlunparse((t.scheme.lower(), t.netloc.lower(), t.path or "/", "", urlencode(query), ""))


def text_aus_html(html: str, max_zeichen: int = 450) -> str:
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()
    if len(text) > max_zeichen:
        text = text[:max_zeichen].rsplit(" ", 1)[0] + " …"
    return text


def lese_artikel(feed_inhalt: bytes, feed_url: str, jetzt: datetime, max_alter: timedelta) -> list[dict]:
    d = feedparser.parse(feed_inhalt)
    medium = text_aus_html(d.feed.get("title") or urlparse(feed_url).netloc, 150)
    artikel = []
    for e in d.entries:
        link = e.get("link")
        if not link:
            continue
        if e.get("published_parsed"):
            datum, datum_art = datetime(*e.published_parsed[:6], tzinfo=timezone.utc), "veröffentlicht"
        elif e.get("updated_parsed"):
            datum, datum_art = datetime(*e.updated_parsed[:6], tzinfo=timezone.utc), "aktualisiert"
        else:
            datum, datum_art = None, "unbekannt"
        if datum and jetzt - datum > max_alter:
            continue
        url = normalisiere_url(urljoin(feed_url, link))
        if not url.startswith(("http://", "https://")):
            continue
        artikel.append({
            "schluessel": [url] + ([f"id:{e.id}"] if e.get("id") else []),
            "url": url,
            "titel": text_aus_html(e.get("title", "(ohne Titel)"), 250),
            "teaser": text_aus_html(e.get("summary", "")),
            "autor": text_aus_html(e.get("author") or "", 150),
            "medium": medium,
            "datum": datum,
            "datum_art": datum_art,
        })
    return artikel


# --------------------------------------------------------------------------- Tags

def finde_tags(text: str, regeln: dict[str, list[str]]) -> list[str]:
    """Schlagwort-Tags. "cyber*" = Wortanfang (Cyberangriff), "KI" = ganzes Wort (nicht Kiew)."""
    treffer = []
    for tag, woerter in regeln.items():
        for wort in woerter:
            if wort.endswith("*"):
                muster = rf"(?<!\w){re.escape(wort[:-1])}"
            else:
                muster = rf"(?<!\w){re.escape(wort)}(?!\w)"
            if re.search(muster, text, re.I):
                treffer.append(tag)
                break
    return treffer


# --------------------------------------------------------------------------- Discord

def sende_discord(webhook: str, payload: dict) -> bool:
    payload["allowed_mentions"] = {"parse": []}  # Artikeltexte dürfen nie @everyone o. Ä. auslösen
    for _ in range(4):
        try:
            r = session.post(webhook, json=payload, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.error("Discord nicht erreichbar: %s", e)
            return False
        if r.status_code == 429:
            try:
                warte = float(r.json().get("retry_after", 2))
            except ValueError:
                warte = 2.0
            time.sleep(min(warte, 30) + 0.2)
            continue
        if r.ok:
            return True
        log.error("Discord-Fehler HTTP %s: %s", r.status_code, r.text[:200])
        return False
    return False


def baue_meldung(a: dict, tz: ZoneInfo) -> dict:
    if a["datum"] is None:
        zeit = "⚠️ unbekannt (bitte prüfen)"
    else:
        zeit = a["datum"].astimezone(tz).strftime("%d.%m.%Y, %H:%M Uhr")
        if a["datum_art"] == "aktualisiert":
            zeit += " (nur Aktualisierungsdatum bekannt)"
    tags = " ".join(f"`{t}`" for t in a["tags"]) or "–"
    beschreibung = a["teaser"] or "_Kein Vorschautext im Feed – bitte Artikel öffnen._"
    felder = [
        {"name": "Medium", "value": a["medium"][:1024] or "–", "inline": True},
        {"name": "Veröffentlicht", "value": zeit, "inline": True},
        {"name": "Tags", "value": tags[:1024], "inline": False},
    ]
    if a["autor"]:
        felder.insert(1, {"name": "Autor", "value": a["autor"][:1024], "inline": True})
    return {
        "content": f"**[NEUER ARTIKEL] {a['tags'][0] if a['tags'] else 'Allgemein'}**",
        "embeds": [{
            "title": a["titel"][:256],
            "url": a["url"],
            "description": f"**Vorschau laut Feed:**\n{beschreibung}\n\n**Direkter Artikel-Link:**\n{a['url']}"[:4000],
            "fields": felder,
            "color": 0x2B6CB0 if a["tags"] else 0x8A8A8A,
        }],
    }


def melde_fehler(cfg: dict, state: dict, quelle: str, grund: str, test: bool) -> None:
    log.warning("Quelle %s: %s", quelle, grund)
    if test:
        return
    jetzt = jetzt_utc()
    # Dashboard: höchstens ein Eintrag pro Quelle und Stunde
    letzter = state["fehler_dashboard"].get(quelle)
    if not letzter or jetzt - datetime.fromisoformat(letzter) > timedelta(hours=1):
        eintrag = {"zeit": jetzt.isoformat(), "quelle": quelle[:2000], "grund": grund[:1000]}
        state["fehler_verlauf"] = (state["fehler_verlauf"] + [eintrag])[-FEHLER_VERLAUF_MAX:]
        state["sync_fehler"] = (state["sync_fehler"] + [eintrag])[-200:]
        state["fehler_dashboard"][quelle] = jetzt.isoformat()
    # Discord: höchstens eine Meldung pro Quelle und Tag
    heute = datetime.now(ZoneInfo(cfg["zeitzone"])).date().isoformat()
    if state["fehler_gemeldet"].get(quelle) == heute:
        return
    webhook = cfg["discord_webhook_fehler"] or cfg["discord_webhook"]
    if webhook and sende_discord(webhook, {"content": f"⚠️ **Quelle nicht abrufbar:** <{quelle}>\n{grund}"[:1900]}):
        state["fehler_gemeldet"][quelle] = heute


# --------------------------------------------------------------------------- Browser-Benachrichtigungen (Web Push)

_vapid_schluessel = None  # wird in main() geladen, wenn ein Dashboard eingerichtet ist


def push_kontakt(cfg: dict) -> str:
    url = cfg["dashboard"]["url"]
    return url if url.startswith("https://") else "mailto:newsbot@example.com"


def sende_push_an_alle(cfg: dict, state: dict, nachricht: dict) -> tuple[int, int]:
    """Gibt (erfolgreich, versucht) zurück. Abbestellte Geräte werden automatisch entfernt."""
    if _vapid_schluessel is None or not state["push_abos"]:
        return 0, 0
    ok, bleiben = 0, []
    for abo in state["push_abos"]:
        try:
            webpush.sende(abo, nachricht, _vapid_schluessel, push_kontakt(cfg), session, TIMEOUT)
            ok += 1
            bleiben.append(abo)
        except webpush.PushAbgelaufen as e:
            log.info("Gerät hat Benachrichtigungen abbestellt (%s) – entfernt.", e)
        except requests.RequestException as e:
            log.warning("Push fehlgeschlagen: %s", e)
            bleiben.append(abo)
    versucht = len(state["push_abos"])
    state["push_abos"] = bleiben
    return ok, versucht


def push_nachricht(a: dict) -> dict:
    zeile = a["medium"] + (f" – {', '.join(a['tags'])}" if a["tags"] else "")
    text = f"{zeile}\n{a['teaser']}" if a["teaser"] else zeile
    return {"titel": a["titel"][:200], "text": text[:300], "url": a["url"], "tag": a["url"][:200]}


def benachrichtige(cfg: dict, state: dict, a: dict, tz: ZoneInfo) -> bool | None:
    """Discord und/oder Browser-Push. True = mindestens ein Weg klappte,
    False = alle Wege fehlgeschlagen (später erneut versuchen), None = kein Weg eingerichtet."""
    versucht = erfolg = False
    if cfg["discord_webhook"]:
        versucht = True
        erfolg = sende_discord(cfg["discord_webhook"], baue_meldung(a, tz))
    push_ok, push_versucht = sende_push_an_alle(cfg, state, push_nachricht(a))
    if push_versucht:
        versucht = True
        erfolg = erfolg or push_ok > 0
    return erfolg if versucht else None


def aendere_push_abos(cfg: dict, state: dict, aenderungen: list) -> None:
    for aenderung in aenderungen[:20]:
        if not isinstance(aenderung, dict):
            continue
        abo = aenderung.get("abo")
        if not webpush.abo_ist_gueltig(abo):
            log.warning("Ungültiges Benachrichtigungs-Abo vom Dashboard ignoriert.")
            continue
        sauber = {"endpoint": abo["endpoint"], "keys": {"p256dh": abo["keys"]["p256dh"], "auth": abo["keys"]["auth"]}}
        vorher = [x for x in state["push_abos"] if x["endpoint"] != sauber["endpoint"]]
        neu = len(vorher) == len(state["push_abos"])
        if aenderung.get("aktion") == "entfernen":
            state["push_abos"] = vorher
            log.info("Benachrichtigungen auf einem Gerät ausgeschaltet.")
        elif aenderung.get("aktion") == "hinzufuegen":
            state["push_abos"] = (vorher + [sauber])[-20:]
            if neu and _vapid_schluessel is not None:
                log.info("Benachrichtigungen auf einem neuen Gerät eingeschaltet.")
                try:
                    webpush.sende(sauber, {"titel": "Benachrichtigungen sind an",
                                           "text": "Ab jetzt meldet sich der News-Bot hier bei neuen Artikeln.",
                                           "url": cfg["dashboard"]["url"] or ""},
                                  _vapid_schluessel, push_kontakt(cfg), session, TIMEOUT)
                except webpush.PushAbgelaufen as e:
                    state["push_abos"] = vorher
                    log.warning("Neues Gerät nimmt keine Benachrichtigungen an (%s) – nicht gespeichert.", e)
                except requests.RequestException as e:
                    log.warning("Bestätigung an neues Gerät fehlgeschlagen: %s", e)
    speichere_state(state)


# --------------------------------------------------------------------------- Durchlauf

def merke_fuer_dashboard(state: dict, a: dict, gemeldet: bool) -> None:
    eintrag = {
        "url": a["url"], "titel": a["titel"], "medium": a["medium"], "teaser": a["teaser"],
        "autor": a["autor"], "datum": a["datum"].isoformat() if a["datum"] else None,
        "datum_art": a["datum_art"], "tags": a["tags"], "gemeldet": gemeldet,
        "gefunden_um": jetzt_utc().isoformat(),
    }
    state["verlauf"] = (state["verlauf"] + [eintrag])[-VERLAUF_MAX:]
    state["sync_artikel"] = (state["sync_artikel"] + [eintrag])[-500:]


def merke_gesehen(state: dict, a: dict) -> None:
    for s in a["schluessel"]:
        state["gesehen"][s] = jetzt_utc().isoformat()


def durchlauf(cfg: dict, state: dict, test: bool = False) -> str:
    """Prüft alle heutigen Quellen. Gibt eine kurze Zusammenfassung zurück."""
    tz = ZoneInfo(cfg["zeitzone"])
    jetzt = jetzt_utc()
    wochentag = WOCHENTAGE[datetime.now(tz).weekday()]
    max_alter = timedelta(hours=cfg["max_alter_stunden"])

    excel = Path(cfg["excel_datei"])
    excel = excel if excel.is_absolute() else BASIS / excel
    quellen = lese_quellen(excel, wochentag)
    state["wochentag"], state["quellen_heute"] = wochentag.capitalize(), len(quellen)
    if not quellen:
        log.info("Für %s sind keine Quellen eingetragen – nichts zu tun.", wochentag.capitalize())
        return "keine Quellen für heute eingetragen"
    log.info("%s: prüfe %d Quelle(n).", wochentag.capitalize(), len(quellen))

    grenze = (jetzt - timedelta(days=GESEHEN_BEHALTEN_TAGE)).isoformat()
    state["gesehen"] = {k: v for k, v in state["gesehen"].items() if v >= grenze}

    neue: list[dict] = []
    schon_im_lauf: set[str] = set()
    fehlerhaft = 0
    for nr, quelle in enumerate(quellen):
        setze_pruefung(nr, len(quellen))
        try:
            feed_url = state["feeds"].get(quelle) or finde_feed(quelle)
            state["feeds"][quelle] = feed_url
            artikel = lese_artikel(hole(feed_url).content, feed_url, jetzt, max_alter)
        except AbrufFehler as e:
            state["feeds"].pop(quelle, None)  # beim nächsten Mal Feed neu suchen
            melde_fehler(cfg, state, quelle, str(e), test)
            fehlerhaft += 1
            continue
        for a in artikel:
            if any(s in state["gesehen"] or s in schon_im_lauf for s in a["schluessel"]):
                continue
            schon_im_lauf.update(a["schluessel"])
            a["tags"] = finde_tags(f"{a['titel']} {a['teaser']}", cfg["tags"])
            neue.append(a)

    neue.sort(key=lambda a: a["datum"] or jetzt)  # älteste zuerst
    gesendet = verarbeitet = 0
    for a in neue:
        if cfg["nur_mit_tags"] and not a["tags"]:
            if not test:
                merke_gesehen(state, a)
                merke_fuer_dashboard(state, a, gemeldet=False)  # Seite zeigt alles, Benachrichtigung nur Relevantes
            verarbeitet += 1
            continue
        if gesendet >= cfg["max_meldungen_pro_lauf"]:
            log.info("Limit pro Lauf erreicht – restliche Artikel folgen beim nächsten Lauf.")
            break
        if test:
            print(f"[{', '.join(a['tags']) or '-'}] {a['medium']} | {a['titel']}\n    {a['url']}")
            gesendet += 1
            verarbeitet += 1
            continue
        ergebnis = benachrichtige(cfg, state, a, tz)
        if ergebnis is False:
            continue  # alle Wege fehlgeschlagen → nicht als gesehen markieren, nächster Lauf versucht es erneut
        merke_gesehen(state, a)
        merke_fuer_dashboard(state, a, gemeldet=bool(ergebnis))
        speichere_state(state)  # nach jeder Meldung → keine Doppelmeldungen nach Absturz
        gesendet += 1 if ergebnis else 0
        verarbeitet += 1

    teile = [f"{len(neue)} neu", f"{gesendet} gemeldet"]
    if verarbeitet < len(neue):
        teile.append(f"{len(neue) - verarbeitet} folgen später")
    if fehlerhaft:
        teile.append("1 Quelle mit Fehler" if fehlerhaft == 1 else f"{fehlerhaft} Quellen mit Fehler")
    zusammenfassung = ", ".join(teile)
    log.info("Fertig: %s.", zusammenfassung)
    return zusammenfassung


# --------------------------------------------------------------------------- Dashboard-Sync & Befehle

def baue_status(cfg: dict, state: dict) -> dict:
    return {
        "pausiert": state["pausiert"],
        "intervall_minuten": intervall(cfg, state),
        "letzter_lauf": state["letzter_lauf"],
        "naechster_lauf": state["naechster_lauf"],
        "letztes_ergebnis": state["letztes_ergebnis"][:300],
        "wochentag": state["wochentag"],
        "quellen_heute": state["quellen_heute"],
        "nur_mit_tags": bool(cfg["nur_mit_tags"]),
        "discord_aktiv": bool(cfg["discord_webhook"]),
        "push_geraete": len(state["push_abos"]),
        "vapid_public_key": webpush.oeffentlicher_schluessel(_vapid_schluessel) if _vapid_schluessel else None,
        "sync_sekunden": cfg["dashboard"]["sync_sekunden"],
    }


# Lebenszeichen: Eine eigene Leitung meldet sich auch während langer Prüfungen beim
# Dashboard, damit die Seite einen hängenden oder abgestürzten Bot von einem fleißigen
# unterscheiden kann. Beim Beenden verabschiedet sich der Bot ausdrücklich.
_puls = {"kontakt": 0.0, "versuch": 0.0, "pruefung": None, "geaendert": False}
_puls_lock = threading.Lock()
_erster_sync = True  # nach dem Start schickt der Bot einmal seinen kompletten Stand
_abgemeldet = False


def setze_pruefung(fertig: int | None, gesamt: int = 0) -> None:
    """fertig=None: keine Prüfung läuft. Sonst Fortschritt für die Seite."""
    with _puls_lock:
        neu = None if fertig is None else {"fertig": fertig, "gesamt": gesamt}
        _puls["geaendert"] = _puls["geaendert"] or (neu is None) != (_puls["pruefung"] is None)
        _puls["pruefung"] = neu


def merke_kontakt() -> None:
    with _puls_lock:
        _puls["kontakt"] = time.monotonic()


def puls_schleife(cfg: dict) -> None:
    d = cfg["dashboard"]
    kopf = {"Authorization": f"Bearer {d['bot_token']}"}
    leitung = requests.Session()  # eigene Session – requests.Session ist nicht threadsicher
    leitung.headers["User-Agent"] = USER_AGENT
    while True:
        time.sleep(2)
        with _puls_lock:
            ruhe = time.monotonic() - max(_puls["kontakt"], _puls["versuch"])
            if not (_puls["geaendert"] and _puls["pruefung"]) and ruhe < d["sync_sekunden"] + 5:
                continue
            _puls["geaendert"], _puls["versuch"] = False, time.monotonic()
            pruefung = _puls["pruefung"]
        try:
            r = leitung.post(f"{d['url']}/bot/puls", json={"pruefung": pruefung}, headers=kopf, timeout=SYNC_TIMEOUT)
            if r.ok:
                merke_kontakt()
        except requests.RequestException:
            pass  # die Hauptschleife meldet Verbindungsprobleme schon im Log


def melde_ende(cfg: dict, grund: str, text: str) -> None:
    """Sagt dem Dashboard, dass der Bot aufhört – damit dort nicht der alte Stand stehen bleibt."""
    global _abgemeldet
    d = cfg["dashboard"]
    if not d["url"] or _abgemeldet:
        return
    _abgemeldet = True
    try:
        requests.post(f"{d['url']}/bot/abmelden", json={"grund": grund, "text": text[:300]},
                      headers={"Authorization": f"Bearer {d['bot_token']}", "User-Agent": USER_AGENT}, timeout=4)
    except requests.RequestException:
        pass  # Seite schläft oder kein Netz – sie merkt es dann am fehlenden Lebenszeichen


def fange_fenster_schliessen_ab(cfg: dict) -> None:
    """Windows: Konsolenfenster schließen, Abmelden oder Herunterfahren → noch schnell abmelden.

    Windows lässt dafür etwa 5 Sekunden Zeit. Strg+C läuft weiter über KeyboardInterrupt.
    """
    if os.name != "nt":
        return
    import ctypes

    def behandle(ereignis: int) -> bool:
        if ereignis in (2, 5, 6):  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
            log.info("Fenster wird geschlossen – Bot beendet.")
            melde_ende(cfg, "beendet", "Konsolenfenster geschlossen oder Windows heruntergefahren.")
            return True
        return False

    global _fenster_handler
    _fenster_handler = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)(behandle)  # Referenz halten!
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_fenster_handler, True)


_fenster_handler = None


def synchronisiere(cfg: dict, state: dict) -> list[dict]:
    """Schickt Status/Neues an das Dashboard und holt offene Befehle ab."""
    global _erster_sync
    d = cfg["dashboard"]
    if not d["url"]:
        return []
    kopf = {"Authorization": f"Bearer {d['bot_token']}"}
    if _erster_sync:
        # Kompletter Stand statt nur Neues – so übernimmt die Seite auch einen geleerten Bot.
        nutzlast = {"status": baue_status(cfg, state), "artikel": state["verlauf"],
                    "fehler": state["fehler_verlauf"], "erledigt": state["sync_erledigt"][-100:], "snapshot": True}
    else:
        nutzlast = {
            "status": baue_status(cfg, state),
            "artikel": state["sync_artikel"],
            "fehler": state["sync_fehler"],
            "erledigt": state["sync_erledigt"][-100:],
            "snapshot": False,
        }
    befehle: list[dict] = []
    for _ in range(2):
        try:
            r = session.post(f"{d['url']}/bot/sync", json=nutzlast, headers=kopf, timeout=SYNC_TIMEOUT)
        except requests.RequestException as e:
            log.warning("Dashboard nicht erreichbar (%s) – versuche es später erneut.", type(e).__name__)
            return befehle
        if r.status_code == 401:
            log.error("Dashboard lehnt den Bot-Token ab – stimmt bot_token mit BOT_TOKEN bei Render überein?")
            return befehle
        if not r.ok:
            log.warning("Dashboard antwortet mit HTTP %s: %s", r.status_code, r.text[:300])
            return befehle
        try:
            antwort = r.json()
        except ValueError:  # z. B. Ladeseite, während Render aufwacht
            log.warning("Dashboard liefert noch keine gültige Antwort (wacht vermutlich gerade auf).")
            return befehle
        merke_kontakt()
        _erster_sync = False
        state["sync_artikel"], state["sync_fehler"], state["sync_erledigt"] = [], [], []
        befehle += antwort.get("befehle", [])
        geraete_geaendert = bool(antwort.get("push_aenderungen"))
        if geraete_geaendert:
            aendere_push_abos(cfg, state, antwort["push_aenderungen"])
        if antwort.get("snapshot_noetig") and not nutzlast["snapshot"]:
            # Render wurde neu gestartet und hat nichts mehr im Speicher → kompletten Verlauf schicken
            log.info("Dashboard ist leer (Neustart bei Render) – schicke kompletten Verlauf.")
            nutzlast.update(status=baue_status(cfg, state), artikel=state["verlauf"],
                            fehler=state["fehler_verlauf"], erledigt=[], snapshot=True)
            continue
        if geraete_geaendert:
            # neue Geräteanzahl sofort auf die Seite bringen
            nutzlast.update(status=baue_status(cfg, state), artikel=[], fehler=[], erledigt=[], snapshot=False)
            continue
        break
    return befehle


def fuehre_befehl_aus(b: dict, cfg: dict, state: dict) -> str:
    """Nur fest definierte Aktionen – alles andere wird ignoriert."""
    aktion = b.get("aktion")
    if aktion not in ERLAUBTE_AKTIONEN:
        return "unbekannte Aktion – ignoriert"
    if aktion == "pausieren":
        state["pausiert"] = True
        return "Monitoring pausiert"
    if aktion == "fortsetzen":
        state["pausiert"] = False
        state["naechster_lauf"] = jetzt_utc().isoformat()
        return "Monitoring fortgesetzt"
    if aktion == "jetzt_pruefen":
        state["sofort"] = True
        return "Prüfung gestartet"
    if aktion == "intervall":
        wert = b.get("wert")
        if not isinstance(wert, int) or not 5 <= wert <= 240:
            return "ungültiges Intervall – ignoriert"
        state["intervall_minuten"] = wert
        basis = datetime.fromisoformat(state["letzter_lauf"]) if state["letzter_lauf"] else jetzt_utc()
        state["naechster_lauf"] = (basis + timedelta(minutes=wert)).isoformat()
        return f"Intervall auf {wert} Minuten gesetzt"
    if aktion == "testnachricht":
        teile = []
        if cfg["discord_webhook"]:
            ok = sende_discord(cfg["discord_webhook"], {"content": "✅ Testnachricht vom News-Bot – die Verbindung klappt."})
            teile.append("Discord: gesendet" if ok else "Discord: fehlgeschlagen, Webhook prüfen")
        ok, versucht = sende_push_an_alle(cfg, state, {
            "titel": "Testbenachrichtigung", "text": "Die Verbindung zum News-Bot klappt.", "url": cfg["dashboard"]["url"]})
        if versucht:
            teile.append(f"Browser: an {ok} von {versucht} Gerät(en) gesendet")
        return "; ".join(teile) or "kein Benachrichtigungsweg eingerichtet – auf der Seite „Benachrichtigungen einschalten“"
    return "ignoriert"


def verarbeite_befehle(cfg: dict, state: dict) -> None:
    for b in synchronisiere(cfg, state):
        ergebnis = fuehre_befehl_aus(b, cfg, state)
        log.info("Befehl %s: %s", b.get("aktion"), ergebnis)
        state["sync_erledigt"].append({"id": str(b.get("id", ""))[:40], "ergebnis": ergebnis})
        speichere_state(state)


def faellig(state: dict) -> bool:
    if state["sofort"]:
        return True
    if state["pausiert"]:
        return False
    return not state["naechster_lauf"] or jetzt_utc() >= datetime.fromisoformat(state["naechster_lauf"])


def pruefen_und_merken(cfg: dict, state: dict) -> None:
    try:
        ergebnis = durchlauf(cfg, state)
    except FileNotFoundError as e:
        log.error("%s", e)
        ergebnis = str(e)
    except Exception as e:  # der Bot soll nie wegen eines einzelnen Problems stehen bleiben
        log.exception("Unerwarteter Fehler im Durchlauf")
        ergebnis = f"Fehler: {type(e).__name__}"
    finally:
        setze_pruefung(None)
    jetzt = jetzt_utc()
    state["letzter_lauf"] = jetzt.isoformat()
    state["naechster_lauf"] = (jetzt + timedelta(minutes=intervall(cfg, state))).isoformat()
    state["letztes_ergebnis"] = ergebnis
    state["sofort"] = False
    speichere_state(state)


# --------------------------------------------------------------------------- Start

def richte_logging_ein() -> None:
    format_ = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    datei = RotatingFileHandler(LOG_DATEI, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    konsole = logging.StreamHandler()
    for h in (datei, konsole):
        h.setFormatter(format_)
        log.addHandler(h)
    log.setLevel(logging.INFO)


_lock_datei = None


def hole_lock() -> bool:
    """Verhindert, dass der Bot zweimal gleichzeitig läuft.

    Nutzt eine Sperre des Betriebssystems: Sie wird automatisch frei, wenn der
    Prozess endet – auch nach einem Absturz oder wenn das Fenster geschlossen wird.
    """
    global _lock_datei
    f = open(LOCK_DATEI, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_datei = f
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Kleiner News-Bot für Discord")
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument("--einmal", action="store_true", help="genau ein Durchlauf")
    gruppe.add_argument("--test", action="store_true", help="ein Durchlauf, nichts senden oder speichern")
    args = parser.parse_args()
    richte_logging_ein()
    cfg = lade_config()

    if args.test:
        durchlauf(cfg, copy.deepcopy(lade_state()), test=True)
        return
    if cfg["discord_webhook"] and not cfg["discord_webhook"].startswith("https://"):
        sys.exit("discord_webhook in config.toml muss mit https:// beginnen (oder leer bleiben).")
    if not cfg["discord_webhook"] and not cfg["dashboard"]["url"]:
        sys.exit("Weder Discord noch Dashboard eingerichtet – trage mindestens eines in config.toml ein.")
    global _vapid_schluessel
    if cfg["dashboard"]["url"]:
        _vapid_schluessel = webpush.lade_oder_erzeuge_schluessel(VAPID_DATEI)
    if not hole_lock():
        sys.exit("Der Bot läuft bereits (newsbot.lock vorhanden).")

    try:
        state = lade_state()
        if args.einmal:
            verarbeite_befehle(cfg, state)
            if not state["pausiert"] or state["sofort"]:
                pruefen_und_merken(cfg, state)
            verarbeite_befehle(cfg, state)
            speichere_state(state)
            return

        log.info("Bot gestartet. Dashboard: %s", cfg["dashboard"]["url"] or "nicht eingerichtet")
        if cfg["dashboard"]["url"]:
            threading.Thread(target=puls_schleife, args=(cfg,), daemon=True, name="puls").start()
            fange_fenster_schliessen_ab(cfg)
        pause = cfg["dashboard"]["sync_sekunden"] if cfg["dashboard"]["url"] else 30
        while True:
            try:
                verarbeite_befehle(cfg, state)
                if faellig(state):
                    pruefen_und_merken(cfg, state)
                    verarbeite_befehle(cfg, state)  # Ergebnis sofort auf die Seite bringen
                speichere_state(state)
            except Exception:  # nie ganz stehen bleiben – beim nächsten Takt neu versuchen
                log.exception("Unerwarteter Fehler in der Hauptschleife")
            time.sleep(pause)
    except KeyboardInterrupt:
        log.info("Bot beendet.")
        melde_ende(cfg, "beendet", "Der Bot wurde auf dem PC beendet.")
    except BaseException as e:
        log.exception("Bot abgestürzt")
        melde_ende(cfg, "fehler", f"Abgestürzt: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
