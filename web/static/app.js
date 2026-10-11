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
const TAG_MUSTER = /^[\p{L}\p{N}][\p{L}\p{N}_ .&\/'+-]{0,39}$/u;
const WORT_MUSTER = /^[\p{L}\p{N}][\p{L}\p{N}_ .&\/'+-]{0,58}\*?$/u;
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
  const woerter = b.woerter || [];
  const was = urls.length === 1 ? kurzUrl(urls[0]) : anzahl(urls.length, "Quelle", "Quellen");
  switch (b.aktion) {
    case "intervall": return `Intervall auf ${b.wert} Min.`;
    case "max_alter": return `Artikel bis ${alterText(b.wert)} alt melden`;
    case "quellen_importieren": return `Import: ${anzahl(b.anzahl_quellen || 0, "Eintrag", "Einträge")} für Quellen`;
    case "tags_importieren":
      return `Import: ${anzahl(b.anzahl_tags || 0, "Tag", "Tags")} mit ${anzahl(b.anzahl_woerter || 0, "Schlagwort", "Schlagwörtern")}`;
    case "quellen_hinzufuegen": return `${was} für ${tageText(b.tage || [])} hinzufügen`;
    case "quellen_entfernen": return `${was} bei ${tageText(b.tage || [])} entfernen`;
    case "tag_hinzufuegen": return `Tag „${b.tag}“: ${woerter.join(", ")} hinzufügen`;
    case "tag_entfernen": return woerter.length ? `Tag „${b.tag}“: ${woerter.join(", ")} entfernen` : `Tag „${b.tag}“ löschen`;
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

function zeichneFilterOptionen() {
  fuelleAuswahl($("filter-tag"), "Alle Tags", daten.artikel.flatMap((a) => a.tags));
  fuelleAuswahl($("filter-medium"), "Alle Medien", daten.artikel.map((a) => a.medium));
}

function fuelleAuswahl(auswahl, leerText, werte) {
  const aktuell = auswahl.value;
  const eindeutig = [...new Set(werte)].sort((a, b) => a.localeCompare(b, "de"));
  auswahl.replaceChildren(el("option", { value: "" }, leerText), ...eindeutig.map((w) => el("option", { value: w }, w)));
  auswahl.value = eindeutig.includes(aktuell) ? aktuell : "";
}

const zeitpunkt = (a) => Date.parse(a.datum || a.gefunden_um) || 0;

function gefilterteArtikel() {
  const suche = $("suche").value.trim().toLowerCase();
  const tag = $("filter-tag").value;
  const medium = $("filter-medium").value;
  const nurGemeldet = $("nur-gemeldet").checked;
  return [...daten.artikel].sort((x, y) => zeitpunkt(y) - zeitpunkt(x)).filter((a) =>
    (!tag || a.tags.includes(tag)) &&
    (!medium || a.medium === medium) &&
    (!nurGemeldet || a.gemeldet) &&
    (!suche || `${a.titel} ${a.teaser}`.toLowerCase().includes(suche))
  );
}

function trennerText(ms) {
  const d = new Date(ms);
  const kurz = tagText(d);
  const lang = fmtTagLang.format(d);
  return kurz === "heute" ? `Heute · ${lang}` : kurz === "gestern" ? `Gestern · ${lang}` : lang;
}

function zeichneTicker() {
  const liste = $("ticker");
  const mehr = $("mehr");
  const artikel = gefilterteArtikel();
  const gesamt = daten.artikel.length;
  const neuZahl = daten.artikel.filter(istNeu).length;

  $("zahl-artikel").textContent = gesamt ? String(gesamt) : "";
  document.title = neuZahl ? `(${neuZahl}) News-Bot` : "News-Bot";
  $("anzahl").textContent = !gesamt ? ""
    : artikel.length === gesamt ? `${gesamt} Artikel${neuZahl ? `, davon ${neuZahl} neu seit deinem letzten Besuch` : ""}`
    : `${artikel.length} von ${gesamt} Artikeln passen zu den Filtern`;

  mehr.hidden = true;
  if (!gesamt) {
    liste.replaceChildren(el("li", { class: "leer" },
      daten.bot.status
        ? daten.bot.status.quellen_heute
          ? "Noch keine Artikel. Mit „Jetzt prüfen“ startest du sofort eine Prüfung."
          : "Noch keine Artikel. Für heute sind keine Quellen eingetragen – im Reiter „Quellen“ kannst du welche hinzufügen."
        : "Sobald der Bot verbunden ist, erscheinen hier die gefundenen Artikel."));
    return;
  }
  if (!artikel.length) {
    liste.replaceChildren(el("li", { class: "leer" }, "Kein Artikel passt zu diesen Filtern."));
    return;
  }

  const zeilen = [];
  let letzterTag = null;
  for (const a of artikel.slice(0, sichtbar)) {
    const ms = zeitpunkt(a);
    const tag = fmtTagSchluessel.format(new Date(ms));
    if (tag !== letzterTag) {
      zeilen.push(el("li", { class: "trenner" }, trennerText(ms)));
      letzterTag = tag;
    }
    zeilen.push(artikelZeile(a));
  }
  liste.replaceChildren(...zeilen);

  const rest = artikel.length - sichtbar;
  if (rest > 0) {
    mehr.hidden = false;
    mehr.textContent = `Weitere ${Math.min(rest, PRO_SEITE)} anzeigen (noch ${rest})`;
  }
}

function artikelZeile(a) {
  const d = a.datum ? new Date(a.datum) : null;
  const zeit = d && !isNaN(d)
    ? el("div", { class: "zeit" }, el("div", { class: "zeit-wert" }, fmtZeit.format(d)),
        a.datum_art === "aktualisiert" ? el("small", {}, "aktualisiert") : null)
    : el("div", { class: "zeit" }, el("div", { class: "zeit-wert unsicher" }, "?"), el("small", {}, "Datum unklar"));

  const url = sichereUrl(a.url);
  const titel = url
    ? el("a", { class: "titel", href: url, target: "_blank", rel: "noopener noreferrer" }, a.titel)
    : el("span", { class: "titel" }, a.titel);

  const kopf = el("div", { class: "titel-zeile" }, istNeu(a) ? el("span", { class: "neu-marke" }, "neu") : null, titel);
  const quelle = el("p", { class: "quelle" },
    a.medium, a.autor ? `, ${a.autor}` : "",
    a.gemeldet ? el("span", { class: "gemeldet-hinweis" }, "gemeldet") : "");

  return el("li", { class: "artikel" },
    zeit,
    el("div", {},
      kopf,
      quelle,
      a.teaser ? el("p", { class: "teaser" }, a.teaser) : null,
      a.tags.length ? el("ul", { class: "tags", "aria-label": "Tags" }, ...a.tags.map((t) => el("li", {}, t))) : null,
    ),
  );
}

$("mehr").addEventListener("click", () => {
  sichtbar += PRO_SEITE;
  zeichneTicker();
});

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
  if (!daten.befehle.length) {
    liste.replaceChildren(el("li", { class: "leise" }, "Noch keine Befehle gesendet."));
    return;
  }
  liste.replaceChildren(...daten.befehle.map((b) => {
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
["suche", "filter-tag", "filter-medium", "nur-gemeldet"].forEach((id) =>
  $(id).addEventListener("input", () => {
    if (!daten) return;
    sichtbar = PRO_SEITE;  // neue Filter → wieder oben anfangen
    zeichneTicker();
  }));

// Erst starten, wenn auch verwaltung.js geladen ist
document.addEventListener("DOMContentLoaded", () => {
  pushVorbereiten().finally(laden);
  setInterval(laden, AKTUALISIEREN_MS);
});
