"use strict";

const AKTUALISIEREN_MS = 10000;
const PRO_SEITE = 30;
const ZONE = "Europe/Vienna";
const fmtZeit = new Intl.DateTimeFormat("de-AT", { timeZone: ZONE, hour: "2-digit", minute: "2-digit" });
const fmtTag = new Intl.DateTimeFormat("de-AT", { timeZone: ZONE, day: "2-digit", month: "2-digit" });
const fmtTagLang = new Intl.DateTimeFormat("de-AT", { timeZone: ZONE, weekday: "long", day: "numeric", month: "long" });
const fmtTagSchluessel = new Intl.DateTimeFormat("en-CA", { timeZone: ZONE });

const AKTIONS_NAMEN = {
  jetzt_pruefen: "Jetzt prüfen",
  pausieren: "Pausieren",
  fortsetzen: "Fortsetzen",
  intervall: "Intervall ändern",
  max_alter: "Höchstalter ändern",
  testnachricht: "Testbenachrichtigung",
};
const TAGE = [
  ["montag", "Montag", "Mo"], ["dienstag", "Dienstag", "Di"], ["mittwoch", "Mittwoch", "Mi"],
  ["donnerstag", "Donnerstag", "Do"], ["freitag", "Freitag", "Fr"], ["samstag", "Samstag", "Sa"],
  ["sonntag", "Sonntag", "So"],
];
const WERKTAGE = TAGE.slice(0, 5).map(([k]) => k);
const fmtWochentag = new Intl.DateTimeFormat("de-AT", { timeZone: ZONE, weekday: "long" });
const heutigerTag = () => fmtWochentag.format(new Date()).toLowerCase();
// Gleiche Regeln wie auf dem Server und im Bot (die prüfen trotzdem noch einmal selbst)
const TAG_MUSTER = /^(?:[\p{L}\p{N}]|[[(])[\p{L}\p{N}_ .,:&\/'+()[\]-]{0,79}$/u;
const MAX_BESCHREIBUNG = 300;
const ZUSTAND_NAMEN = { offen: "wartet auf den Bot", abgeholt: "wird ausgeführt" };

let daten = null;
let sichtbar = PRO_SEITE;  // wie viele Artikel gerade angezeigt werden

// "neu seit deinem letzten Besuch" – merkt sich nur dieser Browser
const GESEHEN_SCHLUESSEL = "newsbot_gesehen_bis";
function ladeGesehenBis() { try { return localStorage.getItem(GESEHEN_SCHLUESSEL); } catch { return null; } }
function speichereGesehenBis(wert) { try { localStorage.setItem(GESEHEN_SCHLUESSEL, wert); } catch { /* egal */ } }
let gesehenBis = ladeGesehenBis();

function neuestesFundDatum() {
  return daten.artikel.reduce((m, a) => (Date.parse(a.gefunden_um) > Date.parse(m) ? a.gefunden_um : m), new Date(0).toISOString());
}
function istNeu(a) { return gesehenBis !== null && Date.parse(a.gefunden_um) > Date.parse(gesehenBis); }

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...kinder) {
  const knoten = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") knoten.className = v;
    else knoten.setAttribute(k, v);
  }
  for (const kind of kinder) {
    if (kind == null || kind === false) continue;
    knoten.append(kind instanceof Node ? kind : document.createTextNode(String(kind)));
  }
  return knoten;
}

function sichereUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

function tagText(datum) {
  const heute = fmtTagSchluessel.format(new Date());
  const gestern = fmtTagSchluessel.format(new Date(Date.now() - 864e5));
  const tag = fmtTagSchluessel.format(datum);
  if (tag === heute) return "heute";
  if (tag === gestern) return "gestern";
  return fmtTag.format(datum);
}

function vorText(sekunden) {
  if (sekunden < 60) return `vor ${sekunden} Sek.`;
  const min = Math.round(sekunden / 60);
  if (min < 90) return `vor ${min} Min.`;
  const std = Math.round(min / 60);
  if (std < 36) return `vor ${std} Std.`;
  return `vor ${Math.round(std / 24)} Tagen`;
}

function uhrzeit(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d) ? null : fmtZeit.format(d);
}

