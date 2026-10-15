"""Artikel finden, wenn eine Seite keinen RSS-Feed hat.

Hier wird nur ausgewertet – abgerufen wird ausschließlich über news_bot.hole(), also mit
robots.txt-Prüfung, Sperre fürs Heimnetz, Pause zwischen Abrufen und Größengrenze.

* Sitemaps (XML, auch .gz): News-Sitemaps nennen Titel und Veröffentlichungszeit, normale
  Sitemaps Adresse und Änderungsdatum. Gelesen mit defusedxml – präparierte XML-Dateien
  (DTDs, Entity-Tricks, externe Verweise) werden abgelehnt.
* Artikelseiten: Titel, Zusammenfassung, Autor und Datum aus den öffentlichen Angaben für
  Suchmaschinen (JSON-LD/schema.org, Open Graph, Meta-Tags). Kein Umgehen von Paywalls.
* Startseite (Notlösung): Links, die nach Artikeln aussehen.
"""
from __future__ import annotations

import json
import re
import zlib
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as SicheresXML
from defusedxml.common import DefusedXmlException

MAX_ENTPACKT = 30_000_000        # .gz-Sitemaps: Schutz vor „Zip-Bomben“
MAX_SITEMAP_EINTRAEGE = 50_000   # mehr erlaubt auch der Sitemap-Standard nicht
MAX_HTML_ZEICHEN = 3_000_000
MAX_JSONLD_ZEICHEN = 500_000
MAX_LINKS = 3_000

SITEMAP_PFADE = ["/news-sitemap.xml", "/sitemap-news.xml", "/sitemap_news.xml", "/sitemap.xml",
                 "/sitemap_index.xml", "/wp-sitemap.xml"]
ARTIKEL_TYPEN = {"article", "newsarticle", "blogposting", "reportagenewsarticle", "analysisnewsarticle",
                 "opinionnewsarticle", "reviewnewsarticle", "backgroundnewsarticle", "liveblogposting",
                 "techarticle", "report"}
KEINE_ARTIKEL = {"tag", "tags", "thema", "themen", "topic", "topics", "kategorie", "category", "categories",
                 "rubrik", "autor", "autoren", "author", "authors", "suche", "search", "login", "anmelden",
                 "registrieren", "abo", "abonnement", "impressum", "datenschutz", "privacy", "kontakt",
                 "contact", "newsletter", "page", "seite", "rss", "feed", "agb", "jobs", "karriere", "shop",
                 "wetter", "horoskop", "kreuzwortraetsel", "spiele", "games"}
DATEI_ENDUNGEN = re.compile(r"\.(jpe?g|png|gif|svg|webp|avif|ico|pdf|css|js|json|xml|gz|zip|mp3|mp4|webm)$", re.I)
ZWEITE_EBENEN = {"co", "or", "gv", "ac", "com", "org", "net", "gov", "edu"}
# Sichtbares Datum (Notlösung, wenn die Seite es Suchmaschinen nicht verrät): wo gesucht wird, relativ zur Überschrift
VOR_UEBERSCHRIFT, NACH_UEBERSCHRIFT = 400, 1500
UNSICHTBAR = {"script", "style", "noscript", "template", "svg", "nav", "footer", "aside", "form", "select", "button"}
MONATE = {"januar": 1, "jänner": 1, "jaenner": 1, "jan": 1, "january": 1, "februar": 2, "feber": 2, "feb": 2,
          "february": 2, "märz": 3, "maerz": 3, "mär": 3, "mrz": 3, "march": 3, "mar": 3, "april": 4, "apr": 4,
          "mai": 5, "may": 5, "juni": 6, "jun": 6, "june": 6, "juli": 7, "jul": 7, "july": 7, "august": 8, "aug": 8,
          "september": 9, "sept": 9, "sep": 9, "oktober": 10, "okt": 10, "october": 10, "oct": 10, "november": 11,
          "nov": 11, "dezember": 12, "dez": 12, "december": 12, "dec": 12}
_MONAT = "|".join(sorted(MONATE, key=len, reverse=True))
DATUMS_MUSTER = [  # (Regex, Reihenfolge der Gruppen: t = Tag, m = Monat, j = Jahr)
    (re.compile(r"(?<![\d.])(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\d)"), "tmj"),            # 14.10.2026
    (re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])"), "jmt"),                          # 2026-10-14
    (re.compile(rf"(?<!\d)(\d{{1,2}})\.?\s+({_MONAT})\.?\s+(\d{{4}})(?!\d)", re.I), "tmj"),     # 14. Oktober 2026
    (re.compile(rf"\b({_MONAT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)", re.I), "mtj"),  # October 14, 2026
]
ZEIT_DANACH = re.compile(r"^[\s,|/·•–—-]*(?:um|at)?\s*(\d{1,2})(?::(\d{2})|\.(\d{2})(?=\s*Uhr))\s*(Uhr|h\b|am\b|pm\b)?", re.I)
ZEIT_DAVOR = re.compile(r"(\d{1,2}):(\d{2})\s*(?:Uhr|h)?\s*[,|/·•–—-]?\s*$", re.I)
URL_DATUM = re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/")


