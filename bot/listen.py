"""Quellen und Tags als CSV-Dateien – lesen, streng prüfen und sicher ändern.

    quellen.csv   Wochentag;URL          eine Zeile pro Quelle und Wochentag
    tags.csv      Tag;Schlagwort         eine Zeile pro Schlagwort

Beide Dateien kannst du mit Excel oder einem Texteditor bearbeiten. Zusätzlich
ändert der Bot sie auf Befehl der Webseite. Alles, was von außen kommt, wird hier
geprüft, bevor es in eine Datei gelangt:

* Adressen: nur http(s), keine Zugangsdaten in der Adresse, keine Adressen aus dem
  eigenen Netz (localhost, 192.168.x.x, Router …).
* Tags und Schlagwörter: nur Buchstaben, Ziffern und wenige Satzzeichen, und sie
  beginnen immer mit einem Buchstaben oder einer Ziffer. Eine Zelle kann also nie
  mit = + - @ anfangen – Excel würde so etwas sonst als Formel ausführen.

Zeilen, die du von Hand einträgst und die diese Regeln nicht erfüllen, ignoriert der
Bot (mit Hinweis im Log und auf der Webseite), löscht sie aber nicht.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("newsbot")

WOCHENTAGE = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
QUELLEN_KOPF = ["Wochentag", "URL"]
TAGS_KOPF = ["Tag", "Schlagwort"]

MAX_URL_LAENGE = 500
MAX_QUELLEN = 700
MAX_TAGS = 100
MAX_WOERTER_PRO_TAG = 100
MAX_PRO_BEFEHL = 50

# Erstes Zeichen immer Buchstabe/Ziffer → keine Excel-Formeln, keine Steuerzeichen.
TAG_MUSTER = re.compile(r"[^\W_][\w .&/'+-]{0,39}")
WORT_MUSTER = re.compile(r"[^\W_][\w .&/'+-]{0,58}\*?")
DOMAIN_MUSTER = re.compile(r"[\w-]+(\.[\w-]+)+")
INTERNE_NAMEN = ("localhost", ".localhost", ".local", ".lan", ".home", ".internal", ".intranet", ".corp", ".arpa")
VERBOTENE_ZEICHEN = set('\\"<>`{}|^')


class DateiGesperrt(Exception):
    """Die Datei ist gerade in einem anderen Programm (meist Excel) geöffnet."""


# --------------------------------------------------------------------------- Prüfen

def ist_oeffentliche_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def pruefe_url(wert: object) -> str | None:
    """Gibt die bereinigte Adresse zurück oder None, wenn sie nicht erlaubt ist."""
    if not isinstance(wert, str):
        return None
    url = wert.strip()
    if not url or len(url) > MAX_URL_LAENGE:
        return None
    if any(c.isspace() or not c.isprintable() or c in VERBOTENE_ZEICHEN for c in url):
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        teile = urlparse(url)
        host = teile.hostname or ""
        teile.port  # wirft ValueError bei kaputtem Port
    except ValueError:
        return None
    if teile.scheme not in ("http", "https") or not host or "@" in teile.netloc:
        return None
    try:
        return url if ist_oeffentliche_ip(ipaddress.ip_address(host)) else None
    except ValueError:
        pass  # keine IP-Adresse, sondern ein Name
    if re.fullmatch(r"[\d.]+", host) or not DOMAIN_MUSTER.fullmatch(host):
        return None  # z. B. "127.1" – sieht aus wie eine Zahl, ist aber keine gültige Adresse
    if host == "localhost" or host.endswith(INTERNE_NAMEN):
        return None
    return url


def pruefe_tag(wert: object) -> str | None:
    if not isinstance(wert, str):
        return None
    name = " ".join(wert.split())
    return name if TAG_MUSTER.fullmatch(name) else None


def pruefe_wort(wert: object) -> str | None:
    if not isinstance(wert, str):
        return None
    wort = " ".join(wert.split())
    return wort if WORT_MUSTER.fullmatch(wort) else None


def _anzahl(n: int, eins: str, viele: str) -> str:
    return f"{n} {eins if n == 1 else viele}"


def _textliste(wert: object, maximal: int) -> list[str] | None:
    if not isinstance(wert, list) or not 0 < len(wert) <= maximal or not all(isinstance(x, str) for x in wert):
        return None
    return wert


# --------------------------------------------------------------------------- CSV lesen & schreiben

def lies_csv(datei: Path, kopf: list[str]) -> list[list[str]]:
    """Alle Datenzeilen ohne Kopfzeile und Leerzeilen. Fehlt die Datei, ist die Liste leer."""
    if not datei.exists():
        return []
    roh = datei.read_bytes()
    try:
        text = roh.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = roh.decode("cp1252", errors="replace")  # Excel speichert „CSV (Trennzeichen-getrennt)“ so
    erste = text.split("\n", 1)[0]
    trenner = "," if "," in erste and ";" not in erste else ";"
    zeilen = []
    for zeile in csv.reader(io.StringIO(text), delimiter=trenner):
        zellen = [z.strip() for z in zeile]
        while zellen and not zellen[-1]:
            zellen.pop()
        if zellen:
            zeilen.append(zellen)
    if zeilen and zeilen[0][0].lower() == kopf[0].lower():
        zeilen.pop(0)
    return zeilen


def schreibe_csv(datei: Path, kopf: list[str], zeilen: list[list[str]]) -> None:
    """Atomar schreiben: erst in eine Hilfsdatei, dann austauschen – nie eine halbe Datei."""
    tmp = datei.with_name(datei.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:  # mit BOM, damit Excel Umlaute richtig zeigt
        w = csv.writer(f, delimiter=";", lineterminator="\r\n")
        w.writerow(kopf)
        w.writerows(zeilen)
    try:
        tmp.replace(datei)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise DateiGesperrt(f"{datei.name} ist gerade geöffnet (z. B. in Excel) – bitte schließen und erneut senden") from e


def richte_ein(quellen_datei: Path, tags_datei: Path, alte_tags: dict | None) -> None:
    """Legt fehlende Dateien an. Tags aus einer älteren config.toml werden einmalig übernommen."""
    if not quellen_datei.exists():
        schreibe_csv(quellen_datei, QUELLEN_KOPF, [])
        log.info("%s angelegt – trage Quellen dort oder über die Webseite ein.", quellen_datei.name)
    if not tags_datei.exists():
        zeilen = []
        for tag, woerter in (alte_tags or {}).items():
            name = pruefe_tag(tag)
            for w in woerter if isinstance(woerter, list) else []:
                wort = pruefe_wort(w)
                if name and wort:
                    zeilen.append([name, wort])
                else:
                    log.warning("Tag %r / Schlagwort %r aus config.toml nicht übernommen (ungültige Zeichen).", tag, w)
        schreibe_csv(tags_datei, TAGS_KOPF, zeilen)
        if zeilen:
            log.info("Tags aus config.toml nach %s übernommen – ab jetzt gilt nur noch die CSV.", tags_datei.name)


# --------------------------------------------------------------------------- Quellen

def _quelle(zeile: list[str]) -> tuple[str, str] | None:
    if len(zeile) < 2 or zeile[0].lower() not in WOCHENTAGE:
        return None
    url = pruefe_url(zeile[1])
    return (zeile[0].lower(), url) if url else None


def lade_quellen(datei: Path) -> tuple[list[tuple[str, str]], list[list[str]]]:
    """(gültige Quellen als (wochentag, url), ungültige Zeilen)."""
    gueltig: list[tuple[str, str]] = []
    ungueltig: list[list[str]] = []
    for zeile in lies_csv(datei, QUELLEN_KOPF):
        q = _quelle(zeile)
        if q is None:
            ungueltig.append(zeile)
        elif q not in gueltig and len(gueltig) < MAX_QUELLEN:
            gueltig.append(q)
    return gueltig, ungueltig


def aendere_quellen(datei: Path, hinzufuegen: bool, tage: object, urls: object) -> str:
    """Befehl von der Webseite. Prüft alles selbst – der Bot vertraut der Webseite nicht blind."""
    tage = _textliste(tage, 7)
    urls = _textliste(urls, MAX_PRO_BEFEHL)
    if not tage or not urls or any(t not in WOCHENTAGE for t in tage):
        return "ungültige Angaben – nichts geändert"
    saubere = []
    for u in urls:
        s = pruefe_url(u)
        if s is None:
            return f"Adresse nicht erlaubt: {str(u)[:80]} – nichts geändert"
        if s not in saubere:
            saubere.append(s)
    ziele = [(t, u) for t in WOCHENTAGE if t in tage for u in saubere]

    zeilen = lies_csv(datei, QUELLEN_KOPF)
    vorhanden = {q for q in map(_quelle, zeilen) if q}
    if hinzufuegen:
        neu = [z for z in ziele if z not in vorhanden]
        if not neu:
            return "schon eingetragen – nichts geändert"
        if len(vorhanden) + len(neu) > MAX_QUELLEN:
            return f"zu viele Quellen (höchstens {MAX_QUELLEN}) – nichts geändert"
        zeilen += [[t.capitalize(), u] for t, u in neu]
        ergebnis = _anzahl(len(neu), "Eintrag", "Einträge") + " eingetragen"
        if len(neu) < len(ziele):
            ergebnis += f", {len(ziele) - len(neu)} waren schon da"
    else:
        vorher = len(zeilen)
        zeilen = [z for z in zeilen if _quelle(z) not in ziele]
        weg = vorher - len(zeilen)
        if not weg:
            return "nicht gefunden – nichts geändert"
        ergebnis = _anzahl(weg, "Eintrag", "Einträge") + " entfernt"

    # Nach Wochentag sortiert, damit die Datei auch von Hand gut lesbar bleibt; Ungültiges ans Ende.
    zeilen.sort(key=lambda z: WOCHENTAGE.index(q[0]) if (q := _quelle(z)) else len(WOCHENTAGE))
    schreibe_csv(datei, QUELLEN_KOPF, zeilen)
    return ergebnis


# --------------------------------------------------------------------------- Tags

def _tag_zeile(zeile: list[str]) -> tuple[str, str] | None:
    if len(zeile) < 2:
        return None
    name, wort = pruefe_tag(zeile[0]), pruefe_wort(zeile[1])
    return (name, wort) if name and wort else None


def lade_tags(datei: Path) -> tuple[dict[str, list[str]], list[list[str]]]:
    """({Tag: [Schlagwörter]} in Dateireihenfolge, ungültige Zeilen). Groß-/Kleinschreibung egal."""
    tags: dict[str, list[str]] = {}
    namen: dict[str, str] = {}  # klein → Schreibweise der ersten Zeile
    ungueltig: list[list[str]] = []
    for zeile in lies_csv(datei, TAGS_KOPF):
        t = _tag_zeile(zeile)
        if t is None:
            ungueltig.append(zeile)
            continue
        name = namen.get(t[0].lower())
        if name is None:
            if len(tags) >= MAX_TAGS:
                continue
            name = namen[t[0].lower()] = t[0]
            tags[name] = []
        if t[1].lower() not in (w.lower() for w in tags[name]) and len(tags[name]) < MAX_WOERTER_PRO_TAG:
            tags[name].append(t[1])
    return tags, ungueltig


def aendere_tags(datei: Path, hinzufuegen: bool, tag: object, woerter: object) -> str:
    name = pruefe_tag(tag)
    if name is None:
        return "ungültiger Tag-Name – nichts geändert"
    woerter = [] if woerter in (None, []) and not hinzufuegen else _textliste(woerter, MAX_PRO_BEFEHL)
    if woerter is None:
        return "keine gültigen Schlagwörter – nichts geändert"
    saubere = []
    for w in woerter:
        s = pruefe_wort(w)
        if s is None:
            return f"Schlagwort nicht erlaubt: {str(w)[:60]} – nichts geändert"
        if s.lower() not in (x.lower() for x in saubere):
            saubere.append(s)

    zeilen = lies_csv(datei, TAGS_KOPF)
    tags, _ = lade_tags(datei)
    vorhanden = next((n for n in tags if n.lower() == name.lower()), None)
    gehoert_zum_tag = lambda z: (t := _tag_zeile(z)) is not None and t[0].lower() == name.lower()  # noqa: E731

    if hinzufuegen:
        if vorhanden is None and len(tags) >= MAX_TAGS:
            return f"zu viele Tags (höchstens {MAX_TAGS}) – nichts geändert"
        name = vorhanden or name
        bekannt = {w.lower() for w in tags.get(name, [])}
        neu = [w for w in saubere if w.lower() not in bekannt]
        if not neu:
            return "schon vorhanden – nichts geändert"
        if len(bekannt) + len(neu) > MAX_WOERTER_PRO_TAG:
            return f"zu viele Schlagwörter (höchstens {MAX_WOERTER_PRO_TAG} pro Tag) – nichts geändert"
        # Direkt hinter die letzte Zeile des Tags, damit er in der Datei zusammenbleibt
        stelle = max((i + 1 for i, z in enumerate(zeilen) if gehoert_zum_tag(z)), default=len(zeilen))
        zeilen[stelle:stelle] = [[name, w] for w in neu]
        if vorhanden:
            ergebnis = f"„{name}“: {_anzahl(len(neu), 'Schlagwort', 'Schlagwörter')} hinzugefügt"
        else:
            ergebnis = f"Tag „{name}“ mit {_anzahl(len(neu), 'Schlagwort', 'Schlagwörtern')} angelegt"
    else:
        if vorhanden is None:
            return "Tag nicht gefunden – nichts geändert"
        klein = {w.lower() for w in saubere}
        vorher = len(zeilen)
        zeilen = [z for z in zeilen if not (gehoert_zum_tag(z) and (not klein or _tag_zeile(z)[1].lower() in klein))]
        weg = vorher - len(zeilen)
        if not weg:
            return "Schlagwort nicht gefunden – nichts geändert"
        ergebnis = f"Tag „{vorhanden}“ gelöscht" if not klein else f"„{vorhanden}“: {_anzahl(weg, 'Schlagwort', 'Schlagwörter')} entfernt"

    schreibe_csv(datei, TAGS_KOPF, zeilen)
    return ergebnis