function anzahl(n, eins, viele) { return `${n} ${n === 1 ? eins : viele}`; }
function kurzUrl(url) { return url.replace(/^https?:\/\//, "").replace(/\/$/, ""); }
function einRaum(text) { return text.split(/\s+/).filter(Boolean).join(" "); }

function tageText(tage) {
  const gewaehlt = TAGE.filter(([k]) => tage.includes(k));
  if (gewaehlt.length === 7) return "jeden Tag";
  if (gewaehlt.length === 5 && gewaehlt.every(([k]) => WERKTAGE.includes(k))) return "Mo–Fr";
  return gewaehlt.length === 1 ? gewaehlt[0][1] : gewaehlt.map(([, , kurz]) => kurz).join(", ");
}

function befehlName(b) {
  const urls = b.urls || [];
  const was = urls.length === 1 ? kurzUrl(urls[0]) : anzahl(urls.length, "Quelle", "Quellen");
  switch (b.aktion) {
    case "intervall": return `Intervall auf ${b.wert} Min.`;
    case "max_alter": return `Artikel bis ${alterText(b.wert)} alt melden`;
    case "quellen_importieren": return `Import: ${anzahl(b.anzahl_quellen || 0, "Eintrag", "Einträge")} für Quellen`;
    case "tags_importieren": return `Import: ${anzahl(b.anzahl_tags || 0, "Tag", "Tags")}`;
    case "quellen_hinzufuegen": return `${was} für ${tageText(b.tage || [])} hinzufügen`;
    case "quellen_entfernen": return `${was} bei ${tageText(b.tage || [])} entfernen`;
    case "tag_hinzufuegen": return `Tag „${b.tag}“ speichern`;
    case "tag_entfernen": return `Tag „${b.tag}“ löschen`;
    default: return AKTIONS_NAMEN[b.aktion] || b.aktion;
  }
}

function alterText(stunden) {
  return stunden >= 48 && stunden % 24 === 0 ? `${stunden / 24} Tage` : `${stunden} Std.`;
}

function zeitpunktVor(sekunden) {
  const d = new Date(Date.now() - sekunden * 1000);
  return `${tagText(d) === "heute" ? "" : `${tagText(d)}, `}${fmtZeit.format(d)}`;
}

// ---------------------------------------------------------------- Laden

async function laden() {
  try {
    const r = await fetch("/api/daten", { credentials: "same-origin" });
    if (r.status === 401) { location.reload(); return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    daten = await r.json();
    zeichneAlles();
  } catch (e) {
    setzeStatus("offline", "Seite nicht erreichbar", "Keine Verbindung", "Die Webseite antwortet gerade nicht.",
      "Sie wacht vermutlich gerade auf, das dauert bis zu einer Minute. Neuer Versuch läuft automatisch.", "");
  }
}

function zeichneAlles() {
  if (gesehenBis === null && daten.artikel.length) {
    gesehenBis = neuestesFundDatum();  // erster Besuch: nichts als neu markieren
    speichereGesehenBis(gesehenBis);
  }
  zeichneSignal();
  zeichnePush();
  zeichneFilterOptionen();
  zeichneTicker();
  zeichneQuellen();
  zeichneTags();
  zeichneFehler();
  zeichneBefehle();
}

// ---------------------------------------------------------------- Status

function setzeStatus(zustand, titel, kurz, zeile1, zeile2, zeile3) {
  $("status-punkt").className = `punkt punkt-${zustand}`;
  $("kopf-punkt").className = `punkt punkt-${zustand}`;
  $("status-karte").dataset.zustand = zustand;
  $("signal-titel").textContent = titel;
  $("kopf-text").textContent = kurz;
  $("status-zeile1").textContent = zeile1;
  $("status-zeile2").textContent = zeile2;
  $("status-zeile3").textContent = zeile3;
}

function setzeAuswahl(auswahl, zahl, text) {
  if (document.activeElement === auswahl) return;  // nicht umstellen, während jemand gerade auswählt
  const wert = String(zahl);
  if (![...auswahl.options].some((o) => o.value === wert)) auswahl.append(el("option", { value: wert }, text(zahl)));
  auswahl.value = wert;
}

function zeichneSignal() {
  const { online, letzter_kontakt_vor_sekunden: vor, status, pruefung, beendet } = daten.bot;
  const pauseKnopf = $("pause-knopf");

  if (!status) {
    setzeStatus("warten", "Nicht verbunden", "Nicht verbunden", "Starte den Bot auf deinem PC.",
      "Er meldet sich innerhalb einer Minute hier.", "");
    return;
  }

  pauseKnopf.dataset.aktion = status.pausiert ? "fortsetzen" : "pausieren";
  pauseKnopf.textContent = status.pausiert ? "Fortsetzen" : "Pausieren";
  setzeAuswahl($("intervall"), status.intervall_minuten, (w) => `${w} Min.`);
  setzeAuswahl($("max-alter"), status.max_alter_stunden || 24, (w) => `${alterText(w)} alt`);

  const zuletzt = uhrzeit(status.letzter_lauf);
  const letzte = zuletzt ? `Letzte Prüfung ${zuletzt}: ${status.letztes_ergebnis || "kein Ergebnis"}` : "Noch keine Prüfung seit dem Start";
  const heute = `Heute (${status.wochentag || "?"}): ${status.quellen_heute === 1 ? "1 Quelle" : `${status.quellen_heute} Quellen`}`;
  const spaeter = "Befehle werden ausgeführt, sobald der Bot wieder läuft.";

  if (beendet && beendet.grund === "fehler") {
    setzeStatus("fehler", "Abgestürzt", "Abgestürzt", `Um ${zeitpunktVor(beendet.vor_sekunden)}: ${beendet.text || "unbekannter Fehler"}`,
      "Details stehen in newsbot.log auf deinem PC. Starte den Bot neu.", spaeter);
  } else if (beendet) {
    setzeStatus("offline", "Beendet", "Beendet", `Der Bot wurde um ${zeitpunktVor(beendet.vor_sekunden)} beendet.`,
      beendet.text || "", spaeter);
  } else if (!online) {
    setzeStatus("fehler", "Keine Verbindung", "Keine Verbindung",
      `Letztes Lebenszeichen um ${zeitpunktVor(vor)} (${vorText(vor)}).`,
      "Der Bot ist abgestürzt, wurde hart beendet oder der PC ist aus bzw. offline.", spaeter);
  } else if (pruefung) {
    const fortschritt = pruefung.gesamt ? `Quelle ${Math.min(pruefung.fertig + 1, pruefung.gesamt)} von ${pruefung.gesamt}` : "";
    setzeStatus("pruefen", "Prüft gerade", `Prüft ${pruefung.gesamt ? `${pruefung.fertig + 1}/${pruefung.gesamt}` : "…"}`,
      fortschritt || "Quellen werden abgerufen.", letzte, heute);
  } else if (status.pausiert) {
    setzeStatus("pausiert", "Pausiert", "Pausiert", "Es wird nicht automatisch geprüft.", letzte, heute);
  } else {
    const naechste = uhrzeit(status.naechster_lauf);
    setzeStatus("laeuft", "Läuft", naechste ? `Läuft · nächste ${naechste}` : "Läuft",
      naechste ? `Nächste Prüfung um ${naechste}` : "Prüfung startet gleich", letzte, heute);
  }
}

// ---------------------------------------------------------------- Reiter

const REITER = ["artikel", "quellen", "tags", "fehler", "befehle"];

function zeigeReiter(name, fokus = false) {
  for (const r of REITER) {
    const aktiv = r === name;
    const knopf = $(`reiter-${r}`);
    knopf.setAttribute("aria-selected", String(aktiv));
    knopf.tabIndex = aktiv ? 0 : -1;
    $(`bereich-${r}`).hidden = !aktiv;
    if (aktiv && fokus) knopf.focus();
  }
}

REITER.forEach((r, i) => {
  const knopf = $(`reiter-${r}`);
  knopf.addEventListener("click", () => zeigeReiter(r));
  knopf.addEventListener("keydown", (e) => {
    const schritt = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!schritt) return;
    e.preventDefault();
    zeigeReiter(REITER[(i + schritt + REITER.length) % REITER.length], true);
  });
});

// ---------------------------------------------------------------- Artikel

const fmtDatumLang = new Intl.DateTimeFormat("de-AT", {
  timeZone: ZONE, weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtTagKurz = new Intl.DateTimeFormat("de-AT", { timeZone: ZONE, weekday: "short", day: "2-digit", month: "2-digit" });
const QUELL_FARBEN = 8;
const ANSICHT_SCHLUESSEL = "newsbot_artikel_ansicht";
let ansicht = (() => { try { return localStorage.getItem(ANSICHT_SCHLUESSEL) === "quelle" ? "quelle" : "zeit"; } catch { return "zeit"; } })();
let farbeVon = new Map();          // Medium → Farbnummer, damit jede Quelle überall gleich aussieht
const offeneArtikel = new Set();   // aufgeklappte Details bleiben beim Aktualisieren offen
const abhakenLokal = new Map();    // url → angeschaut: gilt sofort, bis der Server denselben Stand meldet
let letzteArtikelAnsicht = "";

const WEG_TEXT = { feed: "RSS-Feed", news_sitemap: "News-Sitemap", sitemap: "Sitemap", startseite: "Startseite (Seite ohne Feed)" };

function datumLang(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? `${fmtDatumLang.format(d)} Uhr` : null;
}

function vorZeit(iso) {
  const sekunden = Math.round((Date.now() - Date.parse(iso)) / 1000);
  return Number.isFinite(sekunden) && sekunden >= 0 ? vorText(sekunden) : null;
}

function hostVon(url) {
  try { return new URL(url).host.replace(/^www\./, ""); } catch { return ""; }
}

function kurzId(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.codePointAt(0)) >>> 0;
  return h.toString(36);
}

function zeichneFilterOptionen() {
  fuelleAuswahl($("filter-tag"), "Alle Tags", daten.artikel.flatMap((a) => a.tags));
  fuelleAuswahl($("filter-medium"), "Alle Quellen", daten.artikel.map((a) => a.medium));
  const medien = [...new Set(daten.artikel.map((a) => a.medium))].sort((a, b) => a.localeCompare(b, "de"));
  farbeVon = new Map(medien.map((m, i) => [m, i % QUELL_FARBEN]));
}

function fuelleAuswahl(auswahl, leerText, werte) {
  const aktuell = auswahl.value;
  const eindeutig = [...new Set(werte)].sort((a, b) => a.localeCompare(b, "de"));
  auswahl.replaceChildren(el("option", { value: "" }, leerText), ...eindeutig.map((w) => el("option", { value: w }, w)));
  auswahl.value = eindeutig.includes(aktuell) ? aktuell : "";
}

const zeitpunkt = (a) => Date.parse(a.datum || a.gefunden_um) || 0;
const istAngeschaut = (a) => (abhakenLokal.has(a.url) ? abhakenLokal.get(a.url) : Boolean(a.angeschaut));

function gefilterteArtikel() {
  const suche = $("suche").value.trim().toLowerCase();
  const tag = $("filter-tag").value;
  const medium = $("filter-medium").value;
  const nurGemeldet = $("nur-gemeldet").checked;
  const gelesen = $("filter-gelesen").value;
  return [...daten.artikel].sort((x, y) => zeitpunkt(y) - zeitpunkt(x)).filter((a) =>
    (!gelesen || (gelesen === "angeschaut") === istAngeschaut(a)) &&
    (!tag || a.tags.includes(tag)) &&
    (!medium || a.medium === medium) &&
    (!nurGemeldet || a.gemeldet) &&
    (!suche || `${a.titel} ${a.teaser} ${a.autor} ${a.medium}`.toLowerCase().includes(suche))
  );
}

function trennerText(ms) {
  const d = new Date(ms);
  const kurz = tagText(d);
  const lang = fmtTagLang.format(d);
  return kurz === "heute" ? `Heute · ${lang}` : kurz === "gestern" ? `Gestern · ${lang}` : lang;
}

function zeichneMedienLeiste() {
  const zaehler = new Map();
  for (const a of daten.artikel) zaehler.set(a.medium, (zaehler.get(a.medium) || 0) + 1);
  const aktiv = $("filter-medium").value;
  const leiste = $("medien-leiste");
  leiste.hidden = zaehler.size < 2;
  leiste.replaceChildren(...[...zaehler].sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0], "de")).map(([m, n]) =>
    el("li", {}, el("button", { type: "button", class: `medium-chip farbe-${farbeVon.get(m) ?? 0}`, "aria-pressed": String(aktiv === m),
      title: aktiv === m ? "Filter aufheben" : `Nur ${m} anzeigen`, "data-medium": m, "data-fokus": `m|${m}` },
      el("span", { class: "farb-punkt", "aria-hidden": "true" }), el("span", { class: "medium-name" }, m), el("span", { class: "zahl" }, String(n))))));
}