class SeitenFehler(Exception):
    pass


# --------------------------------------------------------------------------- Hilfen

def basis_domain(host: str) -> str:
    """news.orf.at → orf.at, www.bbc.co.uk → bbc.co.uk (grob, reicht für „gehört zur selben Seite“)."""
    teile = (host or "").lower().rstrip(".").split(".")
    if len(teile) >= 3 and teile[-2] in ZWEITE_EBENEN:
        return ".".join(teile[-3:])
    return ".".join(teile[-2:])


def gleiche_seite(url: str, host: str) -> bool:
    try:
        teile = urlparse(url)
    except ValueError:
        return False
    return teile.scheme in ("http", "https") and bool(teile.hostname) and basis_domain(teile.hostname) == basis_domain(host)


def lies_datum(text: object) -> datetime | None:
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    try:
        datum = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        try:
            datum = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    try:
        if datum.tzinfo is None:
            datum = datum.replace(tzinfo=timezone.utc)
        return datum.astimezone(timezone.utc)
    except (ValueError, OverflowError):  # z. B. Jahr 1 mit Zeitzone – lässt sich nicht umrechnen
        return None


def _text(roh: object, max_zeichen: int) -> str:
    if not isinstance(roh, str):
        return ""
    text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", roh))).strip()
    if len(text) > max_zeichen:
        text = text[:max_zeichen].rsplit(" ", 1)[0] + " …"
    return text


# --------------------------------------------------------------------------- Sitemaps

def entpacke(daten: bytes) -> bytes:
    if daten[:2] != b"\x1f\x8b":
        return daten
    entpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        ergebnis = entpacker.decompress(daten, MAX_ENTPACKT)
    except zlib.error as e:
        raise SeitenFehler("Sitemap-Archiv beschädigt") from e
    if entpacker.unconsumed_tail:
        raise SeitenFehler("Sitemap entpackt zu groß")
    return ergebnis


def _name(tag: object) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _kind(element, name: str):
    return next((k for k in element if _name(k.tag) == name), None)


def _kind_text(element, name: str) -> str:
    k = _kind(element, name) if element is not None else None
    return (k.text or "").strip() if k is not None else ""


def lies_sitemap(daten: bytes) -> dict:
    """{"index": [(url, datum), …]} bei einem Sitemap-Verzeichnis, sonst
    {"eintraege": [{"url", "datum", "titel", "news"}, …]}."""
    try:
        wurzel = SicheresXML.fromstring(entpacke(daten), forbid_dtd=True)
    except (ParseError, DefusedXmlException, ValueError) as e:
        raise SeitenFehler(f"keine gültige Sitemap ({type(e).__name__})") from e
    art = _name(wurzel.tag)
    if art == "sitemapindex":
        index = []
        for sm in wurzel:
            loc = _kind_text(sm, "loc") if _name(sm.tag) == "sitemap" else ""
            if loc:
                index.append((loc, lies_datum(_kind_text(sm, "lastmod"))))
        return {"index": index[:1000], "eintraege": []}
    if art != "urlset":
        raise SeitenFehler("keine Sitemap")
    eintraege = []
    for u in wurzel:
        loc = _kind_text(u, "loc") if _name(u.tag) == "url" else ""
        if not loc:
            continue
        news = _kind(u, "news")  # Google-News-Erweiterung: Titel und Veröffentlichungszeit
        datum = lies_datum(_kind_text(news, "publication_date")) if news is not None else None
        eintraege.append({
            "url": loc,
            "datum": datum or lies_datum(_kind_text(u, "lastmod")),
            "titel": _text(_kind_text(news, "title"), 250) if news is not None else "",
            "news": news is not None,
        })
        if len(eintraege) >= MAX_SITEMAP_EINTRAEGE:
            break
    return {"index": [], "eintraege": eintraege}


# --------------------------------------------------------------------------- Artikelseiten

