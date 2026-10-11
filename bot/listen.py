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


def _schreibe_quellen(datei: Path, zeilen: list[list[str]]) -> None:
    # Nach Wochentag sortiert, damit die Datei auch von Hand gut lesbar bleibt; Ungültiges ans Ende.
    zeilen.sort(key=lambda z: WOCHENTAGE.index(q[0]) if (q := _quelle(z)) else len(WOCHENTAGE))
    schreibe_csv(datei, QUELLEN_KOPF, zeilen)


def _import_text(neu: str, doppelt: int, ungueltig: int, zu_viel: int) -> str:
    teile = [neu]
    if doppelt:
        teile.append(f"{doppelt} schon vorhanden")
    if ungueltig:
        teile.append(f"{ungueltig} ungültig übersprungen")
    if zu_viel:
        teile.append(f"{zu_viel} über dem Limit")
    return ", ".join(teile)


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

    _schreibe_quellen(datei, zeilen)
    return ergebnis


def importiere_quellen(datei: Path, eintraege: object) -> str:
    """Datei-Import von der Webseite: viele Quellen auf einmal (ohne 50er-Grenze).
    Jeder Eintrag wird einzeln geprüft; Ungültiges wird übersprungen statt den Import abzubrechen."""
    if not isinstance(eintraege, list) or not 0 < len(eintraege) <= MAX_QUELLEN:
        return "ungültige Angaben – nichts geändert"
    zeilen = lies_csv(datei, QUELLEN_KOPF)
    vorhanden = {q for q in map(_quelle, zeilen) if q}
    platz = MAX_QUELLEN - len(vorhanden)
    neu: list[tuple[str, str]] = []
    doppelt = ungueltig = zu_viel = 0
    for e in eintraege:
        felder = [e.get("wochentag"), e.get("url")] if isinstance(e, dict) else []
        q = _quelle([f.strip() for f in felder]) if all(isinstance(f, str) for f in felder) else None
        if q is None:
            ungueltig += 1
        elif q in vorhanden:
            doppelt += 1
        elif len(neu) >= platz:
            zu_viel += 1
        else:
            vorhanden.add(q)
            neu.append(q)
    ergebnis = _import_text(_anzahl(len(neu), "Eintrag", "Einträge") + " importiert", doppelt, ungueltig, zu_viel)
    if not neu:
        return ergebnis + " – nichts geändert"
    zeilen += [[t.capitalize(), u] for t, u in neu]
    _schreibe_quellen(datei, zeilen)
    return ergebnis


# --------------------------------------------------------------------------- Tags

def _tag_zeile(zeile: list[str]) -> tuple[str, str] | None:
    if len(zeile) < 2:
        return None
    name, wort = pruefe_tag(zeile[0]), pruefe_wort(zeile[1])
    return (name, wort) if name and wort else None


def _gehoert_zu(zeile: list[str], name: str) -> bool:
    t = _tag_zeile(zeile)
    return t is not None and t[0].lower() == name.lower()


def _tags_aus(zeilen: list[list[str]]) -> tuple[dict[str, list[str]], list[list[str]]]:
    tags: dict[str, list[str]] = {}
    namen: dict[str, str] = {}  # klein → Schreibweise der ersten Zeile
    ungueltig: list[list[str]] = []
    for zeile in zeilen:
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


def lade_tags(datei: Path) -> tuple[dict[str, list[str]], list[list[str]]]:
    """({Tag: [Schlagwörter]} in Dateireihenfolge, ungültige Zeilen). Groß-/Kleinschreibung egal."""
    return _tags_aus(lies_csv(datei, TAGS_KOPF))


def _woerter_einfuegen(zeilen: list[list[str]], tags: dict[str, list[str]], name: str,
                       woerter: list[str]) -> tuple[str, int, int, int]:
    """Fügt bereits geprüfte Schlagwörter in die Datei-Zeilen ein (direkt hinter den Tag, damit er
    zusammenbleibt) und hält `tags` aktuell. Gibt (Schreibweise, neu, schon vorhanden, über Limit) zurück."""
    vorhanden = next((n for n in tags if n.lower() == name.lower()), None)
    if vorhanden is None and len(tags) >= MAX_TAGS:
        return name, 0, 0, len(woerter)
    name = vorhanden or name
    liste = tags.get(name, [])
    bekannt = {w.lower() for w in liste}
    neu: list[str] = []
    for w in woerter:
        if w.lower() not in bekannt:
            bekannt.add(w.lower())
            neu.append(w)
    doppelt = len(woerter) - len(neu)
    platz = max(0, MAX_WOERTER_PRO_TAG - len(liste))
    neu, zu_viel = neu[:platz], max(0, len(neu) - platz)
    if neu:
        stelle = max((i + 1 for i, z in enumerate(zeilen) if _gehoert_zu(z, name)), default=len(zeilen))
        zeilen[stelle:stelle] = [[name, w] for w in neu]
        tags[name] = liste + neu
    return name, len(neu), doppelt, zu_viel