function zeichneTicker() {
  const liste = $("ticker");
  const mehr = $("mehr");
  for (const [url, wert] of abhakenLokal) {  // Server hat den Haken übernommen → lokale Vorgabe nicht mehr nötig
    if (daten.artikel.some((a) => a.url === url && Boolean(a.angeschaut) === wert)) abhakenLokal.delete(url);
  }
  const artikel = gefilterteArtikel();
  const gesamt = daten.artikel.length;
  const neuZahl = daten.artikel.filter(istNeu).length;
  const offenZahl = daten.artikel.filter((a) => !istAngeschaut(a)).length;
  const gelesen = $("filter-gelesen").value;

  $("zahl-artikel").textContent = offenZahl ? String(offenZahl) : "";
  document.title = neuZahl ? `(${neuZahl}) News-Bot` : "News-Bot";
  $("anzahl").textContent = !gesamt ? ""
    : `${artikel.length} von ${gesamt} Artikeln angezeigt · ${offenZahl} nicht angeschaut`
      + (neuZahl ? ` · ${neuZahl} neu seit deinem letzten Besuch` : "");
  const alleKnopf = $("alle-abhaken");
  alleKnopf.hidden = gelesen !== "offen" || !artikel.length;
  alleKnopf.textContent = `Alle ${artikel.length} als angeschaut markieren`;
  document.querySelectorAll("[data-ansicht]").forEach((k) => k.setAttribute("aria-pressed", String(k.dataset.ansicht === ansicht)));

  // Nur neu zeichnen, wenn sich etwas geändert hat (sonst springen Fokus und Auswahl alle 10 Sekunden)
  const schluessel = JSON.stringify([daten.artikel.map((a) => [a.url, a.gemeldet, a.tags, istAngeschaut(a)]), artikel.length, sichtbar, ansicht, gesehenBis, gelesen,
    $("filter-medium").value, [...offeneArtikel], fmtTagSchluessel.format(new Date()), Math.floor(Date.now() / 60000),
    daten.bot.status ? [daten.bot.status.quellen_heute, daten.bot.status.nur_mit_tags] : null,
    $("suche").value, $("filter-tag").value, $("nur-gemeldet").checked]);
  if (schluessel === letzteArtikelAnsicht) return;
  letzteArtikelAnsicht = schluessel;

  zeichneMedienLeiste();
  mehr.hidden = true;
  if (!gesamt || !artikel.length) {
    const text = gesamt && gelesen === "offen" && !offenZahl ? "Alles angeschaut – neue Artikel erscheinen hier, sobald der Bot sie findet."
      : gesamt ? "Kein Artikel passt zu diesen Filtern."
      : !daten.bot.status ? "Sobald der Bot verbunden ist, erscheinen hier die gefundenen Artikel."
      : daten.bot.status.quellen_heute ? "Noch keine Artikel. Mit „Jetzt prüfen“ startest du sofort eine Prüfung."
      : "Noch keine Artikel. Für heute sind keine Quellen eingetragen – im Reiter „Quellen“ kannst du welche hinzufügen.";
    liste.replaceChildren(el("p", { class: "leer" }, text));
    return;
  }

  // Nach Tagen gruppieren; in der Ansicht „Nach Quelle“ innerhalb jedes Tages nach Medium
  const tage = [];
  for (const a of artikel.slice(0, sichtbar)) {
    const ms = zeitpunkt(a);
    const k = fmtTagSchluessel.format(new Date(ms));
    if (!tage.length || tage.at(-1).k !== k) tage.push({ k, ms, artikel: [] });
    tage.at(-1).artikel.push(a);
  }
  const teile = [];
  for (const t of tage) {
    teile.push(el("h2", { class: "tag-trenner" }, trennerText(t.ms),
      el("span", { class: "trenner-zahl" }, anzahl(t.artikel.length, "Artikel", "Artikel"))));
    if (ansicht === "zeit") {
      teile.push(el("ol", { class: "artikel-liste" }, ...t.artikel.map((a) => artikelKarte(a, false))));
      continue;
    }
    const gruppen = new Map();  // Reihenfolge: Quelle mit dem neuesten Artikel zuerst
    for (const a of t.artikel) (gruppen.get(a.medium) || gruppen.set(a.medium, []).get(a.medium)).push(a);
    for (const [m, liste_] of gruppen) {
      teile.push(el("section", { class: `quelle-gruppe farbe-${farbeVon.get(m) ?? 0}`, "aria-label": `${m}: ${anzahl(liste_.length, "Artikel", "Artikel")}` },
        el("header", { class: "quelle-kopf" },
          el("span", { class: "farb-punkt", "aria-hidden": "true" }),
          el("h3", {}, m),
          el("span", { class: "zahl" }, String(liste_.length)),
          el("span", { class: "quelle-host" }, hostVon(liste_[0].url))),
        el("ol", { class: "artikel-liste kompakt" }, ...liste_.map((a) => artikelKarte(a, true)))));
    }
  }
  zeichneErhaltend(liste, () => liste.replaceChildren(...teile));

  const rest = artikel.length - sichtbar;
  if (rest > 0) {
    mehr.hidden = false;
    mehr.textContent = `Weitere ${Math.min(rest, PRO_SEITE)} anzeigen (noch ${rest})`;
  }
}