class _KopfLeser(HTMLParser):
    """Sammelt Meta-Tags, JSON-LD-Blöcke, <title> und den Canonical-Link. Führt nichts aus."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.jsonld: list[str] = []
        self.titel = ""
        self.canonical = ""
        self._jsonld: list[str] | None = None
        self._im_titel = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            schluessel = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower().strip()
            if schluessel and "content" in a and schluessel not in self.meta and len(self.meta) < 300:
                self.meta[schluessel] = a["content"][:3000]
        elif tag == "script" and a.get("type", "").lower().strip() == "application/ld+json":
            self._jsonld = []
        elif tag == "title":
            self._im_titel = True
        elif tag == "link" and "canonical" in a.get("rel", "").lower() and not self.canonical:
            self.canonical = a.get("href", "")[:2000]

    def handle_endtag(self, tag):
        if tag == "script" and self._jsonld is not None:
            text = "".join(self._jsonld)
            if len(text) <= MAX_JSONLD_ZEICHEN and len(self.jsonld) < 20:
                self.jsonld.append(text)
            self._jsonld = None
        elif tag == "title":
            self._im_titel = False

    def handle_data(self, data):
        if self._jsonld is not None:
            if sum(map(len, self._jsonld)) <= MAX_JSONLD_ZEICHEN:
                self._jsonld.append(data)
        elif self._im_titel and len(self.titel) < 500:
            self.titel += data


def _jsonld_artikel(bloecke: list[str]) -> dict:
    """Erstes Objekt vom Typ Article/NewsArticle/… aus den JSON-LD-Blöcken."""
    stapel: list = []
    for block in bloecke:
        try:
            stapel.append(json.loads(block))
        except (ValueError, RecursionError):
            continue
    besucht = 0
    while stapel and besucht < 2000:
        besucht += 1
        obj = stapel.pop(0)
        if isinstance(obj, list):
            stapel.extend(obj[:200])
        elif isinstance(obj, dict):
            typ = obj.get("@type")
            typen = {t.lower() for t in (typ if isinstance(typ, list) else [typ]) if isinstance(t, str)}
            if typen & ARTIKEL_TYPEN:
                return obj
            if isinstance(obj.get("@graph"), list):
                stapel.extend(obj["@graph"][:200])
    return {}


def _erster(*werte: object) -> str:
    """Erster nicht leerer Text – JSON-LD liefert manchmal Listen oder Objekte statt Text."""
    for wert in werte:
        if isinstance(wert, list):
            wert = next((w for w in wert if isinstance(w, str) and w.strip()), None)
        if isinstance(wert, str) and wert.strip():
            return wert
    return ""


def _namen(wert: object) -> str:
    if isinstance(wert, str):
        return wert
    if isinstance(wert, dict):
        return wert.get("name") if isinstance(wert.get("name"), str) else ""
    if isinstance(wert, list):
        return ", ".join(n for n in (_namen(w) for w in wert[:5]) if n)
    return ""


def lies_artikelseite(html: str, url: str) -> dict:
    """Öffentliche Angaben einer Artikelseite: titel, teaser, autor, datum, datum_art, medium,
    canonical, ist_artikel (True, wenn die Seite sich selbst als Artikel ausweist)."""
    leser = _KopfLeser()
    try:
        leser.feed(html[:MAX_HTML_ZEICHEN])
        leser.close()
    except (AssertionError, ValueError):
        pass  # kaputtes HTML – nehmen, was bis dahin gelesen wurde
    m = leser.meta
    ld = _jsonld_artikel(leser.jsonld)

    veroeffentlicht = (lies_datum(ld.get("datePublished")) or lies_datum(m.get("article:published_time"))
                       or lies_datum(m.get("og:article:published_time")) or lies_datum(m.get("date"))
                       or lies_datum(m.get("pubdate")) or lies_datum(m.get("publishdate")) or lies_datum(m.get("dc.date"))
                       or lies_datum(m.get("datepublished")))
    geaendert = lies_datum(ld.get("dateModified")) or lies_datum(m.get("article:modified_time"))
    # Nennt die Seite das Datum nur sichtbar im Text (z. B. Infopoint Security), dieses nehmen – es ist das
    # Veröffentlichungsdatum und damit besser als ein reines Änderungsdatum
    sichtbar = None if veroeffentlicht else sichtbares_datum(html, url)
    canonical = urljoin(url, leser.canonical) if leser.canonical else ""
    return {
        "titel": _text(_erster(ld.get("headline"), ld.get("name"), m.get("og:title"), m.get("twitter:title"),
                               leser.titel), 250),
        "teaser": _text(_erster(ld.get("description"), m.get("og:description"), m.get("description"),
                                m.get("twitter:description")), 1000),
        "autor": _text(_namen(ld.get("author")) or m.get("author") or m.get("article:author"), 150),
        "datum": veroeffentlicht or (None if sichtbar else geaendert),
        "datum_art": "veröffentlicht" if veroeffentlicht else "aktualisiert" if geaendert and not sichtbar else "unbekannt",
        # Ortszeit der Seite (ohne Zeitzone, außer <time> nennt eine) – news_bot rechnet sie um; nur_tag: keine Uhrzeit
        "datum_lokal": sichtbar[0] if sichtbar else None,
        "nur_tag": bool(sichtbar and sichtbar[1]),
        "medium": _text(_namen(ld.get("publisher")) or m.get("og:site_name"), 150),
        "canonical": canonical if canonical.startswith(("http://", "https://")) else "",
        "ist_artikel": bool(ld) or m.get("og:type", "").lower() == "article" or "article:published_time" in m,
    }


# --------------------------------------------------------------------------- Sichtbares Datum (Notlösung)

class _TextLeser(HTMLParser):
    """Sichtbarer Text der Seite, Lage der ersten Überschrift <h1> darin und <time datetime="…">-Angaben."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self.laenge = 0
        self.h1: tuple[int, int] | None = None
        self.zeiten: list[tuple[int, str, bool]] = []  # (Stelle, datetime-Wert, als Veröffentlichung markiert)
        self._unsichtbar = 0
        self._h1_start: int | None = None

    def handle_starttag(self, tag, attrs):
        if tag in UNSICHTBAR:
            self._unsichtbar += 1
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        wert = a.get("datetime") or (a.get("content") if a.get("itemprop", "").lower() == "datepublished" else "")
        if wert and len(self.zeiten) < 200 and not self._unsichtbar:
            markiert = a.get("itemprop", "").lower() == "datepublished" or bool(
                re.search(r"publish|entry-date|post-date|veroeffentlicht|article-date", a.get("class", ""), re.I))
            self.zeiten.append((self.laenge, wert[:60], markiert))
        if tag == "h1" and self.h1 is None and self._h1_start is None:
            self._h1_start = self.laenge
        if tag in ("p", "div", "br", "li", "td", "h1", "h2", "h3", "span", "time"):
            self._dazu(" ")

    def handle_endtag(self, tag):
        if tag in UNSICHTBAR:
            self._unsichtbar = max(0, self._unsichtbar - 1)
        elif tag == "h1" and self._h1_start is not None and self.h1 is None:
            self.h1 = (self._h1_start, self.laenge)
        if tag in ("p", "div", "li", "td", "h1", "h2", "h3", "span", "time"):
            self._dazu(" ")

    def handle_data(self, data):
        if not self._unsichtbar:
            self._dazu(data)

    def _dazu(self, text: str) -> None:
        if self.laenge < MAX_HTML_ZEICHEN:
            self.teile.append(text)
            self.laenge += len(text)


