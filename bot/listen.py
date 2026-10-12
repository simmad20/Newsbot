"""Quellen und Tags als CSV-Dateien – lesen, streng prüfen und sicher ändern.

    quellen.csv   Wochentag;URL          eine Zeile pro Quelle und Wochentag
    tags.csv      Tag;Beschreibung       eine Zeile pro Tag (Beschreibung freiwillig)

Welche Tags zu einem Artikel passen, entscheidet die KI (ki_tags.py) – sie wählt nur aus
den Tags in tags.csv. Die Beschreibung hilft ihr dabei (z. B. der Pfad im Tag-Baum).

Beide Dateien kannst du mit Excel oder einem Texteditor bearbeiten. Zusätzlich
ändert der Bot sie auf Befehl der Webseite. Alles, was von außen kommt, wird hier
geprüft, bevor es in eine Datei gelangt:

* Adressen: nur http(s), keine Zugangsdaten in der Adresse, keine Adressen aus dem
  eigenen Netz (localhost, 192.168.x.x, Router …).
* Tag-Namen: nur Buchstaben, Ziffern und wenige Satzzeichen, am Anfang ein Buchstabe,
  eine Ziffer oder eine Klammer. Beschreibungen: normaler Text ohne Steuerzeichen; Zeichen
  wie = + - @ am Anfang werden entfernt. Eine Zelle kann also nie mit = + - @ anfangen –
  Excel würde so etwas sonst als Formel ausführen.

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
TAGS_KOPF = ["Tag", "Beschreibung"]

MAX_URL_LAENGE = 500
MAX_QUELLEN = 700
MAX_TAGS = 1000
MAX_TAG_LAENGE = 80
MAX_BESCHREIBUNG = 300
MAX_PRO_BEFEHL = 50

# Erstes Zeichen Buchstabe, Ziffer oder Klammer (z. B. "[S]1 Cyber") → keine Excel-Formeln, keine Steuerzeichen.
TAG_MUSTER = re.compile(r"(?:[^\W_]|[\[(])[\w .,:&/'+()\[\]-]{0,%d}" % (MAX_TAG_LAENGE - 1))
FORMEL_ANFANG = "=+-@"
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


def pruefe_beschreibung(wert: object) -> str | None:
    """Freier Text für die KI. Leer ist erlaubt; = + - @ am Anfang werden entfernt (Excel-Formeln)."""
    if wert is None:
        return ""
    if not isinstance(wert, str):
        return None
    text = " ".join(wert.split()).lstrip(FORMEL_ANFANG + " ")
    if len(text) > MAX_BESCHREIBUNG or not text.isprintable():
        return None
    return text


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
    """Legt fehlende Dateien an. Tags aus einer älteren config.toml werden einmalig übernommen,
    eine tags.csv im alten Format (Tag;Schlagwort) wird auf Tag;Beschreibung umgestellt."""
    if not quellen_datei.exists():
        schreibe_csv(quellen_datei, QUELLEN_KOPF, [])
        log.info("%s angelegt – trage Quellen dort oder über die Webseite ein.", quellen_datei.name)
    if not tags_datei.exists():
        zeilen = []
        for tag in alte_tags or {}:
            name = pruefe_tag(tag)
            if name and all(z[0].lower() != name.lower() for z in zeilen):
                zeilen.append([name, ""])
            elif not name:
                log.warning("Tag %r aus config.toml nicht übernommen (ungültige Zeichen).", tag)
        schreibe_csv(tags_datei, TAGS_KOPF, zeilen)
        if zeilen:
            log.info("Tags aus config.toml nach %s übernommen – ab jetzt gilt nur noch die CSV.", tags_datei.name)
    elif _altes_tag_format(tags_datei):
        sicherung = tags_datei.with_name("tags-schlagwoerter-alt.csv")
        if not sicherung.exists():
            sicherung.write_bytes(tags_datei.read_bytes())
        namen: list[str] = []
        for zeile in lies_csv(tags_datei, ["Tag", "Schlagwort"]):
            name = pruefe_tag(zeile[0]) if zeile else None
            if name and all(n.lower() != name.lower() for n in namen) and len(namen) < MAX_TAGS:
                namen.append(name)
        schreibe_csv(tags_datei, TAGS_KOPF, [[n, ""] for n in namen])
        log.info("%s auf das neue Format umgestellt: %d Tags, Schlagwörter entfernt (die KI vergibt die Tags). "
                 "Alte Datei gesichert als %s.", tags_datei.name, len(namen), sicherung.name)


def _altes_tag_format(datei: Path) -> bool:
    roh = datei.read_bytes()[:500].decode("utf-8-sig", errors="replace")
    kopf = roh.split("\n", 1)[0].replace(",", ";").split(";")
    return len(kopf) >= 2 and kopf[1].strip().strip('"').lower() in ("schlagwort", "schlagwörter", "schlagwoerter")


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
    name = pruefe_tag(zeile[0]) if zeile else None
    beschreibung = pruefe_beschreibung(zeile[1] if len(zeile) > 1 else "")
    if not name or beschreibung is None:
        return None
    return name, "" if beschreibung.lower() == name.lower() else beschreibung  # oberste Ebene im Tag-Baum: Pfad = Name


def _verbinde(alt: str, neu: str) -> str:
    """Zwei Beschreibungen desselben Tags (z. B. gleicher Name an zwei Stellen im Tag-Baum)."""
    if not neu or neu.lower() in alt.lower():
        return alt
    if not alt:
        return neu
    zusammen = f"{alt} | {neu}"
    return zusammen if len(zusammen) <= MAX_BESCHREIBUNG else alt


def _tags_aus(zeilen: list[list[str]]) -> tuple[dict[str, str], list[list[str]]]:
    tags: dict[str, str] = {}
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
            tags[name] = ""
        tags[name] = _verbinde(tags[name], t[1])
    return tags, ungueltig


def lade_tags(datei: Path) -> tuple[dict[str, str], list[list[str]]]:
    """({Tag: Beschreibung} in Dateireihenfolge, ungültige Zeilen). Groß-/Kleinschreibung egal."""
    return _tags_aus(lies_csv(datei, TAGS_KOPF))


def _schreibe_tags(datei: Path, tags: dict[str, str], ungueltig: list[list[str]]) -> None:
    # Ungültige Zeilen bleiben am Ende stehen – der Bot löscht nichts, was du von Hand eingetragen hast.
    schreibe_csv(datei, TAGS_KOPF, [[n, b] for n, b in tags.items()] + ungueltig)


def _vorhanden(tags: dict[str, str], name: str) -> str | None:
    return next((n for n in tags if n.lower() == name.lower()), None)


def aendere_tags(datei: Path, hinzufuegen: bool, tag: object, beschreibung: object = None) -> str:
    """Befehl von der Webseite: Tag anlegen bzw. Beschreibung ändern, oder Tag löschen."""
    name = pruefe_tag(tag)
    if name is None:
        return "ungültiger Tag-Name – nichts geändert"
    text = pruefe_beschreibung(beschreibung)
    if text is None:
        return f"Beschreibung nicht erlaubt (höchstens {MAX_BESCHREIBUNG} Zeichen, keine Steuerzeichen) – nichts geändert"

    tags, ungueltig = lade_tags(datei)
    vorhanden = _vorhanden(tags, name)
    if hinzufuegen:
        if vorhanden is None:
            if len(tags) >= MAX_TAGS:
                return f"zu viele Tags (höchstens {MAX_TAGS}) – nichts geändert"
            tags[name] = text
            ergebnis = f"Tag „{name}“ angelegt"
        elif tags[vorhanden] == text:
            return "schon vorhanden – nichts geändert"
        else:
            tags[vorhanden] = text
            ergebnis = f"„{vorhanden}“: Beschreibung {'geändert' if text else 'entfernt'}"
    else:
        if vorhanden is None:
            return "Tag nicht gefunden – nichts geändert"
        del tags[vorhanden]
        ergebnis = f"Tag „{vorhanden}“ gelöscht"

    _schreibe_tags(datei, tags, ungueltig)
    return ergebnis


def importiere_tags(datei: Path, eintraege: object) -> str:
    """Datei-Import von der Webseite: [{"name": …, "beschreibung": …}, …] ohne 50er-Grenze.
    Neue Tags werden angehängt, bei vorhandenen gilt die Beschreibung aus der Datei (falls angegeben).
    Jeder Eintrag wird einzeln geprüft; Ungültiges wird übersprungen."""
    if not isinstance(eintraege, list) or not 0 < len(eintraege) <= MAX_TAGS:
        return "ungültige Angaben – nichts geändert"
    tags, ungueltige_zeilen = lade_tags(datei)
    aus_diesem_import: set[str] = set()
    neu = geaendert = doppelt = ungueltig = zu_viel = 0
    for e in eintraege:
        name = pruefe_tag(e.get("name")) if isinstance(e, dict) else None
        text = pruefe_beschreibung(e.get("beschreibung")) if isinstance(e, dict) else None
        if name is None or text is None:
            ungueltig += 1
            continue
        vorhanden = _vorhanden(tags, name)
        if vorhanden is None:
            if len(tags) >= MAX_TAGS:
                zu_viel += 1
                continue
            tags[name] = text
            neu += 1
        elif vorhanden in aus_diesem_import:  # gleicher Name zweimal in der Datei → Beschreibungen verbinden
            tags[vorhanden] = _verbinde(tags[vorhanden], text)
            doppelt += 1
        elif text and tags[vorhanden] != text:
            tags[vorhanden] = text
            geaendert += 1
        else:
            doppelt += 1
        aus_diesem_import.add(vorhanden or name)
    ergebnis = _anzahl(neu, "Tag", "Tags") + " importiert"
    if geaendert:
        ergebnis += f", {_anzahl(geaendert, 'Beschreibung', 'Beschreibungen')} aktualisiert"
    ergebnis = _import_text(ergebnis, doppelt, ungueltig, zu_viel)
    if not neu and not geaendert:
        return ergebnis + " – nichts geändert"
    _schreibe_tags(datei, tags, ungueltige_zeilen)
    return ergebnis