function detailFeld(name, ...wert) {
  return [el("dt", {}, name), el("dd", {}, ...wert)];
}

// datum_art → [Marke auf der Karte, Erklärung]
const DATUM_HINWEIS = {
  aktualisiert: ["aktualisiert", "Der Feed nennt nur das Aktualisierungsdatum"],
  "nur Datum": ["Uhrzeit ≈", "Die Seite nennt nur den Tag – die Uhrzeit ist die, zu der der Bot den Artikel gefunden hat"],
  Fundzeit: ["Fundzeit", "Die Seite nennt kein Datum – angezeigt wird, wann der Bot den Artikel gefunden hat"],
};

const TAGS_OFFEN = "Tags fehlen – die KI hat für diesen Artikel nicht geantwortet (nachholen: python news_bot.py --retag)";

// Autor: nur natürliche Personen. Nennt die Quelle eine Redaktion, Agentur, Website o. Ä., gilt er als ungenannt.
function autorHinweis(a) {
  return a.autor_angabe
    ? `Die Quelle nennt „${a.autor_angabe}“ – keine natürliche Person`
    : "Die Quelle nennt keinen Autor";
}

function artikelKarte(a, kompakt) {
  const d = a.datum ? new Date(a.datum) : null;
  const datumOk = d && !isNaN(d);
  const url = sichereUrl(a.url);
  const offen = offeneArtikel.has(a.url);
  const id = `artikel-${kurzId(a.url)}`;
  const status = daten.bot.status;

  const zeit = el("div", { class: "artikel-zeit" }, ...(datumOk
    ? [el("span", { class: "zeit-wert" }, fmtZeit.format(d)), el("span", { class: "zeit-datum" }, fmtTagKurz.format(d))]
    : [el("span", { class: "zeit-wert unsicher" }, "?"), el("span", { class: "zeit-datum" }, "kein Datum")]));

  const marken = el("div", { class: "artikel-marken" },
    kompakt ? null : el("span", { class: "medium-marke" }, el("span", { class: "farb-punkt", "aria-hidden": "true" }), a.medium),
    istNeu(a) ? el("span", { class: "neu-marke" }, "neu") : null,
    a.gemeldet ? el("span", { class: "gemeldet-marke", title: "Benachrichtigung wurde gesendet" }, "gemeldet") : null,
    datumOk && DATUM_HINWEIS[a.datum_art] ? el("span", { class: "hinweis-marke", title: DATUM_HINWEIS[a.datum_art][1] }, DATUM_HINWEIS[a.datum_art][0]) : null,
    a.autor ? null : el("span", { class: "hinweis-marke achtung", title: autorHinweis(a) }, "Autor ungenannt"),
    a.tags_offen ? el("span", { class: "hinweis-marke achtung", title: TAGS_OFFEN }, "Tags fehlen") : null);

  const titel = el("h3", { class: "artikel-titel" }, url
    ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, a.titel)
    : a.titel);

  const meta = [a.autor ? `von ${a.autor}` : null, datumOk ? vorZeit(a.datum) : null, kompakt ? null : hostVon(a.url)].filter(Boolean);

  let benachrichtigung = "gesendet";
  if (!a.gemeldet) {
    benachrichtigung = status && status.nur_mit_tags && !a.tags.length
      ? "nicht gesendet – es werden nur Artikel mit Tags gemeldet"
      : "nicht gesendet";
  }

  const details = offen ? el("div", { class: "artikel-details", id },
    el("dl", { class: "details-raster" },
      ...detailFeld("Quelle", a.medium, el("span", { class: "leise" }, ` · ${hostVon(a.url)}`)),
      ...detailFeld("Autor", ...(a.autor ? [a.autor]
        : [el("span", { class: "warnung-text" }, "ungenannt"), el("span", { class: "leise" }, ` · ${autorHinweis(a)}`)])),
      ...detailFeld(a.datum_art === "aktualisiert" ? "Aktualisiert" : "Veröffentlicht", ...(datumOk
        ? [`${datumLang(a.datum)} (${vorZeit(a.datum) || "gerade eben"})`,
          DATUM_HINWEIS[a.datum_art] ? el("span", { class: "leise" }, ` · ${DATUM_HINWEIS[a.datum_art][1]}`) : null]
        : [el("span", { class: "warnung-text" }, "Der Feed nennt kein Datum – bitte im Artikel prüfen")])),
      ...detailFeld("Gefunden", datumLang(a.gefunden_um) || "–",
        a.weg && a.weg !== "feed" ? el("span", { class: "leise" }, ` · über ${WEG_TEXT[a.weg] || a.weg}`) : null),
      ...detailFeld("Benachrichtigung", benachrichtigung),
      ...detailFeld("Tags", a.tags.length
        ? el("ul", { class: "tags" }, ...a.tags.map((t) => el("li", {}, tagKnopf(t, a, "d"))))
        : a.tags_offen ? el("span", { class: "warnung-text" }, TAGS_OFFEN) : el("span", { class: "leise" }, "keine"))),
    el("div", { class: "zusammenfassung" },
      el("h4", {}, "Zusammenfassung laut Feed"),
      el("p", {}, a.teaser || "Der Feed liefert keinen Vorschautext – bitte den Artikel öffnen.")),
    url ? el("div", { class: "details-aktionen" },
      el("a", { class: "knopf haupt mit-symbol", href: url, target: "_blank", rel: "noopener noreferrer" },
        el("span", {}, "Artikel öffnen"), symbol(ICON.extern, 16)),
      el("button", { type: "button", class: "knopf", "data-kopieren": url, "data-fokus": `k|${a.url}` }, "Link kopieren"),
      a.tags.length ? el("button", { type: "button", class: "knopf", "data-kopieren": a.tags.join("\n"), "data-fokus": `kt|${a.url}`,
        title: "Alle Tags dieses Artikels, einer pro Zeile" }, "Alle Tags kopieren") : null) : null) : null;

  const angeschaut = istAngeschaut(a);
  const abhaken = el("button", { type: "button", class: `abhaken${angeschaut ? " an" : ""}`, "aria-pressed": String(angeschaut),
    title: angeschaut ? "Wieder als nicht angeschaut markieren" : "Als angeschaut markieren – dann ist er unter „Nicht angeschaut“ ausgeblendet",
    "data-abhaken": a.url, "data-fokus": `h|${a.url}` }, symbol(ICON.haken, 16), el("span", {}, angeschaut ? "Angeschaut" : "Abhaken"));

  const knopfAttr = { type: "button", class: "details-knopf", "aria-expanded": String(offen), "data-details": a.url, "data-fokus": `d|${a.url}` };
  if (offen) knopfAttr["aria-controls"] = id;

  return el("li", { class: `artikel farbe-${farbeVon.get(a.medium) ?? 0}${offen ? " offen" : ""}${istNeu(a) ? " ist-neu" : ""}${angeschaut ? " angeschaut" : ""}` },
    zeit,
    el("div", { class: "artikel-inhalt" },
      marken.childElementCount ? marken : null,
      titel,
      meta.length ? el("p", { class: "artikel-meta" }, meta.join(" · ")) : null,
      a.teaser && !offen ? el("p", { class: "teaser" }, a.teaser) : null,
      el("div", { class: "artikel-fuss" },
        a.tags.length && !offen ? el("ul", { class: "tags", "aria-label": "Tags" }, ...a.tags.slice(0, 6).map((t) => el("li", {}, tagKnopf(t, a, "k"))),
          a.tags.length > 6 ? el("li", { class: "tags-mehr", title: "Alle Tags unter „Details“" }, `+${a.tags.length - 6}`) : null) : null,
        abhaken,
        el("button", knopfAttr, offen ? "Weniger" : "Details", symbol(ICON.pfeil, 16))),
      details));
}