def _gueltig(j: int, m: int, t: int, std: int = 0, minute: int = 0) -> datetime | None:
    try:
        return datetime(j, m, t, std, minute) if 1990 <= j <= 2100 else None
    except ValueError:
        return None


def _zeit(text: str, start: int, ende: int) -> tuple[int, int] | None:
    """Uhrzeit direkt hinter (oder vor) dem Datum: „14.10.2026, 10:15 Uhr“, „um 9.30 Uhr“, „10:15 | 14.10.2026“."""
    if m := ZEIT_DANACH.match(text[ende:ende + 30]):
        std, minute = int(m.group(1)), int(m.group(2) or m.group(3))
        zusatz = (m.group(4) or "").lower()
        if zusatz == "pm" and std < 12:
            std += 12
        elif zusatz == "am" and std == 12:
            std = 0
        if std < 24 and minute < 60:
            return std, minute
    if m := ZEIT_DAVOR.search(text[max(0, start - 25):start]):
        std, minute = int(m.group(1)), int(m.group(2))
        if std < 24 and minute < 60:
            return std, minute
    return None


def sichtbares_datum(html: str, url: str = "") -> tuple[datetime, bool] | None:
    """Veröffentlichungsdatum, das nur im sichtbaren Text steht – meist in Ortszeit ohne Zeitzone, dazu True, wenn nur der
    Tag bekannt ist (keine Uhrzeit). Gesucht wird nahe der Hauptüberschrift, damit nicht das Datum eines anderen
    Artikels aus der Seitenleiste oder ein Termin im Text erwischt wird. Notfalls aus der Adresse (/2026/10/14/)."""
    leser = _TextLeser()
    try:
        leser.feed(html[:MAX_HTML_ZEICHEN])
        leser.close()
    except (AssertionError, ValueError):
        pass
    text = "".join(leser.teile)
    if leser.h1:
        anfang, ende = leser.h1
        von, bis = max(0, anfang - VOR_UEBERSCHRIFT), ende + NACH_UEBERSCHRIFT

        def abstand(stelle_von: int, stelle_bis: int) -> tuple[bool, int]:
            """Was hinter der Überschrift steht, kommt zuerst (davor steht oft das heutige Datum im Seitenkopf)."""
            return (True, anfang - stelle_bis) if stelle_bis <= anfang else (False, max(0, stelle_von - ende))

        # 1. <time datetime="…"> nahe der Überschrift (als Veröffentlichung markierte zuerst)
        zeiten = sorted((not markiert, abstand(stelle, stelle), wert) for stelle, wert, markiert in leser.zeiten
                        if von <= stelle <= bis or markiert)
        for _, _, wert in zeiten:
            if ergebnis := _datum_aus_attribut(wert):
                return ergebnis
        # 2. Datum im Text – das der Überschrift nächste
        treffer = []
        for muster, reihenfolge in DATUMS_MUSTER:
            for m in muster.finditer(text, von, min(len(text), bis)):
                werte = dict(zip(reihenfolge, m.groups()))
                monat = int(werte["m"]) if werte["m"].isdigit() else MONATE.get(werte["m"].lower().rstrip("."))
                if monat and (tag := _gueltig(int(werte["j"]), monat, int(werte["t"]))):
                    treffer.append((abstand(m.start(), m.end()), m.start(), m.end(), tag))
        if treffer:
            _, start, ende_treffer, tag = min(treffer, key=lambda x: (x[0], x[1]))
            if uhr := _zeit(text, start, ende_treffer):
                return tag.replace(hour=uhr[0], minute=uhr[1]), False
            return tag, True
    # 3. Datum in der Adresse
    if m := URL_DATUM.search(urlparse(url).path):
        if tag := _gueltig(int(m.group(1)), int(m.group(2)), int(m.group(3))):
            return tag, True
    return None