def _saubere_woerter(woerter: list[str]) -> tuple[list[str], str | None]:
    saubere: list[str] = []
    for w in woerter:
        s = pruefe_wort(w)
        if s is None:
            return [], str(w)
        if s.lower() not in (x.lower() for x in saubere):
            saubere.append(s)
    return saubere, None


def aendere_tags(datei: Path, hinzufuegen: bool, tag: object, woerter: object) -> str:
    name = pruefe_tag(tag)
    if name is None:
        return "ungültiger Tag-Name – nichts geändert"
    woerter = [] if woerter in (None, []) and not hinzufuegen else _textliste(woerter, MAX_PRO_BEFEHL)
    if woerter is None:
        return "keine gültigen Schlagwörter – nichts geändert"
    saubere, falsch = _saubere_woerter(woerter)
    if falsch is not None:
        return f"Schlagwort nicht erlaubt: {falsch[:60]} – nichts geändert"

    zeilen = lies_csv(datei, TAGS_KOPF)
    tags, _ = _tags_aus(zeilen)
    vorhanden = next((n for n in tags if n.lower() == name.lower()), None)

    if hinzufuegen:
        if vorhanden is None and len(tags) >= MAX_TAGS:
            return f"zu viele Tags (höchstens {MAX_TAGS}) – nichts geändert"
        bekannt = {w.lower() for w in tags.get(vorhanden or "", [])}
        neu = [w for w in saubere if w.lower() not in bekannt]
        if not neu:
            return "schon vorhanden – nichts geändert"
        if len(bekannt) + len(neu) > MAX_WOERTER_PRO_TAG:
            return f"zu viele Schlagwörter (höchstens {MAX_WOERTER_PRO_TAG} pro Tag) – nichts geändert"
        name, anzahl, _, _ = _woerter_einfuegen(zeilen, tags, name, neu)
        if vorhanden:
            ergebnis = f"„{name}“: {_anzahl(anzahl, 'Schlagwort', 'Schlagwörter')} hinzugefügt"
        else:
            ergebnis = f"Tag „{name}“ mit {_anzahl(anzahl, 'Schlagwort', 'Schlagwörtern')} angelegt"
    else:
        if vorhanden is None:
            return "Tag nicht gefunden – nichts geändert"
        klein = {w.lower() for w in saubere}
        vorher = len(zeilen)
        zeilen = [z for z in zeilen if not (_gehoert_zu(z, name) and (not klein or _tag_zeile(z)[1].lower() in klein))]
        weg = vorher - len(zeilen)
        if not weg:
            return "Schlagwort nicht gefunden – nichts geändert"
        ergebnis = f"Tag „{vorhanden}“ gelöscht" if not klein else f"„{vorhanden}“: {_anzahl(weg, 'Schlagwort', 'Schlagwörter')} entfernt"

    schreibe_csv(datei, TAGS_KOPF, zeilen)
    return ergebnis


def importiere_tags(datei: Path, eintraege: object) -> str:
    """Datei-Import von der Webseite: [{"name": …, "woerter": […]}, …] ohne 50er-Grenze.
    Bestehende Tags werden ergänzt; jedes Schlagwort wird einzeln geprüft, Ungültiges übersprungen."""
    if not isinstance(eintraege, list) or not 0 < len(eintraege) <= MAX_TAGS:
        return "ungültige Angaben – nichts geändert"
    zeilen = lies_csv(datei, TAGS_KOPF)
    tags, _ = _tags_aus(zeilen)
    neue_tags = neue_woerter = doppelt = ungueltig = zu_viel = 0
    for e in eintraege:
        name = pruefe_tag(e.get("name")) if isinstance(e, dict) else None
        woerter = e.get("woerter") if isinstance(e, dict) else None
        if name is None or not isinstance(woerter, list):
            ungueltig += len(woerter) if isinstance(woerter, list) else 1
            continue
        zu_viel += max(0, len(woerter) - MAX_WOERTER_PRO_TAG)
        saubere: list[str] = []
        for w in woerter[:MAX_WOERTER_PRO_TAG]:
            s = pruefe_wort(w)
            if s is None:
                ungueltig += 1
            elif s.lower() in (x.lower() for x in saubere):
                doppelt += 1
            else:
                saubere.append(s)
        if not saubere:
            continue
        war_neu = all(n.lower() != name.lower() for n in tags)
        _, n, d, z = _woerter_einfuegen(zeilen, tags, name, saubere)
        neue_woerter, doppelt, zu_viel = neue_woerter + n, doppelt + d, zu_viel + z
        neue_tags += war_neu and n > 0
    neu = _anzahl(neue_woerter, "Schlagwort", "Schlagwörter") + " importiert"
    if neue_tags:
        neu += f" ({_anzahl(neue_tags, 'neuer Tag', 'neue Tags')})"
    ergebnis = _import_text(neu, doppelt, ungueltig, zu_viel)
    if not neue_woerter:
        return ergebnis + " – nichts geändert"
    schreibe_csv(datei, TAGS_KOPF, zeilen)
    return ergebnis