$("mehr").addEventListener("click", () => {
  sichtbar += PRO_SEITE;
  zeichneTicker();
});

/** Abhaken (oder zurücknehmen): sofort sichtbar, dann an Server und Bot. Bei Fehler wieder zurück. */
async function setzeAngeschaut(urls, wert, text) {
  const rueck = $("artikel-rueck");
  for (const u of urls) abhakenLokal.set(u, wert);
  zeichneTicker();
  try {
    for (let i = 0; i < urls.length; i += 400) {
      await schickeBefehl({ aktion: "angeschaut", artikel: urls.slice(i, i + 400), angeschaut: wert });
    }
    rueck.replaceChildren(text, " ",
      el("button", { type: "button", class: "link-knopf", "data-rueckgaengig": wert ? "1" : "0", "data-urls": JSON.stringify(urls) }, "Rückgängig"));
    laden();
  } catch (e) {
    for (const u of urls) abhakenLokal.delete(u);
    zeichneTicker();
    rueck.textContent = `Nicht gespeichert: ${e.message}`;
  }
}

$("artikel-rueck").addEventListener("click", (e) => {
  const knopf = e.target.closest("button[data-rueckgaengig]");
  if (!knopf) return;
  const urls = JSON.parse(knopf.dataset.urls);
  setzeAngeschaut(urls, knopf.dataset.rueckgaengig !== "1", "Zurückgenommen.");
});

$("alle-abhaken").addEventListener("click", () => {
  const urls = gefilterteArtikel().map((a) => a.url);
  if (urls.length && confirm(`${anzahl(urls.length, "Artikel", "Artikel")} als angeschaut markieren?`)) {
    setzeAngeschaut(urls, true, `${anzahl(urls.length, "Artikel", "Artikel")} abgehakt.`);
  }
});

// ---------------------------------------------------------------- Kopieren

/** In die Zwischenablage; ältere Browser (z. B. alte iPhones) über ein unsichtbares Textfeld. */
async function kopiereText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const feld = el("textarea", { readonly: "", "aria-hidden": "true", class: "kopier-feld" });
    feld.value = text;
    document.body.append(feld);
    feld.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    feld.remove();
    return ok;
  }
}

// ---------------------------------------------------------------- Tag-Pfad: wo liegt ein Tag im Tag-Baum?

function tagKnopf(name, artikel, wo) {
  const beleg = artikel.belege?.[name];
  return el("button", { type: "button", class: "tag-knopf", "data-tag-pfad": name, "data-url": artikel.url,
    title: `${beleg ? `Warum: ${beleg}\n` : ""}Antippen: kopieren · Gedrückt halten, Rechtsklick oder Umschalt+Klick: Pfad und Beleg`,
    "data-fokus": `t|${wo}|${artikel.url}|${name}` }, name);
}

// ---- Antippen kopiert, Gedrückthalten / Rechtsklick / Umschalt+Klick zeigt den Pfad, Strg+C über einem Tag kopiert

const HINWEIS_SCHLUESSEL = "newsbot_tag_hinweis";
let toastUhr = null;

function zeigeToast(...inhalt) {
  const toast = $("toast");
  toast.replaceChildren(...inhalt.filter(Boolean));
  toast.hidden = false;
  toast.classList.remove("weg");
  void toast.offsetWidth;  // Animation neu starten, auch wenn schon sichtbar
  toast.classList.add("da");
  clearTimeout(toastUhr);
  toastUhr = setTimeout(() => { toast.classList.remove("da"); toast.classList.add("weg"); }, 2400);
}

async function kopiereTag(knopf) {
  const name = knopf.dataset.tagPfad;
  const ok = await kopiereText(name);
  if (!ok) {
    zeigeToast(el("span", {}, "Kopieren nicht möglich – gedrückt halten zeigt den Tag zum Markieren."));
    return;
  }
  knopf.classList.remove("kopiert");
  void knopf.offsetWidth;
  knopf.classList.add("kopiert");
  setTimeout(() => knopf.classList.remove("kopiert"), 900);
  let ersterHinweis = false;
  try {
    ersterHinweis = !localStorage.getItem(HINWEIS_SCHLUESSEL);
    localStorage.setItem(HINWEIS_SCHLUESSEL, "1");
  } catch { /* ohne Speicher eben jedes Mal ohne Hinweis */ }
  zeigeToast(symbol(ICON.haken, 16), el("span", {}, "Kopiert: "), el("strong", {}, name),
    ersterHinweis ? el("small", {}, "Pfad im Tag-Baum: gedrückt halten (Handy) oder Rechtsklick (PC)") : null);
}

let drueckUhr = null;
let drueckStart = null;
let letzterZeiger = "mouse";
let klickIgnorieren = 0;  // bis dahin kopiert der Klick nicht, der zum selben Gedrückthalten gehört

