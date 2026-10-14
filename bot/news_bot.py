"""News-Bot (Hobby-Version) – läuft auf deinem PC.

Liest aus quellen.csv die Quellen für den heutigen Wochentag, prüft deren
RSS/Atom-Feeds auf neue Artikel (max. 24 h alt), lässt eine KI (DeepSeek oder Claude) passende
Tags aus tags.csv auswählen (ki_tags.py) und meldet sie als Browser-Benachrichtigung über
dein Dashboard auf Render und/oder an Discord. Das Dashboard zeigt Status, Artikel, Fehler, Quellen und Tags und nimmt
Befehle entgegen – auch neue Quellen und Tags. Alles Gemerkte liegt in state.json.

Aufruf:
    python news_bot.py            # läuft dauerhaft (empfohlen, mit Dashboard)
    python news_bot.py --einmal   # genau ein Durchlauf (z. B. für die Aufgabenplanung)
    python news_bot.py --test     # ein Durchlauf, nur Ausgabe in der Konsole, nichts senden/speichern
    python news_bot.py --prompt   # den kompletten Prompt an die KI in prompt-vorschau.txt schreiben
    python news_bot.py --zuruecksetzen  # nicht angeschaute Artikel vergessen (Abgehakte, Quellen, Tags, Geräte bleiben)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
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
import urllib3

import ki_tags
import listen
import seiten
import webpush

BASIS = Path(__file__).resolve().parent
CONFIG_DATEI = BASIS / "config.toml"
STATE_DATEI = BASIS / "state.json"
LOCK_DATEI = BASIS / "newsbot.lock"
LOG_DATEI = BASIS / "newsbot.log"
VAPID_DATEI = BASIS / "vapid_privat.pem"  # geheimer Schlüssel für Browser-Benachrichtigungen
QUELLEN_DATEI = BASIS / "quellen.csv"
TAGS_DATEI = BASIS / "tags.csv"

WOCHENTAGE = listen.WOCHENTAGE
USER_AGENT = "PrivaterNewsBot/1.4 (Hobbyprojekt, liest RSS-Feeds und Sitemaps)"
TIMEOUT = 20
SYNC_TIMEOUT = 90  # Render-Free braucht nach dem Schlafen ca. 1 Minute zum Aufwachen
PAUSE_ZWISCHEN_ABRUFEN = 1.0
GESEHEN_BEHALTEN_TAGE = 14
MAX_ALTER_GRENZE = 168  # 7 Tage; muss unter GESEHEN_BEHALTEN_TAGE bleiben, sonst kämen alte Artikel doppelt
VERLAUF_MAX = 300
FEHLER_VERLAUF_MAX = 100
FEED_PFADE = ["/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml"]
TRACKING = re.compile(r"^(utm_\w*|fbclid|gclid|dclid|mc_cid|mc_eid|ref|ref_src|ito|xtor|wt_mc|ns_\w+)$", re.I)
MAX_WEITERLEITUNGEN = 5
MAX_SEITE_BYTES = 5_000_000      # Feeds und Webseiten
MAX_SITEMAP_BYTES = 15_000_000   # Sitemaps können groß sein
MAX_ROBOTS_BYTES = 500_000
MAX_DOWNLOAD_SEKUNDEN = 60       # Gesamtzeit pro Abruf – ein Server, der Byte für Byte tröpfelt, hält den Bot nicht fest
MAX_SEITENABRUFE = 20            # Artikelseiten pro Quelle und Prüfung (Sitemap/Startseite)
MAX_ERSTABRUFE_STARTSEITE = 10   # beim ersten Mal nur die obersten Links der Startseite ansehen
WEG_NEU_SUCHEN_STUNDEN = 24      # ohne Feed: einmal am Tag schauen, ob es inzwischen einen gibt
WEGE = {"feed": "RSS-Feed", "news_sitemap": "News-Sitemap", "sitemap": "Sitemap", "startseite": "Startseite"}
ERLAUBTE_AKTIONEN = {"jetzt_pruefen", "pausieren", "fortsetzen", "intervall", "max_alter", "testnachricht",
                     "quellen_hinzufuegen", "quellen_entfernen", "tag_hinzufuegen", "tag_entfernen",
                     "quellen_importieren", "tags_importieren", "angeschaut"}
STANDARD_EINSTELLUNGEN = {
    "discord_webhook": "", "discord_webhook_fehler": "",
    "zeitzone": "Europe/Vienna", "max_alter_stunden": 24, "intervall_minuten": 15,
    "nur_mit_tags": False, "max_meldungen_pro_lauf": 25,
    "offene_artikel_tage": 7,  # nicht abgehakte Artikel nach so vielen Tagen löschen (0 = nie)
}
# Namen in config.toml sind englisch; die früheren deutschen Namen funktionieren weiter (englisch gewinnt).
# Links: Name in config.toml, rechts: Name hier im Programm.
CONFIG_NAMEN = {
    "timezone": "zeitzone", "interval_minutes": "intervall_minuten", "max_age_hours": "max_alter_stunden",
    "only_with_tags": "nur_mit_tags", "max_notifications_per_run": "max_meldungen_pro_lauf",
    "unchecked_article_days": "offene_artikel_tage", "discord_webhook_errors": "discord_webhook_fehler",
}
DASHBOARD_NAMEN = {"sync_seconds": "sync_sekunden"}
ANZEIGE_NAMEN = {intern: englisch for englisch, intern in (CONFIG_NAMEN | DASHBOARD_NAMEN).items()}


def config_name(intern: str) -> str:
    """Wie die Einstellung in config.toml heißt – für Meldungen."""
    return ANZEIGE_NAMEN.get(intern, intern)


def englische_namen(roh: dict) -> dict:
    """Englische Namen aus config.toml auf die Namen im Programm abbilden (ohne die Datei zu ändern)."""
    cfg = dict(roh)
    for englisch, intern in CONFIG_NAMEN.items():
        if englisch in cfg:
            cfg[intern] = cfg.pop(englisch)
    if isinstance(cfg.get("dashboard"), dict):
        cfg["dashboard"] = dict(cfg["dashboard"])
        for englisch, intern in DASHBOARD_NAMEN.items():
            if englisch in cfg["dashboard"]:
                cfg["dashboard"][intern] = cfg["dashboard"].pop(englisch)
    return cfg


# Diese Einstellungen übernimmt der Bot ohne Neustart, sobald config.toml gespeichert wird.
# Werte: (kleinster, größter) erlaubter Wert, None = ja/nein.
LIVE_EINSTELLUNGEN = {"intervall_minuten": (5, 240), "max_alter_stunden": (1, MAX_ALTER_GRENZE), "nur_mit_tags": None}

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
        cfg = englische_namen(tomllib.load(f))
    for k, v in STANDARD_EINSTELLUNGEN.items():
        cfg.setdefault(k, v)
    for name in LIVE_EINSTELLUNGEN:
        wert = pruefe_einstellung(name, cfg[name])
        if wert is None:
            sys.exit(f"{config_name(name)} in config.toml hat einen ungültigen Wert.")
        cfg[name] = wert
    tage = cfg["offene_artikel_tage"]
    if isinstance(tage, bool) or not isinstance(tage, int) or not 0 <= tage <= 60:
        sys.exit("unchecked_article_days in config.toml muss eine ganze Zahl von 0 bis 60 sein (0 = nie löschen).")
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
        "sync_entfernt": [],
        "pausiert": False, "intervall_minuten": None, "max_alter_stunden": None, "config_stand": {}, "sofort": False,
        "letzter_lauf": None, "naechster_lauf": None, "letztes_ergebnis": "",
        "wochentag": "", "quellen_heute": 0, "push_abos": [], "bekannt": {},
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
    """Auf der Webseite eingestellt (state) oder sonst aus config.toml."""
    return int(state.get("intervall_minuten") or cfg["intervall_minuten"])


def max_alter(cfg: dict, state: dict) -> int:
    """Wie alt ein Artikel höchstens sein darf (Stunden) – Webseite oder config.toml."""
    return int(state.get("max_alter_stunden") or cfg["max_alter_stunden"])


def alter_text(stunden: int) -> str:
    return f"{stunden // 24} Tage" if stunden >= 48 and stunden % 24 == 0 else f"{stunden} Stunden"


def plane_naechsten_lauf(state: dict, minuten: int) -> None:
    basis = datetime.fromisoformat(state["letzter_lauf"]) if state["letzter_lauf"] else jetzt_utc()
    state["naechster_lauf"] = (basis + timedelta(minutes=minuten)).isoformat()


def pruefe_einstellung(name: str, wert: object) -> int | bool | None:
    grenzen = LIVE_EINSTELLUNGEN[name]
    if grenzen is None:
        return wert if isinstance(wert, bool) else None
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    return min(grenzen[1], max(grenzen[0], int(wert)))


_config_zeitstempel: int | None = None


def uebernimm_config_aenderungen(cfg: dict, state: dict) -> None:
    """Liest config.toml neu, sobald sie gespeichert wurde – nur die LIVE_EINSTELLUNGEN.

    Wer zuletzt ändert, gewinnt: Wurde ein Wert in der Datei geändert, gilt er, auch wenn er vorher
    auf der Webseite anders eingestellt war. Eine spätere Änderung auf der Webseite gilt wieder vor
    der Datei. (Zugangsdaten, Discord usw. brauchen weiterhin einen Neustart.)
    """
    global _config_zeitstempel
    try:
        zeitstempel = CONFIG_DATEI.stat().st_mtime_ns
    except OSError:
        return
    if zeitstempel == _config_zeitstempel:
        return
    _config_zeitstempel = zeitstempel
    try:
        neu = englische_namen(tomllib.loads(CONFIG_DATEI.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        log.warning("config.toml gerade nicht lesbar (%s) – bisherige Einstellungen bleiben.", e)
        return
    zuletzt = state.setdefault("config_stand", {})
    for name in LIVE_EINSTELLUNGEN:
        wert = pruefe_einstellung(name, neu.get(name, STANDARD_EINSTELLUNGEN[name]))
        if wert is None:
            log.warning("config.toml: %s hat einen ungültigen Wert – bisheriger Wert bleibt.", config_name(name))
            continue
        cfg[name] = wert
        if name in zuletzt and zuletzt[name] != wert:
            log.info("config.toml: %s = %s übernommen (ohne Neustart).", config_name(name), wert)
            if name in state:
                state[name] = None  # Datei gilt jetzt statt der Einstellung von der Webseite
            if name == "intervall_minuten":
                plane_naechsten_lauf(state, wert)
        zuletzt[name] = wert


# --------------------------------------------------------------------------- Quellen & Tags (CSV)

def heutige_quellen(cfg: dict) -> tuple[str, list[str]]:
    wochentag = WOCHENTAGE[datetime.now(ZoneInfo(cfg["zeitzone"])).weekday()]
    quellen, _ = listen.lade_quellen(QUELLEN_DATEI)
    return wochentag, [u for t, u in quellen if t == wochentag]


def melde_ungueltige_zeilen(cfg: dict, state: dict, test: bool) -> None:
    """Von Hand eingetragene Zeilen, die der Bot nicht verwenden darf – im Log und auf der Seite zeigen."""
    _, falsche_quellen = listen.lade_quellen(QUELLEN_DATEI)
    _, falsche_tags = listen.lade_tags(TAGS_DATEI)
    for datei, zeilen in ((QUELLEN_DATEI, falsche_quellen), (TAGS_DATEI, falsche_tags)):
        for zeile in zeilen[:5]:
            inhalt = ";".join(zeile)[:200]
            melde_fehler(cfg, state, f"{datei.name}: {inhalt}",
                         f"Zeile in {datei.name} ungültig und übersprungen: {inhalt}", test, discord=False)


# --------------------------------------------------------------------------- Netzwerk

_robots: dict[str, RobotFileParser] = {}
_robots_bis: dict[str, float] = {}  # robots.txt nach einem Tag neu laden (nach Fehlschlag nach einer Stunde)


def pruefe_ziel(url: str) -> None:
    """Der Bot ruft nur öffentliche Server im Internet ab – nie deinen PC, Router oder andere Geräte
    im Heimnetz. Geprüft wird die tatsächliche IP-Adresse, auch nach jeder Weiterleitung."""
    teile = urlparse(url)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        raise AbrufFehler(f"{url}: keine gültige Webadresse")
    try:
        port = teile.port or (443 if teile.scheme == "https" else 80)
        adressen = socket.getaddrinfo(teile.hostname, port, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError, ValueError) as e:
        raise AbrufFehler(f"{url}: Adresse nicht gefunden") from e
    for *_, sockaddr in adressen:
        ip = ipaddress.ip_address(str(sockaddr[0]).split("%")[0])
        if not listen.ist_oeffentliche_ip(ip):
            raise AbrufFehler(f"{url}: zeigt auf ein privates Netz ({ip}) – aus Sicherheitsgründen gesperrt")


def sicher_abrufen(url: str, max_bytes: int = MAX_SEITE_BYTES) -> requests.Response:
    """Wie session.get, folgt Weiterleitungen aber selbst, prüft jedes Ziel und liest höchstens
    max_bytes (auch entpackt) – eine riesige oder endlose Antwort kann den PC nicht volllaufen lassen."""
    for _ in range(MAX_WEITERLEITUNGEN + 1):
        pruefe_ziel(url)
        r = session.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True)
        if not r.is_redirect:
            teile, groesse, start = [], 0, time.monotonic()
            try:
                # read1 kommt sofort mit dem zurück, was schon angekommen ist – so greift die Zeitgrenze
                # auch bei einem Server, der Byte für Byte tröpfelt. Entpackt wird dabei gleich mitgezählt.
                while stueck := r.raw.read1(65536, decode_content=True):
                    groesse += len(stueck)
                    if groesse > max_bytes:
                        raise AbrufFehler(f"{url}: Antwort zu groß (über {max_bytes // 1_000_000} MB)")
                    if time.monotonic() - start > MAX_DOWNLOAD_SEKUNDEN:
                        raise AbrufFehler(f"{url}: Antwort kommt zu langsam (über {MAX_DOWNLOAD_SEKUNDEN} s)")
                    teile.append(stueck)
            except (urllib3.exceptions.HTTPError, OSError) as e:
                raise AbrufFehler(f"{url}: Verbindung abgebrochen ({type(e).__name__})") from e
            finally:
                r.close()
            r._content, r._content_consumed = b"".join(teile), True
            return r
        r.close()
        url = urljoin(url, r.headers["location"])
    raise AbrufFehler(f"{url}: zu viele Weiterleitungen")


def erlaubt(url: str) -> bool:
    """Respektiert die robots.txt der jeweiligen Seite."""
    teile = urlparse(url)
    basis = f"{teile.scheme}://{teile.netloc}"
    rp = _robots.get(basis)
    if rp is None or time.monotonic() > _robots_bis.get(basis, 0):
        rp = RobotFileParser()
        gueltig = 24 * 3600
        try:
            r = sicher_abrufen(basis + "/robots.txt", MAX_ROBOTS_BYTES)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except (requests.RequestException, AbrufFehler):
            rp.parse([])
            gueltig = 3600
        _robots[basis], _robots_bis[basis] = rp, time.monotonic() + gueltig
    return rp.can_fetch(USER_AGENT, url)


def hole(url: str, max_bytes: int = MAX_SEITE_BYTES) -> requests.Response:
    if not erlaubt(url):
        raise AbrufFehler(f"robots.txt verbietet den Abruf von {url}")
    time.sleep(PAUSE_ZWISCHEN_ABRUFEN)
    try:
        r = sicher_abrufen(url, max_bytes)
    except requests.RequestException as e:
        raise AbrufFehler(f"{url}: {type(e).__name__}") from e
    if r.status_code != 200:
        raise AbrufFehler(f"{url}: HTTP {r.status_code}")
    return r


# --------------------------------------------------------------------------- Feeds finden & lesen

def ist_feed(inhalt: bytes, leer_ok: bool = False) -> bool:
    d = feedparser.parse(inhalt)
    return bool(d.version) and (leer_ok or bool(d.entries))


def feed_in_seite(r: requests.Response) -> str | None:
    """Ist die Adresse selbst ein Feed? Sonst <link rel=alternate> auf der Seite, sonst übliche Pfade."""
    url = r.url
    if ist_feed(r.content, leer_ok=True):  # die eingetragene Adresse ist selbst ein Feed (evtl. gerade leer)
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
    return None


# --------------------------------------------------------------------------- Ohne Feed: Sitemap, Startseite
# Reihenfolge: Feed → News-Sitemap → normale Sitemap → Startseite (Notlösung).
# Auswerten tut seiten.py; abgerufen wird nur über hole() mit allen Schutzregeln.

def sitemap_kandidaten(seiten_url: str) -> list[str]:
    teile = urlparse(seiten_url)
    basis = f"{teile.scheme}://{teile.netloc}"
    erlaubt(seiten_url)  # lädt die robots.txt, falls noch nicht geschehen
    rp = _robots.get(basis)
    aus_robots = list(rp.site_maps() or []) if rp else []
    ergebnis: list[str] = []
    for kandidat in aus_robots + [basis + p for p in seiten.SITEMAP_PFADE]:
        url = listen.pruefe_url(kandidat)
        if url and seiten.gleiche_seite(url, teile.hostname) and url not in ergebnis:
            ergebnis.append(url)
    ergebnis.sort(key=lambda u: "news" not in u.lower())  # News-Sitemaps zuerst
    return ergebnis[:8]


def lies_sitemap_url(url: str, host: str, tiefe: int = 0) -> tuple[list[dict], bool]:
    """(Einträge derselben Seite, ist News-Sitemap). Verzeichnisse: höchstens 2 Unter-Sitemaps."""
    try:
        sitemap = seiten.lies_sitemap(hole(url, MAX_SITEMAP_BYTES).content)
    except seiten.SeitenFehler as e:
        raise AbrufFehler(f"{url}: {e}") from e
    if sitemap["index"]:
        if tiefe:
            return [], False
        kinder = [(u, d) for u, d in sitemap["index"] if listen.pruefe_url(u) and seiten.gleiche_seite(u, host)]
        if any(d for _, d in kinder):
            kinder.sort(key=lambda k: ("news" not in k[0].lower(), -(k[1].timestamp() if k[1] else 0)))
        else:
            kinder = sorted(kinder[::-1], key=lambda k: "news" not in k[0].lower())  # ohne Datum: die letzten sind meist die neuesten
        # Seit über 30 Tagen unveränderte Teil-Sitemaps enthalten keine neuen Artikel – nicht abrufen
        frisch = [k for k in kinder if not k[1] or jetzt_utc() - k[1] < timedelta(days=30)] or kinder[:1]
        alle, news = [], False
        for kind, _ in frisch[:2]:
            try:
                eintraege, ist_news = lies_sitemap_url(kind, host, 1)
            except AbrufFehler:
                continue
            alle += eintraege
            news = news or ist_news
            if news:
                break  # News-Sitemap gefunden – das reicht
        return alle, news
    eintraege = [e for e in sitemap["eintraege"] if seiten.gleiche_seite(e["url"], host)]
    return eintraege, any(e["news"] for e in eintraege)


def finde_weg(quelle: str) -> dict:
    """Wie kommt der Bot an die neuen Artikel dieser Quelle?"""
    r = hole(quelle)
    jetzt = jetzt_utc().isoformat()
    feed = feed_in_seite(r)
    if feed:
        return {"art": "feed", "url": feed, "gesucht": jetzt}
    host = urlparse(r.url).hostname or ""
    normale = None
    for kandidat in sitemap_kandidaten(r.url):
        try:
            eintraege, news = lies_sitemap_url(kandidat, host)
        except AbrufFehler:
            continue
        if news:
            return {"art": "news_sitemap", "url": kandidat, "gesucht": jetzt}
        mit_datum = sum(1 for e in eintraege if e["datum"])
        if normale is None and mit_datum and mit_datum * 2 >= len(eintraege):
            normale = kandidat
    if normale:
        return {"art": "sitemap", "url": normale, "gesucht": jetzt}
    return {"art": "startseite", "url": r.url, "gesucht": jetzt}


def seitenartikel(norm: str, eintrag: dict, info: dict | None, weg: dict, jetzt: datetime,
                  grenze: timedelta, ohne_datum_ok: bool) -> dict | None:
    """Aus Sitemap-Eintrag und Angaben der Artikelseite einen Artikel wie aus einem Feed machen."""
    info = info or {}
    titel = info.get("titel") or eintrag.get("titel")
    if not titel or (weg["art"] == "startseite" and not info.get("ist_artikel")):
        return None  # Startseite: nur Seiten, die sich selbst als Artikel ausweisen
    datum = info.get("datum") or eintrag.get("datum")
    if datum is None and not ohne_datum_ok:
        return None
    if datum is not None and (jetzt - datum > grenze or datum > jetzt + timedelta(days=1)):
        return None
    schluessel = [norm]
    canonical = listen.pruefe_url(info.get("canonical", ""))
    if canonical and seiten.gleiche_seite(canonical, urlparse(norm).hostname):
        schluessel.append(normalisiere_url(canonical))
    return {
        "schluessel": list(dict.fromkeys(schluessel)),
        "url": norm,
        "titel": titel,
        "teaser": info.get("teaser", ""),
        "autor": info.get("autor", ""),
        "medium": info.get("medium") or (urlparse(norm).hostname or "").removeprefix("www."),
        "datum": datum,
        # Datum der Artikelseite > News-Sitemap (Veröffentlichung) > normale Sitemap (nur Änderungsdatum)
        "datum_art": "unbekannt" if datum is None else info.get("datum_art") if info.get("datum")
        else "veröffentlicht" if eintrag.get("news") else "aktualisiert",
        "weg": weg["art"],
    }


def artikel_von_seiten(kandidaten: list[tuple[str, dict]], state: dict, weg: dict, jetzt: datetime,
                       grenze: timedelta, ohne_datum_ok: bool) -> list[dict]:
    """Holt die Angaben neuer Artikelseiten (höchstens MAX_SEITENABRUFE). Was nicht gemeldet wird,
    kommt in "bekannt", damit der Bot die Seite nicht bei jeder Prüfung erneut abruft."""
    neue, abrufe = [], 0
    for norm, eintrag in kandidaten:
        if norm in state["gesehen"]:
            continue
        if norm in state["bekannt"]:
            state["bekannt"][norm] = jetzt.isoformat()  # noch verlinkt → nicht vergessen
            continue
        if abrufe >= MAX_SEITENABRUFE:
            break  # Rest beim nächsten Lauf
        abrufe += 1
        info = None
        try:
            r = hole(eintrag["url"])
            if "html" in r.headers.get("content-type", "").lower():
                info = seiten.lies_artikelseite(r.text, r.url)
        except AbrufFehler as e:
            log.info("Artikelseite übersprungen: %s", e)
        except Exception:  # fremde Seite mit unerwartetem Inhalt – nur diese Seite überspringen
            log.exception("Artikelseite %s nicht auswertbar – übersprungen", eintrag["url"])
        try:
            artikel = seitenartikel(norm, eintrag, info, weg, jetzt, grenze, ohne_datum_ok)
        except Exception:
            log.exception("Artikel %s nicht auswertbar – übersprungen", eintrag["url"])
            artikel = None
        if artikel:
            neue.append(artikel)
        else:
            state["bekannt"][norm] = jetzt.isoformat()
    return neue


def lies_quelle(weg: dict, state: dict, jetzt: datetime, grenze: timedelta) -> list[dict]:
    if weg["art"] == "feed":
        return [{**a, "weg": "feed"} for a in lese_artikel(hole(weg["url"]).content, weg["url"], jetzt, grenze)]
    host = urlparse(weg["url"]).hostname or ""
    if weg["art"] in ("news_sitemap", "sitemap"):
        eintraege, _ = lies_sitemap_url(weg["url"], host)
        kandidaten = []
        for e in eintraege:
            url = listen.pruefe_url(e["url"])
            if url and e["datum"] and timedelta(days=-1) <= jetzt - e["datum"] <= grenze:
                kandidaten.append((normalisiere_url(url), {**e, "url": url}))
        kandidaten.sort(key=lambda k: k[1]["datum"], reverse=True)  # neueste zuerst
        return artikel_von_seiten(list(dict(kandidaten).items()), state, weg, jetzt, grenze, ohne_datum_ok=False)

    # Startseite: neue Links erkennen. Beim allerersten Mal nur die obersten ansehen, den Rest nur merken –
    # sonst kämen auf einen Schlag alle Artikel der Startseite als „neu“.
    r = hole(weg["url"])
    links: dict[str, dict] = {}
    for url, text in seiten.artikel_links(r.text, r.url):
        sauber = listen.pruefe_url(url)
        if sauber:
            links.setdefault(normalisiere_url(sauber), {"url": sauber, "datum": None, "titel": text})
    if not links:
        raise AbrufFehler(f"{weg['url']}: weder Feed noch Sitemap, und auf der Seite sind keine Artikel-Links erkennbar")
    marke = f"basis|{weg['url']}"
    erstes_mal = marke not in state["bekannt"]
    state["bekannt"][marke] = jetzt.isoformat()
    kandidaten = list(links.items())
    if erstes_mal:
        for norm, _ in kandidaten[MAX_ERSTABRUFE_STARTSEITE:]:
            state["bekannt"].setdefault(norm, jetzt.isoformat())
        kandidaten = kandidaten[:MAX_ERSTABRUFE_STARTSEITE]
    return artikel_von_seiten(kandidaten, state, weg, jetzt, grenze, ohne_datum_ok=not erstes_mal)


def weg_fuer(quelle: str, state: dict) -> dict:
    weg = state["feeds"].get(quelle)
    if isinstance(weg, str):  # Stand aus älteren Versionen: nur Feed-Adresse
        weg = {"art": "feed", "url": weg, "gesucht": jetzt_utc().isoformat()}
    veraltet = weg and weg["art"] != "feed" and (
        jetzt_utc() - datetime.fromisoformat(weg.get("gesucht") or "2000-01-01T00:00:00+00:00")
        > timedelta(hours=WEG_NEU_SUCHEN_STUNDEN))
    if not weg or veraltet:
        neu = finde_weg(quelle)
        if not weg or neu["art"] != weg["art"]:
            log.info("%s: %s wird verwendet (%s).", quelle, WEGE[neu["art"]], neu["url"])
        weg = neu
    return weg


def normalisiere_url(url: str) -> str:
    t = urlparse(url.strip())
    query = sorted((k, v) for k, v in parse_qsl(t.query, keep_blank_values=True) if not TRACKING.match(k))
    return urlunparse((t.scheme.lower(), t.netloc.lower(), t.path or "/", "", urlencode(query), ""))


def text_aus_html(html: str, max_zeichen: int = 450) -> str:
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()
    if len(text) > max_zeichen:
        text = text[:max_zeichen].rsplit(" ", 1)[0] + " …"
    return text


def lese_artikel(feed_inhalt: bytes, feed_url: str, jetzt: datetime, grenze: timedelta) -> list[dict]:
    d = feedparser.parse(feed_inhalt)
    medium = text_aus_html(d.feed.get("title") or urlparse(feed_url).netloc, 150)
    artikel = []
    for e in d.entries:
        link = e.get("link")
        if not link:
            continue
        try:
            if e.get("published_parsed"):
                datum, datum_art = datetime(*e.published_parsed[:6], tzinfo=timezone.utc), "veröffentlicht"
            elif e.get("updated_parsed"):
                datum, datum_art = datetime(*e.updated_parsed[:6], tzinfo=timezone.utc), "aktualisiert"
            else:
                datum, datum_art = None, "unbekannt"
        except (TypeError, ValueError, OverflowError):
            datum, datum_art = None, "unbekannt"
        if datum and jetzt - datum > grenze:
            continue
        url = normalisiere_url(urljoin(feed_url, link))
        if not url.startswith(("http://", "https://")) or len(url) > 2000:
            continue
        artikel.append({
            "schluessel": [url] + ([f"id:{e.id}"] if e.get("id") else []),
            "url": url,
            "titel": text_aus_html(e.get("title", "(ohne Titel)"), 250),
            "teaser": text_aus_html(e.get("summary", ""), 1000),  # ganze Vorschau für die Details auf der Seite
            "autor": text_aus_html(e.get("author") or "", 150),
            "medium": medium,
            "datum": datum,
            "datum_art": datum_art,
        })
    return artikel


# --------------------------------------------------------------------------- Tags (per KI, siehe ki_tags.py)

def vergib_tags(cfg: dict, state: dict, artikel: list[dict], tags: dict[str, str], test: bool) -> None:
    """Setzt a["relevant"] (Themenfilter) und a["tags"] für alle Artikel. Klappt das nicht, bekommen sie
    a["tags_offen"] = True – sie werden dann trotzdem gemeldet (auch bei nur_mit_tags), damit nichts verloren geht."""
    llm = ki_tags.einstellungen(cfg)
    zu_tun = bool(tags) or bool(llm["thema"])  # ohne Tags und ohne Themenfilter gibt es nichts zu entscheiden
    for a in artikel:
        a["relevant"], a["tags"], a["belege"], a["tags_offen"] = True, [], {}, zu_tun
    if not zu_tun or not artikel:
        return
    try:
        ki_tags.TagVergabe(llm, tags).vergib(artikel)
    except ki_tags.KiFehler as e:
        melde_fehler(cfg, state, "Tags (KI)", f"Tags konnten nicht vergeben werden: {e}", test, discord=False)
    except Exception as e:  # unerwartet – die Prüfung läuft trotzdem weiter
        log.exception("Unerwarteter Fehler bei der Tag-Vergabe")
        melde_fehler(cfg, state, "Tags (KI)", f"Unerwarteter Fehler ({type(e).__name__}) – Details in newsbot.log",
                     test, discord=False)


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


def melde_fehler(cfg: dict, state: dict, quelle: str, grund: str, test: bool, discord: bool = True) -> None:
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
    if not discord:
        return
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
            log.info("Gerät hat Benachrichtigungen abbestellt oder das Abo gilt nicht mehr (%s) – entfernt.", e)
        except requests.RequestException as e:
            log.warning("Push fehlgeschlagen: %s", e)
            bleiben.append(abo)
        except (ValueError, TypeError) as e:  # kaputtes Abo – würde sonst jede Meldung blockieren
            log.warning("Ungültiges Benachrichtigungs-Abo entfernt (%s).", e)
    versucht = len(state["push_abos"])
    state["push_abos"] = bleiben
    return ok, versucht


def push_nachricht(a: dict) -> dict:
    tags = ", ".join(a["tags"][:3]) + (f" +{len(a['tags']) - 3}" if len(a["tags"]) > 3 else "")  # Platz für die Vorschau lassen
    zeile = a["medium"] + (f" – {tags}" if a["tags"] else "")
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
                except (webpush.PushAbgelaufen, ValueError, TypeError) as e:
                    state["push_abos"] = vorher
                    log.warning("Neues Gerät nimmt keine Benachrichtigungen an (%s) – nicht gespeichert.", e)
                except requests.RequestException as e:
                    log.warning("Bestätigung an neues Gerät fehlgeschlagen: %s", e)
    speichere_state(state)


# --------------------------------------------------------------------------- Durchlauf

def merke_fuer_dashboard(state: dict, a: dict, gemeldet: bool) -> None:
    # Längen wie in web/server.py (ArtikelIn) – ein zu langer Wert würde sonst die ganze Übertragung blockieren
    eintrag = {
        "url": a["url"], "titel": a["titel"][:300], "medium": a["medium"][:200], "teaser": a["teaser"][:1200],
        "autor": a["autor"][:200], "datum": a["datum"].isoformat() if a["datum"] else None,
        "datum_art": a["datum_art"], "tags": [t[:80] for t in a["tags"][:30]], "gemeldet": gemeldet, "angeschaut": False,
        "belege": {t[:80]: b[:200] for t, b in (a.get("belege") or {}).items() if t in a["tags"][:30] and b},
        "weg": a.get("weg", "feed"),
        "gefunden_um": jetzt_utc().isoformat(),
    }
    state["verlauf"] = (state["verlauf"] + [eintrag])[-VERLAUF_MAX:]
    state["sync_artikel"] = (state["sync_artikel"] + [eintrag])[-500:]


def raeume_auf(cfg: dict, state: dict) -> int:
    """Nicht abgehakte Artikel, die älter als offene_artikel_tage sind, aus dem Verlauf löschen – auch auf der
    Webseite. Abgehakte bleiben. Sie kommen nicht als neu wieder: „gesehen“ hält 14 Tage, gemeldet wird
    höchstens 7 Tage Altes."""
    tage = cfg["offene_artikel_tage"]
    if not tage:
        return 0
    grenze = jetzt_utc() - timedelta(days=tage)

    def zu_alt(e: dict) -> bool:
        if e.get("angeschaut"):
            return False
        try:
            zeit = datetime.fromisoformat(e.get("datum") or e["gefunden_um"])
        except (KeyError, TypeError, ValueError):
            return False  # ohne lesbares Datum lieber behalten
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return zeit < grenze

    weg = [e["url"] for e in state["verlauf"] if zu_alt(e)]
    if weg:
        entfernt = set(weg)
        state["verlauf"] = [e for e in state["verlauf"] if e["url"] not in entfernt]
        state["sync_artikel"] = [e for e in state["sync_artikel"] if e["url"] not in entfernt]
        state["sync_entfernt"] = list(dict.fromkeys(state["sync_entfernt"] + weg))[-1000:]
        log.info("Aufgeräumt: %d nicht angeschaute Artikel älter als %d Tage gelöscht.", len(weg), tage)
    return len(weg)


def merke_gesehen(state: dict, a: dict) -> None:
    for s in a["schluessel"]:
        state["gesehen"][s] = jetzt_utc().isoformat()


def durchlauf(cfg: dict, state: dict, test: bool = False) -> str:
    """Prüft alle heutigen Quellen. Gibt eine kurze Zusammenfassung zurück."""
    tz = ZoneInfo(cfg["zeitzone"])
    jetzt = jetzt_utc()
    grenze_alter = timedelta(hours=max_alter(cfg, state))

    if not test:
        raeume_auf(cfg, state)
    wochentag, quellen = heutige_quellen(cfg)
    tags, _ = listen.lade_tags(TAGS_DATEI)  # jedes Mal neu lesen → Änderungen gelten ohne Neustart
    melde_ungueltige_zeilen(cfg, state, test)
    state["wochentag"], state["quellen_heute"] = wochentag.capitalize(), len(quellen)
    if not quellen:
        log.info("Für %s sind keine Quellen eingetragen – nichts zu tun.", wochentag.capitalize())
        return "keine Quellen für heute eingetragen"
    log.info("%s: prüfe %d Quelle(n).", wochentag.capitalize(), len(quellen))

    grenze = (jetzt - timedelta(days=GESEHEN_BEHALTEN_TAGE)).isoformat()
    state["gesehen"] = {k: v for k, v in state["gesehen"].items() if v >= grenze}
    state["bekannt"] = {k: v for k, v in state["bekannt"].items() if v >= grenze}

    neue: list[dict] = []
    schon_im_lauf: set[str] = set()
    fehlerhaft = 0
    for nr, quelle in enumerate(quellen):
        setze_pruefung(nr, len(quellen))
        try:
            weg = weg_fuer(quelle, state)
            state["feeds"][quelle] = weg
            artikel = lies_quelle(weg, state, jetzt, grenze_alter)
        except AbrufFehler as e:
            state["feeds"].pop(quelle, None)  # beim nächsten Mal Weg neu suchen
            melde_fehler(cfg, state, quelle, str(e), test)
            fehlerhaft += 1
            continue
        except Exception as e:  # z. B. präparierte Daten einer Seite – nur diese Quelle überspringen
            log.exception("Unerwarteter Fehler bei %s", quelle)
            state["feeds"].pop(quelle, None)
            melde_fehler(cfg, state, quelle, f"Unerwarteter Fehler ({type(e).__name__}) – Quelle übersprungen, "
                                              "die anderen laufen weiter. Details in newsbot.log.", test)
            fehlerhaft += 1
            continue
        for a in artikel:
            if any(s in state["gesehen"] or s in schon_im_lauf for s in a["schluessel"]):
                continue
            schon_im_lauf.update(a["schluessel"])
            neue.append(a)

    neue.sort(key=lambda a: a["datum"] or jetzt)  # älteste zuerst
    gesendet = verarbeitet = aussortiert = 0
    for i, a in enumerate(neue):
        if gesendet >= cfg["max_meldungen_pro_lauf"]:
            log.info("Limit pro Lauf erreicht – restliche Artikel folgen beim nächsten Lauf.")
            break
        if "tags" not in a:  # Tags paketweise erst holen, wenn die Artikel an der Reihe sind –
            vergib_tags(cfg, state, neue[i:i + ki_tags.STAPEL], tags, test)  # was warten muss, kostet nichts
        if not a["relevant"]:  # nicht zum Thema (z. B. Sport auf einer Nachrichtenseite) – merken, sonst nichts
            if test:
                print(f"[aussortiert] {a['medium']} | {a['titel']}")
            else:
                merke_gesehen(state, a)
            aussortiert += 1
            verarbeitet += 1
            continue
        if cfg["nur_mit_tags"] and not a["tags"] and not a["tags_offen"]:
            if not test:
                merke_gesehen(state, a)
                merke_fuer_dashboard(state, a, gemeldet=False)  # Seite zeigt alles, Benachrichtigung nur Relevantes
            verarbeitet += 1
            continue
        if test:
            tagtext = "Tags fehlen" if a["tags_offen"] else ", ".join(a["tags"]) or "-"
            print(f"[{tagtext}] {a['medium']} | {a['titel']}\n    {a['url']}")
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

    teile = [f"{len(neue)} neu"] + ([f"{aussortiert} nicht zum Thema"] if aussortiert else []) + [f"{gesendet} gemeldet"]
    if verarbeitet < len(neue):
        teile.append(f"{len(neue) - verarbeitet} folgen später")
    if fehlerhaft:
        teile.append("1 Quelle mit Fehler" if fehlerhaft == 1 else f"{fehlerhaft} Quellen mit Fehler")
    zusammenfassung = ", ".join(teile)
    log.info("Fertig: %s.", zusammenfassung)
    return zusammenfassung


# --------------------------------------------------------------------------- Dashboard-Sync & Befehle

def baue_status(cfg: dict, state: dict) -> dict:
    llm = ki_tags.einstellungen(cfg)
    return {
        "pausiert": state["pausiert"],
        "intervall_minuten": intervall(cfg, state),
        "max_alter_stunden": max_alter(cfg, state),
        "letzter_lauf": state["letzter_lauf"],
        "naechster_lauf": state["naechster_lauf"],
        "letztes_ergebnis": state["letztes_ergebnis"][:300],
        "wochentag": state["wochentag"],
        "quellen_heute": state["quellen_heute"],
        "nur_mit_tags": bool(cfg["nur_mit_tags"]),
        "ki_modell": llm["modell"] if llm["api_key"] else None,
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
_listen_gesendet: str | None = None  # Prüfsumme der Quellen/Tags, die das Dashboard schon kennt
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


def baue_listen(state: dict) -> tuple[dict | None, str | None]:
    """Aktuelle Quellen und Tags für die Webseite – plus Prüfsumme, um nur Änderungen zu schicken."""
    try:
        quellen, _ = listen.lade_quellen(QUELLEN_DATEI)
        tags, _ = listen.lade_tags(TAGS_DATEI)
    except OSError as e:
        log.warning("Quellen/Tags nicht lesbar: %s", e)
        return None, None
    wege = {u: w["art"] for u, w in state["feeds"].items() if isinstance(w, dict) and w.get("art") in WEGE}
    daten = {"quellen": [{"wochentag": t, "url": u} for t, u in quellen],
             "tags": [{"name": n, "beschreibung": b} for n, b in tags.items()],
             "wege": [{"url": u, "art": wege[u]} for u in dict.fromkeys(u for _, u in quellen) if u in wege]}
    return daten, hashlib.sha256(json.dumps(daten, sort_keys=True).encode()).hexdigest()


def synchronisiere(cfg: dict, state: dict) -> list[dict]:
    """Schickt Status/Neues an das Dashboard und holt offene Befehle ab."""
    global _erster_sync, _listen_gesendet
    d = cfg["dashboard"]
    if not d["url"]:
        return []
    kopf = {"Authorization": f"Bearer {d['bot_token']}"}
    listen_daten, pruefsumme = baue_listen(state)
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
            "entfernt": state["sync_entfernt"],
            "snapshot": False,
        }
    neu_fuer_seite = nutzlast["snapshot"] or pruefsumme != _listen_gesendet
    nutzlast["listen"] = listen_daten if neu_fuer_seite else None
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
        if nutzlast["listen"] is not None:
            _listen_gesendet = pruefsumme
        state["sync_artikel"], state["sync_fehler"], state["sync_erledigt"], state["sync_entfernt"] = [], [], [], []
        befehle += antwort.get("befehle", [])
        geraete_geaendert = bool(antwort.get("push_aenderungen"))
        if geraete_geaendert:
            aendere_push_abos(cfg, state, antwort["push_aenderungen"])
        if antwort.get("snapshot_noetig") and not nutzlast["snapshot"]:
            # Render wurde neu gestartet und hat nichts mehr im Speicher → kompletten Verlauf schicken
            log.info("Dashboard ist leer (Neustart bei Render) – schicke kompletten Verlauf.")
            nutzlast.update(status=baue_status(cfg, state), artikel=state["verlauf"],
                            fehler=state["fehler_verlauf"], erledigt=[], snapshot=True, listen=listen_daten)
            continue
        if geraete_geaendert:
            # neue Geräteanzahl sofort auf die Seite bringen
            nutzlast.update(status=baue_status(cfg, state), artikel=[], fehler=[], erledigt=[], snapshot=False,
                            listen=None)
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
        plane_naechsten_lauf(state, wert)
        return f"Intervall auf {wert} Minuten gesetzt"
    if aktion == "max_alter":
        wert = b.get("wert")
        if not isinstance(wert, int) or isinstance(wert, bool) or not 1 <= wert <= MAX_ALTER_GRENZE:
            return "ungültiges Höchstalter – ignoriert"
        state["max_alter_stunden"] = wert
        return f"Artikel werden bis {alter_text(wert)} nach Erscheinen gemeldet"
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
    if aktion == "angeschaut":
        urls, wert = b.get("artikel"), b.get("angeschaut")
        if not isinstance(urls, list) or not isinstance(wert, bool):
            return "ungültige Angaben – ignoriert"
        ziel = {u for u in urls[:1000] if isinstance(u, str)}
        n = 0
        for eintrag in state["verlauf"]:
            if eintrag["url"] in ziel and eintrag.get("angeschaut", False) != wert:
                eintrag["angeschaut"] = wert
                n += 1
        return f"{n} Artikel als {'angeschaut' if wert else 'nicht angeschaut'} markiert"
    # Quellen und Tags: listen.py prüft jeden Wert selbst, bevor etwas in eine Datei geschrieben wird.
    try:
        if aktion in ("quellen_hinzufuegen", "quellen_entfernen", "quellen_importieren"):
            if aktion == "quellen_importieren":
                ergebnis = listen.importiere_quellen(QUELLEN_DATEI, b.get("quellen"))
            else:
                ergebnis = listen.aendere_quellen(QUELLEN_DATEI, aktion == "quellen_hinzufuegen", b.get("tage"), b.get("urls"))
            wochentag, heute = heutige_quellen(cfg)  # Statuskarte gleich richtig anzeigen
            state["wochentag"], state["quellen_heute"] = wochentag.capitalize(), len(heute)
            return ergebnis
        if aktion in ("tag_hinzufuegen", "tag_entfernen"):
            return listen.aendere_tags(TAGS_DATEI, aktion == "tag_hinzufuegen", b.get("tag"), b.get("beschreibung"))
        if aktion == "tags_importieren":
            return listen.importiere_tags(TAGS_DATEI, b.get("tags"))
    except listen.DateiGesperrt as e:
        return str(e)
    except OSError as e:
        log.error("Datei konnte nicht geändert werden: %s", e)
        return f"Datei konnte nicht geändert werden ({type(e).__name__}) – nichts geändert"
    return "ignoriert"


def verarbeite_befehle(cfg: dict, state: dict) -> None:
    for _ in range(3):  # Ergebnis (und geänderte Listen) gleich zurückmelden, statt 30 s zu warten
        befehle = synchronisiere(cfg, state)
        if not befehle:
            return
        for b in befehle:
            ergebnis = fuehre_befehl_aus(b, cfg, state)
            log.info("Befehl %s: %s", b.get("aktion"), ergebnis)
            state["sync_erledigt"].append({"id": str(b.get("id", ""))[:40], "ergebnis": ergebnis[:300]})
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


def zuruecksetzen() -> None:
    """Neuanfang ohne Datenverlust: quellen.csv, tags.csv, config.toml und vapid_privat.pem bleiben unberührt,
    aus state.json bleiben die Geräte für Benachrichtigungen, Pause/Intervall/Höchstalter, die gefundenen Wege
    und alle abgehakten (angeschauten) Artikel. Vergessen werden nur die noch nicht angeschauten."""
    if not hole_lock():
        sys.exit("Der Bot läuft gerade – erst beenden, dann zurücksetzen.")
    alt = lade_state()
    if STATE_DATEI.exists():
        sicherung = STATE_DATEI.with_name("state.vorher.json")
        STATE_DATEI.replace(sicherung)
        log.info("Bisheriger Stand gesichert als %s.", sicherung.name)
    neu = lade_state()  # leerer Stand
    for k in ("push_abos", "feeds", "pausiert", "intervall_minuten", "max_alter_stunden", "config_stand"):
        neu[k] = alt[k]
    # Abgehakte Artikel bleiben – samt „gesehen“, damit sie nicht als neu wiederkommen
    neu["verlauf"] = [e for e in alt["verlauf"] if e.get("angeschaut")]
    behalten = {e["url"] for e in neu["verlauf"]}
    neu["gesehen"] = {k: v for k, v in alt["gesehen"].items() if k in behalten}
    speichere_state(neu)
    log.info("Zurückgesetzt: %d nicht angeschaute Artikel vergessen (sie können bei der nächsten Prüfung neu "
             "kommen), %d abgehakte behalten; %d Gerät(e) für Benachrichtigungen behalten. Beim nächsten Start "
             "übernimmt die Webseite den neuen Stand.",
             len(alt["verlauf"]) - len(neu["verlauf"]), len(neu["verlauf"]), len(alt["push_abos"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Kleiner News-Bot mit eigener Webseite")
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument("--einmal", action="store_true", help="genau ein Durchlauf")
    gruppe.add_argument("--test", action="store_true", help="ein Durchlauf, nichts senden oder speichern")
    gruppe.add_argument("--prompt", action="store_true",
                        help="den kompletten Prompt an die KI in prompt-vorschau.txt schreiben (zum Kontrollieren)")
    gruppe.add_argument("--zuruecksetzen", action="store_true",
                        help="nicht angeschaute Artikel und Fehler vergessen – abgehakte Artikel, Quellen, Tags, Geräte "
                             "und Einstellungen bleiben")
    args = parser.parse_args()
    richte_logging_ein()
    if args.zuruecksetzen:
        zuruecksetzen()
        return
    cfg = lade_config()
    listen.richte_ein(QUELLEN_DATEI, TAGS_DATEI, cfg.get("tags"))
    llm = ki_tags.einstellungen(cfg)
    log.info("Tags vergibt %s.", f"{ki_tags.NAMEN[llm['anbieter']]} ({llm['modell']})" if llm["api_key"]
             else "niemand – kein API-Schlüssel in config.toml unter [llm] (Artikel kommen ohne Tags)")

    if args.prompt:
        tags, _ = listen.lade_tags(TAGS_DATEI)
        ziel = BASIS / "prompt-vorschau.txt"
        ziel.write_text(ki_tags.prompt_vorschau(llm, tags), encoding="utf-8")
        log.info("Prompt geschrieben: %s (ansehen z. B. mit: less %s)", ziel, ziel.name)
        return
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
        raeume_auf(cfg, state)  # vor dem ersten Abgleich, damit die Seite gleich aufgeräumt ist
        uebernimm_config_aenderungen(cfg, state)
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
                uebernimm_config_aenderungen(cfg, state)
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