def _datum_aus_attribut(wert: str) -> tuple[datetime, bool] | None:
    """datetime-Wert eines <time>-Elements: nur Tag („2026-10-14“), Ortszeit oder mit Zeitzone."""
    wert = wert.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", wert):
            tag = date.fromisoformat(wert)
            return (datetime(tag.year, tag.month, tag.day), True) if 1990 <= tag.year <= 2100 else None
        d = datetime.fromisoformat(wert.replace("Z", "+00:00"))  # mit Zeitzone bleibt sie dran, sonst Ortszeit
    except (ValueError, OverflowError):
        return None
    return (d, False) if 1990 <= d.year <= 2100 else None


# --------------------------------------------------------------------------- Startseite (Notlösung)

class _LinkLeser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and len(self.links) < MAX_LINKS:
            self._href = dict(attrs).get("href") or None
            self._text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href[:2000], " ".join("".join(self._text).split())[:300]))
            self._href = None

    def handle_data(self, data):
        if self._href is not None and sum(map(len, self._text)) < 600:
            self._text.append(data)


def sieht_nach_artikel_aus(url: str, text: str) -> bool:
    pfad = urlparse(url).path.lower()
    teile = [t for t in pfad.split("/") if t]
    if not teile or DATEI_ENDUNGEN.search(pfad) or any(t in KEINE_ARTIKEL for t in teile):
        return False
    slug = teile[-1]
    struktur = len(teile) >= 2 or slug.count("-") >= 3
    hinweis = len(text) >= 20 or slug.count("-") >= 3 or re.search(r"\d{4,}", pfad) is not None
    return struktur and hinweis


def artikel_links(html: str, seiten_url: str) -> list[tuple[str, str]]:
    """Links der Seite, die nach Artikeln derselben Seite aussehen – in Seitenreihenfolge, ohne Doppelte."""
    leser = _LinkLeser()
    try:
        leser.feed(html[:MAX_HTML_ZEICHEN])
        leser.close()
    except (AssertionError, ValueError):
        pass
    host = urlparse(seiten_url).hostname or ""
    gesehen: set[str] = set()
    ergebnis = []
    for href, text in leser.links:
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        try:
            url = urljoin(seiten_url, href.strip()).split("#", 1)[0]
        except ValueError:
            continue
        if url in gesehen or not gleiche_seite(url, host) or not sieht_nach_artikel_aus(url, text):
            continue
        gesehen.add(url)
        ergebnis.append((url, text))
    return ergebnis