$("ticker").addEventListener("pointerdown", (e) => {
  const knopf = e.target.closest("button[data-tag-pfad]");
  letzterZeiger = e.pointerType;
  klickIgnorieren = 0;  // neue Berührung – neuer Klick zählt wieder
  if (!knopf || e.pointerType === "mouse") return;  // Maus: Rechtsklick statt Gedrückthalten
  drueckStart = { x: e.clientX, y: e.clientY };
  clearTimeout(drueckUhr);
  drueckUhr = setTimeout(() => {
    drueckUhr = null;
    klickIgnorieren = Date.now() + 800;
    if (navigator.vibrate) navigator.vibrate(12);
    zeigeTagPfad(knopf);
  }, 480);
});
const drueckenAbbrechen = () => { clearTimeout(drueckUhr); drueckUhr = null; };
$("ticker").addEventListener("pointerup", drueckenAbbrechen);
$("ticker").addEventListener("pointercancel", drueckenAbbrechen);
$("ticker").addEventListener("pointermove", (e) => {
  if (drueckUhr && drueckStart && Math.hypot(e.clientX - drueckStart.x, e.clientY - drueckStart.y) > 10) drueckenAbbrechen();
});
$("ticker").addEventListener("contextmenu", (e) => {  // Rechtsklick, Menütaste – und Android meldet Gedrückthalten so
  const knopf = e.target.closest("button[data-tag-pfad]");
  if (!knopf) return;
  e.preventDefault();
  if ($("tag-pfad").open) return;  // schon über Gedrückthalten geöffnet
  drueckenAbbrechen();
  if (letzterZeiger !== "mouse") klickIgnorieren = Date.now() + 800;  // nach dem Finger-Gedrückthalten folgt evtl. ein Klick
  zeigeTagPfad(knopf);
});

let tagUnterMaus = null;
$("ticker").addEventListener("pointerover", (e) => { tagUnterMaus = e.target.closest("button[data-tag-pfad]"); });
$("ticker").addEventListener("pointerleave", () => { tagUnterMaus = null; });
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "c" || e.altKey || e.shiftKey) return;
  if (String(getSelection() || "").trim()) return;  // markierten Text normal kopieren
  const fokus = document.activeElement?.closest?.("button[data-tag-pfad]");
  const knopf = (tagUnterMaus?.isConnected ? tagUnterMaus : null) || fokus;  // Maus zeigt, was gemeint ist
  if (!knopf) return;
  e.preventDefault();
  kopiereTag(knopf);
});

/** Pfade laut Beschreibung in der Tag-Liste („A > B > Tag“, mehrere mit „ | “). Ohne Pfad: nur der Tag selbst. */
function tagPfade(name) {
  const t = (daten.listen?.tags || []).find((x) => x.name.toLowerCase() === name.toLowerCase());
  const pfade = [];
  let notiz = "";
  for (const teil of (t?.beschreibung || "").split(" | ").filter(Boolean)) {
    const pfad = teil.split(" > ").map((x) => x.trim());
    if (pfad.length > 1 && pfad.at(-1).toLowerCase() === name.toLowerCase()) pfade.push(pfad);
    else notiz = teil;  // freie Beschreibung statt Pfad
  }
  return { pfade: pfade.length ? pfade : [[t ? t.name : name]], notiz, bekannt: Boolean(t) };
}

let tagPfadAusloeser = null;

function zeigeTagPfad(knopf) {
  const name = knopf.dataset.tagPfad;
  const { pfade, notiz, bekannt } = tagPfade(name);
  const dialog = $("tag-pfad");
  const treffer = daten.artikel.filter((a) => a.tags.includes(name)).length;
  const beleg = daten.artikel.find((a) => a.url === knopf.dataset.url)?.belege?.[name] || "";
  const ergaenzt = beleg.startsWith("vom Bot ergänzt");
  const tiefe = Math.max(...pfade.map((p) => p.length));

  const baum = (pfad) => el("ol", { class: "pfad-baum" }, ...pfad.map((stufe, i) => {
    const ziel = i === pfad.length - 1;
    const attrs = { class: `pfad-stufe${ziel ? " ziel" : ""}${i === 0 ? " wurzel" : ""}` };
    if (ziel) attrs["aria-current"] = "true";
    const zeile = el("li", attrs,
      el("span", { class: "pfad-knoten", "aria-hidden": "true" }),
      el("span", { class: "pfad-name" }, stufe),
      ziel ? null : el("span", { class: "nur-vorlesen" }, `, Ebene ${i + 1}`));
    zeile.style.setProperty("--ebene", i);  // per CSSOM – die Seite erlaubt keine style-Attribute (CSP)
    return zeile;
  }));

  dialog.replaceChildren(el("div", { class: "tag-pfad-inhalt" },
    el("span", { class: "tag-pfad-griff", "aria-hidden": "true" }),
    el("header", { class: "tag-pfad-kopf" },
      el("span", { class: "tag-pfad-symbol", "aria-hidden": "true" }, symbol(ICON.etikett, 18)),
      el("div", { class: "tag-pfad-titel" },
        el("p", { class: "tag-pfad-oberzeile" }, pfade.length > 1 ? `${pfade.length} Pfade im Tag-Baum` : "Pfad im Tag-Baum"),
        el("h2", { id: "tag-pfad-name" }, name)),
      el("button", { type: "button", class: "symbol-knopf", "data-schliessen": "", "aria-label": "Schließen" }, symbol(ICON.x))),
    el("p", { class: "tag-kopiert", role: "status", "aria-live": "polite" }),
    el("section", { class: `tag-beleg${ergaenzt ? " ergaenzt" : ""}${beleg ? "" : " leer"}`, "aria-label": "Warum dieser Tag" },
      el("p", { class: "tag-beleg-titel" }, "Warum dieser Tag?"),
      el("p", { class: "tag-beleg-text" }, beleg
        ? (ergaenzt ? "Pflicht-Tag – die KI hatte aus diesem Bereich keinen gewählt, deshalb hat der Bot ihn ergänzt." : beleg)
        : "Kein Beleg gespeichert – der Artikel wurde vor dieser Funktion getaggt.")),
    pfade.length === 1 && pfade[0].length > 1 ? el("p", { class: "tag-pfad-weg", "aria-hidden": "true" },
      ...pfade[0].flatMap((stufe, i) => [i ? el("span", { class: "pfeil" }, "→") : null, el("span", {}, stufe)])) : null,
    ...pfade.map((pfad, n) => el("section", { class: "pfad-block", "aria-label": pfade.length > 1 ? `Pfad ${n + 1}` : "Pfad" },
      pfade.length > 1 ? el("p", { class: "pfad-nummer" }, `Pfad ${n + 1}`) : null,
      baum(pfad))),
    notiz ? el("p", { class: "tag-pfad-notiz" }, notiz) : null,
    !bekannt ? el("p", { class: "tag-pfad-notiz" }, daten.listen
      ? "Dieser Tag steht nicht mehr in der Tag-Liste."
      : "Den Pfad zeigt die Seite, sobald der Bot verbunden ist.") : null,
    el("footer", { class: "tag-pfad-fuss" },
      el("span", { class: "tag-pfad-info" }, `${tiefe > 1 ? `Ebene ${tiefe}` : "Oberste Ebene"} · ${anzahl(treffer, "Artikel", "Artikel")}`),
      el("div", { class: "tag-pfad-knoepfe" },
        el("button", { type: "button", class: "knopf mit-symbol", "data-tag-kopieren": name },
          symbol(ICON.kopie, 16), el("span", {}, "Kopieren")),
        el("button", { type: "button", class: "knopf mit-symbol", "data-tag-filter": name },
          symbol(ICON.filter, 16), el("span", {}, "Nur diese Artikel"))))));

  tagPfadAusloeser = knopf;
  knopf.setAttribute("aria-expanded", "true");
  dialog.showModal();
  platziereTagPfad(dialog, knopf);
}

async function meldeKopiert(name, versprechen) {
  const ok = await versprechen;
  const hinweis = $("tag-pfad").querySelector(".tag-kopiert");
  if (!hinweis) return;
  hinweis.className = `tag-kopiert ${ok ? "ok" : "fehler"}`;
  hinweis.replaceChildren(...(ok
    ? [symbol(ICON.haken, 15), el("span", {}, "Kopiert: "), el("strong", {}, name), el("span", { class: "leise" }, " – zum Einfügen bereit")]
    : [el("span", {}, "Kopieren nicht möglich – Name markieren und selbst kopieren.")]));
}

function platziereTagPfad(dialog, knopf) {
  dialog.style.left = dialog.style.top = "";
  if (matchMedia("(max-width: 520px)").matches) return;  // Handy: Blatt von unten (CSS)
  const r = knopf.getBoundingClientRect();
  const breite = dialog.offsetWidth;
  const hoehe = dialog.offsetHeight;
  const links = Math.min(Math.max(16, r.left + r.width / 2 - breite / 2), innerWidth - breite - 16);
  const unten = r.bottom + 10 + hoehe <= innerHeight - 16;
  dialog.style.left = `${links}px`;
  dialog.style.top = `${unten ? r.bottom + 10 : Math.max(16, r.top - 10 - hoehe)}px`;
  dialog.dataset.seite = unten ? "unten" : "oben";
  dialog.style.setProperty("--pfeil-x", `${Math.min(Math.max(24, r.left + r.width / 2 - links), breite - 24)}px`);
}

$("tag-pfad").addEventListener("close", () => {
  if (tagPfadAusloeser) {
    tagPfadAusloeser.setAttribute("aria-expanded", "false");
    if (tagPfadAusloeser.isConnected) tagPfadAusloeser.focus({ preventScroll: true });
  }
  tagPfadAusloeser = null;
});
$("tag-pfad").addEventListener("click", (e) => {
  const dialog = $("tag-pfad");
  if (e.target === dialog || e.target.closest("[data-schliessen]")) { dialog.close(); return; }
  const nochmal = e.target.closest("button[data-tag-kopieren]");
  if (nochmal) {
    meldeKopiert(nochmal.dataset.tagKopieren, kopiereText(nochmal.dataset.tagKopieren));
    return;
  }
  const filter = e.target.closest("button[data-tag-filter]");
  if (!filter) return;
  dialog.close();
  $("filter-tag").value = filter.dataset.tagFilter;
  sichtbar = PRO_SEITE;
  zeichneTicker();
  $("bereich-artikel").scrollIntoView({ behavior: "smooth", block: "start" });
});
addEventListener("resize", () => { if ($("tag-pfad").open) $("tag-pfad").close(); });
addEventListener("scroll", () => {
  if ($("tag-pfad").open && !matchMedia("(max-width: 520px)").matches) $("tag-pfad").close();
}, { passive: true });

$("ticker").addEventListener("click", async (e) => {
  const tagPfad = e.target.closest("button[data-tag-pfad]");
  if (tagPfad) {
    if (Date.now() < klickIgnorieren) {  // Klick am Ende des Gedrückthaltens
      klickIgnorieren = 0;
      return;
    }
    if (e.shiftKey) zeigeTagPfad(tagPfad);
    else kopiereTag(tagPfad);
    return;
  }
  const haken = e.target.closest("button[data-abhaken]");
  if (haken) {
    const a = daten.artikel.find((x) => x.url === haken.dataset.abhaken);
    if (a) {
      const wert = !istAngeschaut(a);
      setzeAngeschaut([a.url], wert, wert ? `Abgehakt: „${a.titel.slice(0, 80)}“` : `Wieder offen: „${a.titel.slice(0, 80)}“`);
    }
    return;
  }
  const details = e.target.closest("button[data-details]");
  if (details) {
    const url = details.dataset.details;
    if (offeneArtikel.has(url)) offeneArtikel.delete(url);
    else offeneArtikel.add(url);
    zeichneTicker();
    return;
  }
  const kopieren = e.target.closest("button[data-kopieren]");
  if (!kopieren) return;
  const beschriftung = kopieren.dataset.beschriftung || kopieren.textContent;
  kopieren.dataset.beschriftung = beschriftung;
  kopieren.textContent = (await kopiereText(kopieren.dataset.kopieren)) ? "Kopiert" : "Kopieren nicht möglich";
  setTimeout(() => { kopieren.textContent = beschriftung; }, 2000);
});

$("medien-leiste").addEventListener("click", (e) => {
  const chip = e.target.closest("button[data-medium]");
  if (!chip) return;
  const auswahl = $("filter-medium");
  auswahl.value = auswahl.value === chip.dataset.medium ? "" : chip.dataset.medium;
  sichtbar = PRO_SEITE;
  zeichneTicker();
});

document.querySelectorAll("[data-ansicht]").forEach((knopf) => knopf.addEventListener("click", () => {
  ansicht = knopf.dataset.ansicht;
  try { localStorage.setItem(ANSICHT_SCHLUESSEL, ansicht); } catch { /* egal */ }
  if (daten) zeichneTicker();
}));

// ---------------------------------------------------------------- Fehler & Befehle

function zeichneFehler() {
  const liste = $("fehler");
  const zahl = $("zahl-fehler");
  zahl.textContent = daten.fehler.length ? String(daten.fehler.length) : "";
  zahl.classList.toggle("warnung", daten.fehler.length > 0);
  if (!daten.fehler.length) {
    liste.replaceChildren(el("li", { class: "leise" }, "Keine Fehler. Alle Quellen ließen sich abrufen."));
    return;
  }
  liste.replaceChildren(...daten.fehler.slice(0, 50).map((f) =>
    el("li", { class: "fehler-eintrag" },
      el("span", { class: "wann" }, `${tagText(new Date(f.zeit))}, ${uhrzeit(f.zeit) ?? ""}`),
      el("span", { class: "problem" }, f.grund),
    )));
}

function zeichneBefehle() {
  const liste = $("befehle");
  if (!daten.befehle.some((b) => b.aktion !== "angeschaut")) {  // Abhaken steht nicht in der Liste – das wären zu viele
    liste.replaceChildren(el("li", { class: "leise" }, "Noch keine Befehle gesendet."));
    return;
  }
  liste.replaceChildren(...daten.befehle.filter((b) => b.aktion !== "angeschaut").map((b) => {
    const name = befehlName(b);
    const stand = b.zustand === "erledigt" ? b.ergebnis : ZUSTAND_NAMEN[b.zustand];
    const wann = new Date(b.erstellt * 1000);
    return el("li", {},
      el("span", { class: "wann" }, `${tagText(wann)}, ${fmtZeit.format(wann)}`),
      `${name}: ${stand}`);
  }));
}

// ---------------------------------------------------------------- Befehle senden

async function schickeBefehl(body) {
  const r = await fetch("/api/befehl", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.status === 401) { location.reload(); throw new Error("Bitte neu anmelden."); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.json();
}

function gesendetText(name) {
  return daten?.bot.online
    ? `„${name}“ gesendet. Der Bot führt den Befehl innerhalb von etwa 30 Sekunden aus.`
    : `„${name}“ gespeichert. Der Bot läuft gerade nicht und führt ihn aus, sobald er wieder da ist.`;
}

async function sendeBefehl(knopf) {
  const aktion = knopf.dataset.aktion;
  const body = { aktion };
  if (aktion === "intervall") body.wert = Number($("intervall").value);
  if (aktion === "max_alter") body.wert = Number($("max-alter").value);

  knopf.disabled = true;
  const rueck = $("rueckmeldung");
  try {
    await schickeBefehl(body);
    rueck.textContent = gesendetText(AKTIONS_NAMEN[aktion]);
    laden();
  } catch (e) {
    rueck.textContent = `Befehl wurde nicht gesendet: ${e.message}`;
  } finally {
    knopf.disabled = false;
  }
}

// ---------------------------------------------------------------- Browser-Benachrichtigungen

const PUSH_MOEGLICH = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const IST_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const ALS_APP = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
let swAnmeldung = null;
let pushAbo = null;
let aboAufgefrischt = false;

function b64ZuBytes(b64) {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
function bytesZuB64(puffer) {
  return btoa(String.fromCharCode(...new Uint8Array(puffer))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function pushVorbereiten() {
  if (!PUSH_MOEGLICH) return;
  try {
    swAnmeldung = await navigator.serviceWorker.register("/sw.js");
    pushAbo = await swAnmeldung.pushManager.getSubscription();
  } catch {
    swAnmeldung = null;
  }
}

async function sendePushAbo(aktion, aboJson) {
  const r = await fetch("/api/push", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ aktion, abo: aboJson }),
  });
  if (r.status === 401) { location.reload(); return; }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
}

function zeichnePush() {
  const kasten = $("push-kasten");
  const titel = $("push-titel");
  const knopf = $("push-knopf");
  const hinweis = $("push-hinweis");
  const status = daten.bot.status;
  const schluessel = status && status.vapid_public_key;
  const geraete = (status && status.push_geraete) || 0;
  const discord = status && status.discord_aktiv ? " Zusätzlich über Discord." : "";
  knopf.hidden = true;
  kasten.classList.remove("an");
  titel.textContent = "Benachrichtigungen";

  if (!PUSH_MOEGLICH || !swAnmeldung) {
    hinweis.textContent = IST_IOS && !ALS_APP
      ? "Am iPhone: unten auf Teilen tippen, „Zum Home-Bildschirm“ wählen und die Seite über das neue Symbol öffnen."
      : "Dieser Browser kann keine Benachrichtigungen anzeigen. Neue Artikel siehst du trotzdem hier.";
    return;
  }
  if (!schluessel) { hinweis.textContent = "Verfügbar, sobald der Bot verbunden ist."; return; }
  if (Notification.permission === "denied") {
    titel.textContent = "Benachrichtigungen blockiert";
    hinweis.textContent = "Erlaube sie in den Website-Einstellungen des Browsers, dann kannst du sie hier einschalten.";
    return;
  }

  // Hat der Bot einen neuen Schlüssel (z. B. vapid_privat.pem gelöscht), gilt das alte Abo nicht mehr.
  const aboSchluessel = pushAbo && pushAbo.options && pushAbo.options.applicationServerKey;
  if (pushAbo && aboSchluessel && bytesZuB64(aboSchluessel) !== schluessel) {
    pushAbo.unsubscribe().catch(() => {});
    pushAbo = null;
  }
  if (pushAbo && !aboAufgefrischt) {
    aboAufgefrischt = true;  // dem Bot das Abo bei jedem Besuch erneut mitteilen – schadet nie
    sendePushAbo("hinzufuegen", pushAbo.toJSON()).catch(() => { aboAufgefrischt = false; });
  }

  knopf.hidden = false;
  if (pushAbo) {
    kasten.classList.add("an");
    titel.textContent = "Benachrichtigungen an";
    hinweis.textContent = `${geraete > 1 ? `Auf ${geraete} Geräten aktiv, auch auf diesem.` : "Auf diesem Gerät aktiv."}${discord}`;
    knopf.className = "link-knopf";
    knopf.textContent = "Auf diesem Gerät ausschalten";
  } else {
    titel.textContent = geraete ? "Hier aus" : "Benachrichtigungen aus";
    hinweis.textContent = geraete
      ? `Auf ${geraete} ${geraete === 1 ? "anderem Gerät" : "anderen Geräten"} aktiv.${discord}`
      : `Schalte sie ein, dann meldet sich der Bot bei neuen Artikeln.${discord}`;
    knopf.className = "knopf";
    knopf.textContent = "Auf diesem Gerät einschalten";
  }
}

$("push-knopf").addEventListener("click", async () => {
  const knopf = $("push-knopf");
  const rueck = $("rueckmeldung");
  knopf.disabled = true;
  try {
    if (pushAbo) {
      const aboJson = pushAbo.toJSON();
      await sendePushAbo("entfernen", aboJson);
      await pushAbo.unsubscribe();
      pushAbo = null;
      rueck.textContent = "Benachrichtigungen auf diesem Gerät ausgeschaltet.";
    } else {
      const erlaubnis = await Notification.requestPermission();
      if (erlaubnis !== "granted") {
        rueck.textContent = "Ohne deine Erlaubnis kann der Browser keine Benachrichtigungen zeigen.";
        return;
      }
      pushAbo = await swAnmeldung.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ZuBytes(daten.bot.status.vapid_public_key),
      });
      await sendePushAbo("hinzufuegen", pushAbo.toJSON());
      aboAufgefrischt = true;
      rueck.textContent = "Benachrichtigungen eingeschaltet. In etwa 30 Sekunden kommt eine Bestätigung vom Bot.";
    }
  } catch (e) {
    rueck.textContent = `Das hat nicht geklappt: ${e.message}`;
  } finally {
    knopf.disabled = false;
    laden();
  }
});

document.addEventListener("visibilitychange", () => {
  if (!daten) return;
  if (document.visibilityState === "hidden") {
    speichereGesehenBis(neuestesFundDatum());  // beim nächsten Besuch gilt alles bis hierher als gesehen
  } else {
    gesehenBis = ladeGesehenBis() ?? gesehenBis;
    laden();  // nach dem Zurückkommen sofort den echten Stand zeigen
  }
});

document.querySelectorAll(".steuerung button[data-aktion]").forEach((k) => k.addEventListener("click", () => sendeBefehl(k)));
["suche", "filter-tag", "filter-medium", "nur-gemeldet", "filter-gelesen"].forEach((id) =>
  $(id).addEventListener("input", () => {
    if (!daten) return;
    sichtbar = PRO_SEITE;  // neue Filter → wieder oben anfangen
    zeichneTicker();
  }));

// Erst starten, wenn auch verwaltung.js geladen ist
document.addEventListener("DOMContentLoaded", () => {
  pushVorbereiten().finally(laden);
  // Nur abfragen, solange die Seite sichtbar ist – beim Zurückkommen wird sofort aktualisiert.
  setInterval(() => { if (document.visibilityState === "visible") laden(); }, AKTUALISIEREN_MS);
});
