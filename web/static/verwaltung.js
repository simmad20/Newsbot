"use strict";
// Quellen und Tags verwalten: Tabelle, Karten, Dialoge und Datei-Import.
// Alles wird über el()/textContent angezeigt – nie als HTML. Dateien werden nur hier im Browser
// gelesen; an den Server gehen ausschließlich geprüfte Texte. Server und Bot prüfen trotzdem
// jede Änderung noch einmal selbst.

const MAX_PRO_BEFEHL = 50;        // darüber wird automatisch als Import geschickt
const MAX_QUELLEN = 700;
const MAX_TAGS = 1000;
const MAX_DATEI_BYTES = 2 * 1024 * 1024;
const MAX_DATEI_ZEILEN = 20000;
const VERBOTENE_URL_ZEICHEN = /[\s\\"<>`{}|^]/;
const INTERNE_ENDUNGEN = [".localhost", ".local", ".lan", ".home", ".internal", ".intranet", ".corp", ".arpa"];
const WEG_ANZEIGE = {
  feed: ["RSS", "Liest den RSS/Atom-Feed der Seite – am zuverlässigsten."],
  news_sitemap: ["News-Sitemap", "Kein Feed – liest die News-Sitemap der Seite (Titel und Zeit für Suchmaschinen)."],
  sitemap: ["Sitemap", "Kein Feed – liest die Sitemap der Seite und holt Titel und Datum aus den Artikelseiten."],
  startseite: ["Startseite", "Weder Feed noch Sitemap – erkennt neue Artikel-Links auf der Seite. Weniger zuverlässig."],
};
const TAG_KUERZEL = { mo: "montag", di: "dienstag", mi: "mittwoch", do: "donnerstag", fr: "freitag", sa: "samstag", so: "sonntag" };

const wartetAuf = { quellen: null, tags: null };  // Befehl, dessen Ergebnis wir anzeigen wollen
const letzteAnsicht = { quellen: "", tags: "" };  // nur neu zeichnen, wenn sich etwas geändert hat

// ---------------------------------------------------------------- Kleinteile

const SVG_NS = "http://www.w3.org/2000/svg";
const ICON = {
  haken: ["M20 6 9 17l-5-5"],
  muell: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6", "M10 11v6", "M14 11v6"],
  plus: ["M12 5v14", "M5 12h14"],
  x: ["M18 6 6 18", "m6 6 12 12"],
  extern: ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
  pfeil: ["m6 9 6 6 6-6"],
  stift: ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"],
};

function symbol(pfade, groesse = 18) {
  const svg = document.createElementNS(SVG_NS, "svg");
  for (const [k, v] of Object.entries({ width: groesse, height: groesse, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
  for (const d of pfade) {
    const pfad = document.createElementNS(SVG_NS, "path");
    pfad.setAttribute("d", d);
    svg.append(pfad);
  }
  return svg;
}

const klein = (text) => text.toLowerCase();
const tagLang = (k) => TAGE.find(([x]) => x === k)[1];

function wochentagAus(wert) {
  const t = klein(String(wert ?? "").trim()).replace(/\.$/, "");
  return TAGE.some(([k]) => k === t) ? t : TAG_KUERZEL[t] || null;
}

function interneIp(host) {
  const teile = host.split(".");
  if (teile.length !== 4 || !teile.every((t) => /^\d{1,3}$/.test(t) && Number(t) <= 255)) return null;  // keine IPv4
  const [a, b] = teile.map(Number);
  return a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31)
    || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || (a === 198 && (b === 18 || b === 19));
}

/** Gleiche Regeln wie Server und Bot: nur http(s) zu öffentlichen Servern, keine Zugangsdaten. */
function pruefeUrl(text) {
  const roh = String(text ?? "").trim();
  if (!roh || roh.length > 500 || VERBOTENE_URL_ZEICHEN.test(roh)) return null;
  const url = /^[a-z][a-z0-9+.-]*:\/\//i.test(roh) ? roh : `https://${roh}`;
  let u;
  try { u = new URL(url); } catch { return null; }
  const host = klein(u.hostname);
  if (!["http:", "https:"].includes(u.protocol) || u.username || u.password || !host.includes(".") || host.startsWith("[")) return null;
  const ip = interneIp(host);
  if (ip === true || (ip === null && /^[\d.]+$/.test(host))) return null;
  if (host === "localhost" || INTERNE_ENDUNGEN.some((e) => host.endsWith(e))) return null;
  return url;
}

function offeneBefehle(aktionen) {
  return daten.befehle.filter((b) => b.zustand !== "erledigt" && aktionen.includes(b.aktion));
}

function meldeErgebnis(bereich) {
  const id = wartetAuf[bereich];
  const b = id && daten.befehle.find((x) => x.id === id);
  if (!b || b.zustand !== "erledigt") return;
  $(`${bereich}-rueck`).textContent = `Erledigt: ${b.ergebnis}`;
  wartetAuf[bereich] = null;
}

function importHinweis(befehle) {
  if (!befehle.length) return null;
  return el("div", { class: "ausstehend" },
    el("p", { class: "ausstehend-titel" }, daten.bot.online ? "Import wird übertragen" : "Import wartet auf den Bot"),
    el("ul", {}, ...befehle.map((b) => el("li", {}, befehlName(b)))));
}

/** Neu zeichnen, ohne dass der Fokus (z. B. Tastatur auf einem Tag-Knopf) verloren geht. */
function zeichneErhaltend(behaelter, zeichnen) {
  const aktiv = document.activeElement;
  const schluessel = aktiv && behaelter.contains(aktiv) ? aktiv.dataset.fokus : null;
  zeichnen();
  if (!schluessel) return;
  const neu = [...behaelter.querySelectorAll("[data-fokus]")].find((x) => x.dataset.fokus === schluessel);
  if (neu) neu.focus();
}

async function listenBefehl(bereich, body, knopf) {
  const rueck = $(`${bereich}-rueck`);
  if (knopf) knopf.disabled = true;
  try {
    const neu = await schickeBefehl(body);
    wartetAuf[bereich] = neu.id;
    rueck.textContent = gesendetText(befehlName(neu));
    laden();
    return true;
  } catch (e) {
    rueck.textContent = `Nicht gesendet: ${e.message}`;
    return false;
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

// ---------------------------------------------------------------- Quellen: Tabelle

function quellenModell() {
  const zeilen = new Map();  // url → { url, tage, kommt, geht }
  const zeile = (url) => {
    if (!zeilen.has(url)) zeilen.set(url, { url, tage: new Set(), kommt: new Set(), geht: new Set() });
    return zeilen.get(url);
  };
  for (const q of daten.listen?.quellen || []) zeile(q.url).tage.add(q.wochentag);
  for (const b of offeneBefehle(["quellen_hinzufuegen", "quellen_entfernen"])) {
    for (const url of b.urls || []) for (const t of b.tage || []) (b.aktion === "quellen_hinzufuegen" ? zeile(url).kommt : zeile(url).geht).add(t);
  }
  const sortiert = (u) => klein(kurzUrl(u)).replace(/^www\./, "");
  return [...zeilen.values()].sort((a, b) => sortiert(a.url).localeCompare(sortiert(b.url), "de"));
}

function zeichneQuellen() {
  const quellen = daten.listen ? daten.listen.quellen : null;
  const anzahlQuellen = quellen ? new Set(quellen.map((q) => q.url)).size : 0;
  $("zahl-quellen").textContent = anzahlQuellen ? String(anzahlQuellen) : "";
  meldeErgebnis("quellen");
  const suche = klein($("quellen-suche").value.trim());
  const heute = heutigerTag();
  const offen = offeneBefehle(["quellen_hinzufuegen", "quellen_entfernen", "quellen_importieren"]);
  const schluessel = JSON.stringify([quellen, daten.listen?.wege, offen.map((b) => b.id), suche, heute, daten.bot.online]);
  if (schluessel === letzteAnsicht.quellen) return;
  letzteAnsicht.quellen = schluessel;

  const modell = quellenModell();
  const heuteAnzahl = (quellen || []).filter((q) => q.wochentag === heute).length;
  $("quellen-info").textContent = !quellen
    ? "Die Liste erscheint, sobald der Bot verbunden ist. Hinzufügen kannst du trotzdem schon."
    : `${anzahl(anzahlQuellen, "Quelle", "Quellen")} · heute (${tagLang(heute)}) ${heuteAnzahl} · Tag anklicken schaltet ihn ein oder aus`
      + (!daten.bot.online && offen.length ? " · Gestrichelte Änderungen werden übertragen, sobald der Bot läuft." : "");
  $("quellen-ausstehend").replaceChildren(...[importHinweis(offen.filter((b) => b.aktion === "quellen_importieren"))].filter(Boolean));

  const leer = $("quellen-leer");
  leer.hidden = modell.length > 0;
  $("quellen-rahmen").hidden = modell.length === 0;
  if (!modell.length) {
    leer.replaceChildren(
      el("p", { class: "leer-titel" }, "Noch keine Quellen"),
      el("p", {}, "Mit „Quellen hinzufügen“ trägst du Adressen ein, mit „Datei importieren“ übernimmst du eine ganze Liste."));
    return;
  }

  const proTag = Object.fromEntries(TAGE.map(([k]) => [k, modell.filter((z) => z.tage.has(k)).length]));
  $("quellen-kopf").replaceChildren(
    el("th", { scope: "col", class: "quelle-spalte" }, "Quelle"),
    ...TAGE.map(([k, lang, kurz]) => el("th", { scope: "col", class: `tag-spalte${k === heute ? " heute" : ""}`, title: lang },
      el("abbr", { title: lang }, kurz), el("span", { class: "spalten-zahl" }, String(proTag[k])))),
    el("th", { scope: "col" }, el("span", { class: "nur-vorlesen" }, "Entfernen")));

  const sichtbare = modell.filter((z) => !suche || klein(z.url).includes(suche));
  zeichneErhaltend($("quellen-zeilen"), () => $("quellen-zeilen").replaceChildren(...(sichtbare.length
    ? sichtbare.map((z) => quellenZeile(z, heute))
    : [el("tr", {}, el("td", { colspan: "9", class: "keine-treffer" }, "Keine Quelle passt zur Suche."))])));
}

function quellenZeile(z, heute) {
  let host = kurzUrl(z.url);
  let pfad = "";
  try {
    const u = new URL(z.url);
    host = u.host.replace(/^www\./, "");
    pfad = (u.pathname === "/" ? "" : u.pathname) + u.search;
  } catch { /* Anzeige wie gespeichert */ }
  const sicher = sichereUrl(z.url);
  const kurz = kurzUrl(z.url);
  const link = sicher
    ? el("a", { class: "quelle-link", href: sicher, target: "_blank", rel: "noopener noreferrer", title: z.url },
        el("span", { class: "quelle-host" }, host), pfad ? el("span", { class: "quelle-pfad" }, pfad) : null)
    : el("span", { class: "quelle-link" }, z.url);
  const nurWartend = z.tage.size === 0;
  const weg = (daten.listen?.wege || []).find((w) => w.url === z.url);
  const [wegText, wegTitel] = weg ? WEG_ANZEIGE[weg.art] || [] : [];

  const zellen = TAGE.map(([k, lang, tagKurz]) => {
    const an = z.tage.has(k);
    const zustand = z.kommt.has(k) && !an ? "kommt" : z.geht.has(k) && an ? "geht" : an ? "an" : "aus";
    const titel = { an: `Aktiv am ${lang} – zum Entfernen klicken`, aus: `Für ${lang} hinzufügen`,
      kommt: "Wird gerade hinzugefügt", geht: "Wird gerade entfernt" }[zustand];
    const attrs = { type: "button", class: `tag-schalter ${zustand}`, title: titel, "aria-pressed": String(zustand === "an" || zustand === "kommt"),
      "aria-label": `${kurz} am ${lang}`, "data-url": z.url, "data-tag": k, "data-fokus": `q|${z.url}|${k}` };
    if (zustand === "kommt" || zustand === "geht") attrs.disabled = "";
    return el("td", { class: `tag-zelle${k === heute ? " heute" : ""}` },
      el("button", attrs, el("span", { class: "tag-kurz" }, tagKurz), symbol(ICON.haken, 16)));
  });

  return el("tr", { class: nurWartend ? "wartend" : "" },
    el("td", { class: "quelle-zelle" }, el("div", { class: "quelle-inhalt" }, link,
      wegText ? el("span", { class: `weg-marke weg-${weg.art}`, title: wegTitel }, wegText) : null)),
    ...zellen,
    el("td", { class: "aktion-zelle" }, nurWartend ? null
      : el("button", { type: "button", class: "symbol-knopf gefahr", title: "An allen Tagen entfernen",
        "aria-label": `${kurz} an allen Tagen entfernen`, "data-entfernen": z.url, "data-fokus": `qx|${z.url}` }, symbol(ICON.muell))));
}

$("quellen-zeilen").addEventListener("click", (e) => {
  const schalter = e.target.closest("button.tag-schalter");
  if (schalter) {
    const an = schalter.classList.contains("an");
    listenBefehl("quellen", { aktion: an ? "quellen_entfernen" : "quellen_hinzufuegen",
      tage: [schalter.dataset.tag], urls: [schalter.dataset.url] }, schalter);
    return;
  }
  const weg = e.target.closest("button[data-entfernen]");
  if (!weg) return;
  const url = weg.dataset.entfernen;
  const zeile = quellenModell().find((z) => z.url === url);
  const tage = zeile ? [...zeile.tage] : [];
  if (!tage.length || !confirm(`${kurzUrl(url)} an allen Tagen (${tageText(tage)}) entfernen?`)) return;
  listenBefehl("quellen", { aktion: "quellen_entfernen", tage, urls: [url] }, weg);
});

$("quellen-suche").addEventListener("input", () => { if (daten) zeichneQuellen(); });

// ---------------------------------------------------------------- Tags: Karten

function tagsModell() {
  const karten = [];
  const nachName = new Map();
  for (const t of daten.listen?.tags || []) {
    const k = { name: t.name, beschreibung: t.beschreibung || "", wartend: false, aendert: false, geht: false };
    karten.push(k);
    nachName.set(klein(t.name), k);
  }
  for (const b of offeneBefehle(["tag_hinzufuegen", "tag_entfernen"])) {
    let k = nachName.get(klein(b.tag));
    if (b.aktion === "tag_hinzufuegen") {
      if (!k) {
        k = { name: b.tag, beschreibung: "", wartend: true, aendert: false, geht: false };
        karten.push(k);
        nachName.set(klein(b.tag), k);
      } else {
        k.aendert = true;
      }
      k.beschreibung = b.beschreibung || "";
    } else if (k) {
      k.geht = true;
    }
  }
  return karten;
}

function kiHinweis() {
  const status = daten.bot.status;
  if (!status) return "";
  if (!("ki_modell" in status)) return " · Bot noch auf alter Version – bitte aktualisieren";
  return status.ki_modell
    ? ` · ${status.ki_modell} wählt pro Artikel die passenden Tags`
    : " · Kein API-Schlüssel: der Bot vergibt gerade keine Tags (config.toml → [llm] api_key)";
}

function zeichneTags() {
  const tags = daten.listen ? daten.listen.tags : null;
  $("zahl-tags").textContent = tags && tags.length ? String(tags.length) : "";
  meldeErgebnis("tags");
  const suche = klein($("tags-suche").value.trim());
  const offen = offeneBefehle(["tag_hinzufuegen", "tag_entfernen", "tags_importieren"]);
  const schluessel = JSON.stringify([tags, offen.map((b) => b.id), suche, daten.bot.online, daten.bot.status?.ki_modell]);
  if (schluessel === letzteAnsicht.tags) return;
  letzteAnsicht.tags = schluessel;

  $("tag-namen").replaceChildren(...(tags || []).map((t) => el("option", { value: t.name })));
  const modell = tagsModell();
  $("tags-info").textContent = !tags
    ? "Die Tags erscheinen, sobald der Bot verbunden ist. Anlegen kannst du trotzdem schon."
    : `${anzahl(tags.length, "Tag", "Tags")}${kiHinweis()} · Änderungen gelten ab der nächsten Prüfung`
      + (!daten.bot.online && offen.length ? " · Gestrichelte Änderungen werden übertragen, sobald der Bot läuft." : "");
  $("tags-ausstehend").replaceChildren(...[importHinweis(offen.filter((b) => b.aktion === "tags_importieren"))].filter(Boolean));

  const leer = $("tags-leer");
  leer.hidden = modell.length > 0;
  if (!modell.length) {
    leer.replaceChildren(
      el("p", { class: "leer-titel" }, "Noch keine Tags"),
      el("p", {}, "Lege Tags an oder importiere deinen Tag-Baum. Die KI liest jeden neuen Artikel und wählt die passenden Tags aus dieser Liste."));
  }
  const sichtbare = modell.filter((k) => !suche || klein(k.name).includes(suche) || klein(k.beschreibung).includes(suche));
  const raster = $("tags-karten");
  zeichneErhaltend(raster, () => raster.replaceChildren(...(sichtbare.length || !modell.length
    ? sichtbare.map(tagKarte)
    : [el("p", { class: "keine-treffer" }, "Kein Tag passt zur Suche.")])));
}

function tagKarte(k) {
  const schluessel = klein(k.name);
  let rechts;
  if (k.geht) rechts = [el("span", { class: "karte-status" }, "wird gelöscht")];
  else if (k.wartend) rechts = [el("span", { class: "karte-status" }, "wird angelegt")];
  else if (k.aendert) rechts = [el("span", { class: "karte-status" }, "wird geändert")];
  else {
    rechts = [
      el("button", { type: "button", class: "symbol-knopf karte-rechts", title: "Beschreibung bearbeiten", "aria-label": `Tag ${k.name} bearbeiten`,
        "data-bearbeiten": k.name, "data-fokus": `b|${schluessel}` }, symbol(ICON.stift)),
      el("button", { type: "button", class: "symbol-knopf gefahr", title: "Tag löschen", "aria-label": `Tag ${k.name} löschen`,
        "data-loeschen": k.name, "data-fokus": `l|${schluessel}` }, symbol(ICON.muell)),
    ];
  }
  return el("article", { class: `tag-karte${k.wartend || k.aendert ? " wartend" : ""}${k.geht ? " geht" : ""}`, "aria-label": `Tag ${k.name}` },
    el("header", { class: "karte-kopf" }, el("h3", { class: "karte-titel" }, k.name), ...rechts),
    k.beschreibung
      ? el("p", { class: "karte-beschreibung" }, k.beschreibung)
      : el("p", { class: "karte-beschreibung leise" }, "Ohne Beschreibung – die KI richtet sich nach dem Namen."));
}

/** Gleiche Regeln wie Server und Bot: Leerraum zusammenfassen, = + - @ am Anfang entfernen. */
function pruefeBeschreibung(text) {
  const t = einRaum(String(text ?? "")).replace(/^[=+\-@ ]+/, "");
  return t.length <= MAX_BESCHREIBUNG && !/[\p{C}\p{Zl}\p{Zp}]/u.test(t) ? t : null;
}

$("tags-karten").addEventListener("click", (e) => {
  const knopf = e.target.closest("button");
  if (!knopf) return;
  if (knopf.dataset.loeschen) {
    if (!confirm(`Tag „${knopf.dataset.loeschen}“ löschen?`)) return;
    listenBefehl("tags", { aktion: "tag_entfernen", tag: knopf.dataset.loeschen }, knopf);
  } else if (knopf.dataset.bearbeiten) {
    const t = (daten.listen?.tags || []).find((x) => x.name === knopf.dataset.bearbeiten);
    oeffneTagDialog(knopf.dataset.bearbeiten, t ? t.beschreibung : "");
  }
});

$("tags-suche").addEventListener("input", () => { if (daten) zeichneTags(); });

// ---------------------------------------------------------------- Dialoge

function oeffneDialog(dialog, fokus) {
  dialog.querySelectorAll(".dialog-fehler").forEach((p) => { p.textContent = ""; });
  dialog.showModal();
  if (fokus) fokus.focus();
}

document.querySelectorAll("dialog").forEach((dialog) => {
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog || e.target.closest("[data-schliessen]")) dialog.close();  // Klick daneben oder auf Schließen
  });
});

// ---- Quellen hinzufügen

$("tage-wahl").replaceChildren(...TAGE.map(([k, lang, kurz]) =>
  el("label", { class: "tag-chip", title: lang },
    el("input", { type: "checkbox", value: k, "aria-label": lang }),
    el("span", { "aria-hidden": "true" }, kurz))));

document.querySelectorAll("[data-tage]").forEach((knopf) => knopf.addEventListener("click", () => {
  const auswahl = { werktage: WERKTAGE, alle: TAGE.map(([k]) => k), keine: [] }[knopf.dataset.tage];
  document.querySelectorAll("#tage-wahl input").forEach((c) => { c.checked = auswahl.includes(c.value); });
}));

$("quellen-neu").addEventListener("click", () => oeffneDialog($("dialog-quellen"), $("quellen-urls")));

$("quellen-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fehler = $("quellen-fehler");
  const eintraege = [...new Set($("quellen-urls").value.split(/\s+/).filter(Boolean))];
  const tage = [...document.querySelectorAll("#tage-wahl input:checked")].map((c) => c.value);
  const falsch = eintraege.filter((u) => !pruefeUrl(u));
  let problem = "";
  if (!eintraege.length) problem = "Bitte mindestens eine Adresse eintragen.";
  else if (falsch.length) problem = `Nicht erlaubt: ${falsch.slice(0, 3).join(", ")}. Nur http(s)-Adressen öffentlicher Webseiten, keine Adressen aus dem eigenen Netz.`;
  else if (!tage.length) problem = "Bitte mindestens einen Wochentag auswählen.";
  else if (eintraege.length * tage.length > MAX_QUELLEN) problem = `Höchstens ${MAX_QUELLEN} Einträge auf einmal.`;
  fehler.textContent = problem;
  if (problem) return;
  const urls = [...new Set(eintraege.map(pruefeUrl))];
  const body = urls.length <= MAX_PRO_BEFEHL
    ? { aktion: "quellen_hinzufuegen", tage, urls }
    : { aktion: "quellen_importieren", quellen: tage.flatMap((t) => urls.map((url) => ({ wochentag: t, url }))) };
  if (await listenBefehl("quellen", body, e.submitter)) {
    $("quellen-urls").value = "";
    $("dialog-quellen").close();
  } else {
    fehler.textContent = $("quellen-rueck").textContent;
  }
});

// ---- Tag anlegen oder bearbeiten

function oeffneTagDialog(name, beschreibung) {
  const bearbeiten = name !== null;
  $("dialog-tag-titel").textContent = bearbeiten ? "Tag bearbeiten" : "Neuer Tag";
  $("tag-name").value = bearbeiten ? name : "";
  $("tag-name").readOnly = bearbeiten;
  $("tag-beschreibung").value = beschreibung || "";
  $("tag-name-hinweis").textContent = "";
  oeffneDialog($("dialog-tag"), bearbeiten ? $("tag-beschreibung") : $("tag-name"));
}

$("tag-name").addEventListener("input", () => {
  const name = einRaum($("tag-name").value);
  const vorhanden = (daten?.listen?.tags || []).find((t) => klein(t.name) === klein(name));
  $("tag-name-hinweis").textContent = vorhanden ? `„${vorhanden.name}“ gibt es schon – die Beschreibung wird ersetzt.` : "";
});

$("tag-neu").addEventListener("click", () => oeffneTagDialog(null, ""));

$("tag-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fehler = $("tag-fehler");
  const name = einRaum($("tag-name").value);
  const beschreibung = pruefeBeschreibung($("tag-beschreibung").value);
  let problem = "";
  if (!name) problem = "Bitte einen Namen eintragen.";
  else if (!TAG_MUSTER.test(name)) problem = "Name: höchstens 80 Zeichen – Buchstaben, Ziffern, Leerzeichen und - . , : & / ' + ( ) [ ]; am Anfang ein Buchstabe, eine Ziffer oder eine Klammer.";
  else if (beschreibung === null) problem = `Beschreibung: höchstens ${MAX_BESCHREIBUNG} Zeichen, ohne Steuerzeichen.`;
  fehler.textContent = problem;
  if (problem) return;
  if (await listenBefehl("tags", { aktion: "tag_hinzufuegen", tag: name, beschreibung }, e.submitter)) $("dialog-tag").close();
  else fehler.textContent = $("tags-rueck").textContent;
});

// ---------------------------------------------------------------- Datei-Import (CSV und JSON)

let importArt = "quellen";
let importBereit = null;  // fertiger Befehl, der beim Klick auf „Importieren“ gesendet wird

const FORMATE = {
  quellen: [
    ["CSV, eine Zeile pro Quelle und Tag (wie quellen.csv)", "Wochentag;URL\nMontag;https://derstandard.at\nMontag;orf.at/rss\nDienstag;heise.de"],
    ["CSV mit einer Spalte pro Tag (wie die alte Excel)", "Montag;Dienstag;Mittwoch\nderstandard.at;orf.at;heise.de\norf.at;;futurezone.at"],
    ["JSON nach Tagen", '{\n  "montag": ["derstandard.at", "orf.at/rss"],\n  "dienstag": ["heise.de"]\n}'],
    ["JSON als Liste", '[\n  {"wochentag": "montag", "url": "derstandard.at"},\n  {"wochentag": "dienstag", "url": "heise.de"}\n]'],
  ],
  tags: [
    ["CSV, eine Zeile pro Tag (wie tags.csv) – Beschreibung freiwillig", "Tag;Beschreibung\nRansomware;Erpressung mit Schadsoftware\nÖsterreich;"],
    ["CSV aus dem Tag-Baum (tags-import/tags.csv) – der Pfad wird zur Beschreibung", "Tag;Pfad\nCyber;Cyber\nBauteil;Cyber > Cyber Infrastruktur > Hardware > Bauteil"],
    ["JSON-Baum (tags-import/tags.json)", '[\n  {"tag": "Cyber", "untertags": [\n    {"tag": "Cyber Security", "untertags": []}\n  ]}\n]'],
    ["JSON als Liste", '[\n  {"name": "Ransomware", "beschreibung": "Erpressung mit Schadsoftware"},\n  "Österreich"\n]'],
    ["JSON nach Tags", '{\n  "Ransomware": "Erpressung mit Schadsoftware",\n  "Österreich": ""\n}'],
  ],
};

function liesCsv(text) {
  const erste = text.split(/\r?\n/, 1)[0];
  const trenner = erste.includes(";") ? ";" : erste.includes("\t") ? "\t" : erste.includes(",") ? "," : ";";
  const zeilen = [];
  let zeile = [];
  let feld = "";
  let inAnfuehrung = false;
  for (let i = 0; i < text.length && zeilen.length < MAX_DATEI_ZEILEN; i++) {
    const c = text[i];
    if (inAnfuehrung) {
      if (c !== '"') feld += c;
      else if (text[i + 1] === '"') { feld += '"'; i++; }
      else inAnfuehrung = false;
    } else if (c === '"' && !feld.trim()) {
      inAnfuehrung = true;
      feld = "";
    } else if (c === trenner) {
      zeile.push(feld);
      feld = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      zeile.push(feld);
      zeilen.push(zeile);
      zeile = [];
      feld = "";
    } else {
      feld += c;
    }
  }
  if (feld || zeile.length) zeilen.push([...zeile, feld]);
  return zeilen.map((z) => z.map((f) => f.trim())).filter((z) => z.some(Boolean));
}

const istJson = (name, text) => /\.json$/i.test(name) || /^\s*[[{]/.test(text);

function liesJson(text) {
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`Die JSON-Datei ist fehlerhaft (${e.message}).`);
  }
}

const alsListe = (wert) => (Array.isArray(wert) ? wert : wert == null ? [] : [wert]);
const istObjekt = (wert) => wert !== null && typeof wert === "object" && !Array.isArray(wert);

/** Liefert [[wochentag-text, url-text], …] aus jedem unterstützten Format. */
function quellenRohdaten(name, text) {
  const roh = [];
  if (istJson(name, text)) {
    let d = liesJson(text);
    if (istObjekt(d) && "quellen" in d) d = d.quellen;
    if (Array.isArray(d)) {
      for (const e of d.slice(0, MAX_DATEI_ZEILEN)) roh.push(istObjekt(e) ? [e.wochentag ?? e.tag ?? e.day, e.url] : [null, e]);
    } else if (istObjekt(d)) {
      for (const [tag, urls] of Object.entries(d)) for (const u of alsListe(urls).slice(0, MAX_DATEI_ZEILEN)) roh.push([tag, u]);
    } else {
      throw new Error("Unbekanntes JSON-Format – siehe „Welche Formate werden erkannt?“.");
    }
    return roh;
  }
  const zeilen = liesCsv(text);
  const kopf = (zeilen[0] || []).map(wochentagAus);
  const spaltenFormat = kopf.some(Boolean) && zeilen[0].every((zelle, i) => !zelle || kopf[i]);
  if (spaltenFormat) {
    for (const z of zeilen.slice(1)) z.forEach((u, i) => { if (u && kopf[i]) roh.push([kopf[i], u]); });
  } else {
    const start = zeilen.length && /^(wochentag|tag|day)$/i.test(zeilen[0][0]) ? 1 : 0;
    for (const z of zeilen.slice(start)) roh.push([z[0], z[1]]);
  }
  return roh;
}

/** Liefert [[tag-text, beschreibung-text], …] aus jedem unterstützten Format.
 *  Schlagwörter aus Dateien im alten Format werden ignoriert – die Tags vergibt jetzt die KI. */
function tagsRohdaten(name, text) {
  const roh = [];
  const textAus = (wert) => (typeof wert === "string" ? wert : "");
  const baum = (knoten, pfad) => {  // [{"tag": …, "untertags": […]}] → Pfad als Beschreibung
    for (const k of alsListe(knoten)) {
      if (roh.length >= MAX_DATEI_ZEILEN) return;
      if (!istObjekt(k)) { roh.push([k, ""]); continue; }
      const weg = [...pfad, String(k.tag ?? k.name ?? "")];
      roh.push([k.tag ?? k.name, weg.length > 1 ? weg.join(" > ") : textAus(k.beschreibung)]);
      baum(k.untertags ?? k.kinder ?? k.children ?? [], weg);
    }
  };
  if (istJson(name, text)) {
    let d = liesJson(text);
    if (istObjekt(d) && "tags" in d) d = d.tags;
    if (Array.isArray(d) && d.some((e) => istObjekt(e) && ("untertags" in e || "children" in e || "kinder" in e))) {
      baum(d, []);
    } else if (Array.isArray(d)) {
      for (const e of d.slice(0, MAX_DATEI_ZEILEN)) {
        if (istObjekt(e)) roh.push([e.name ?? e.tag, textAus(e.beschreibung ?? e.pfad ?? e.description)]);
        else roh.push([e, ""]);
      }
    } else if (istObjekt(d)) {
      for (const [tag, wert] of Object.entries(d)) roh.push([tag, textAus(wert)]);  // alte Form {Tag: [Schlagwörter]} → ohne Beschreibung
    } else {
      throw new Error("Unbekanntes JSON-Format – siehe „Welche Formate werden erkannt?“.");
    }
    return roh;
  }
  const zeilen = liesCsv(text);
  const kopf = zeilen.length && /^(tag|name)$/i.test(zeilen[0][0]) ? zeilen[0] : null;
  const altesFormat = kopf && /^schlagw/i.test(kopf[1] || "");  // Tag;Schlagwort → Schlagwörter weglassen
  for (const z of zeilen.slice(kopf ? 1 : 0)) roh.push([z[0], altesFormat ? "" : z[1] || ""]);
  return roh;
}

const zeigeText = (wert) => (typeof wert === "string" || typeof wert === "number" ? String(wert) : "?").slice(0, 80);

function bereiteQuellenVor(roh) {
  const fehler = [];
  const gesehen = new Set();
  const gueltig = [];
  for (const [tagText, urlText] of roh) {
    const tag = wochentagAus(tagText);
    const url = typeof urlText === "string" ? pruefeUrl(urlText) : null;
    const anzeige = `${zeigeText(tagText)} · ${zeigeText(urlText)}`;
    if (!tag) fehler.push([anzeige, "kein gültiger Wochentag"]);
    else if (!url) fehler.push([anzeige, "Adresse nicht erlaubt"]);
    else if (!gesehen.has(`${tag}|${url}`)) {
      gesehen.add(`${tag}|${url}`);
      gueltig.push({ wochentag: tag, url });
    }
  }
  const bekannt = daten?.listen ? new Set(daten.listen.quellen.map((q) => `${q.wochentag}|${q.url}`)) : null;
  const neu = bekannt ? gueltig.filter((q) => !bekannt.has(`${q.wochentag}|${q.url}`)) : gueltig;
  const platz = MAX_QUELLEN - (bekannt ? bekannt.size : 0);
  const senden = neu.slice(0, Math.max(0, platz));

  const proTag = TAGE.map(([k, , kurz]) => [kurz, senden.filter((q) => q.wochentag === k).length]).filter(([, n]) => n);
  const zahlen = [
    [gueltig.length, "erkannt"],
    [senden.length, "neu"],
    [gueltig.length - neu.length, "schon vorhanden"],
    [neu.length - senden.length, "über dem Limit"],
    [fehler.length, "übersprungen"],
  ];
  return {
    befehl: senden.length ? { aktion: "quellen_importieren", quellen: senden } : null,
    knopf: `${anzahl(senden.length, "Eintrag", "Einträge")} importieren`,
    zahlen, fehler,
    details: proTag.length ? el("ul", { class: "vorschau-chips", "aria-label": "Neue Einträge pro Tag" },
      ...proTag.map(([kurz, n]) => el("li", {}, el("strong", {}, kurz), ` ${n}`))) : null,
    hinweis: bekannt ? "" : "Der Bot ist noch nicht verbunden – doppelte Einträge erkennt er beim Eintragen selbst.",
  };
}

/** Zwei Beschreibungen desselben Tags verbinden (gleicher Name an zwei Stellen im Tag-Baum). */
function verbinde(alt, neu) {
  if (!neu || klein(alt).includes(klein(neu))) return alt;
  if (!alt) return neu;
  const zusammen = `${alt} | ${neu}`;
  return zusammen.length <= MAX_BESCHREIBUNG ? zusammen : alt;
}

function bereiteTagsVor(roh) {
  const fehler = [];
  const tags = new Map();  // klein(name) → { name, beschreibung }
  let zuViel = 0;
  for (const [nameText, beschreibungText] of roh) {
    const name = typeof nameText === "string" ? einRaum(nameText) : "";
    let beschreibung = pruefeBeschreibung(beschreibungText);
    if (!TAG_MUSTER.test(name)) {
      fehler.push([zeigeText(nameText), "Tag-Name nicht erlaubt"]);
      continue;
    }
    if (beschreibung === null) {
      fehler.push([`${name} · ${zeigeText(beschreibungText)}`, "Beschreibung nicht erlaubt"]);
      continue;
    }
    if (klein(beschreibung) === klein(name)) beschreibung = "";  // oberste Ebene im Tag-Baum: Pfad = Name
    const t = tags.get(klein(name));
    if (t) t.beschreibung = verbinde(t.beschreibung, beschreibung);
    else if (tags.size >= MAX_TAGS) zuViel++;
    else tags.set(klein(name), { name, beschreibung });
  }
  const bekannt = new Map((daten?.listen?.tags || []).map((t) => [klein(t.name), t.beschreibung || ""]));
  const neu = [];
  const geaendert = [];
  let vorhanden = 0;
  for (const t of tags.values()) {
    if (!bekannt.has(klein(t.name))) neu.push(t);
    else if (t.beschreibung && t.beschreibung !== bekannt.get(klein(t.name))) geaendert.push(t);
    else vorhanden++;
  }
  const platz = Math.max(0, MAX_TAGS - bekannt.size);
  const senden = [...neu.slice(0, platz), ...geaendert];
  zuViel += neu.length - Math.min(neu.length, platz);
  const neuGesendet = Math.min(neu.length, platz);
  return {
    befehl: senden.length ? { aktion: "tags_importieren", tags: senden } : null,
    knopf: `${anzahl(senden.length, "Tag", "Tags")} importieren`,
    zahlen: [[tags.size, "Tags erkannt"], [neuGesendet, "neu"], [geaendert.length, "Beschreibung geändert"],
      [vorhanden, "schon vorhanden"], [zuViel, "über dem Limit"], [fehler.length, "übersprungen"]],
    fehler,
    details: senden.length ? el("ul", { class: "vorschau-chips", "aria-label": "Neue oder geänderte Tags" },
      ...senden.slice(0, 30).map((t) => el("li", { title: t.beschreibung }, el("strong", {}, t.name))),
      senden.length > 30 ? el("li", {}, `… ${senden.length - 30} weitere`) : null) : null,
    hinweis: daten?.listen ? "" : "Der Bot ist noch nicht verbunden – vorhandene Tags erkennt er beim Eintragen selbst.",
  };
}

function zeigeVorschau(v) {
  const vorschau = $("import-vorschau");
  vorschau.hidden = false;
  vorschau.replaceChildren(...[
    el("ul", { class: "vorschau-zahlen" }, ...v.zahlen.filter(([n], i) => n || i < 2).map(([n, text]) =>
      el("li", {}, el("strong", {}, String(n)), ` ${text}`))),
    v.details,
    v.hinweis ? el("p", { class: "feld-hilfe" }, v.hinweis) : null,
    v.fehler.length ? el("details", { class: "vorschau-fehler" },
      el("summary", {}, `${anzahl(v.fehler.length, "Eintrag wird", "Einträge werden")} übersprungen – anzeigen`),
      el("ul", {}, ...v.fehler.slice(0, 50).map(([text, grund]) => el("li", {}, el("span", {}, text), el("small", {}, grund))),
        v.fehler.length > 50 ? el("li", {}, `… und ${v.fehler.length - 50} weitere`) : null)) : null,
  ].filter(Boolean));
  importBereit = v.befehl;
  const start = $("import-start");
  start.disabled = !v.befehl;
  start.textContent = v.befehl ? v.knopf : "Nichts Neues zu importieren";
}

async function liesDateiText(datei) {
  if (datei.size > MAX_DATEI_BYTES) throw new Error("Die Datei ist größer als 2 MB.");
  const puffer = await datei.arrayBuffer();
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(puffer);
  } catch {
    text = new TextDecoder("windows-1252").decode(puffer);  // so speichert Excel „CSV (Trennzeichen-getrennt)“
  }
  return text.replace(/^﻿/, "");
}

async function verarbeiteDatei(datei) {
  const fehler = $("import-fehler");
  fehler.textContent = "";
  importBereit = null;
  $("import-start").disabled = true;
  $("import-vorschau").hidden = true;
  $("import-dateiname").textContent = `${datei.name} · ${Math.max(1, Math.round(datei.size / 1024))} KB`;
  try {
    if (!/\.(csv|json|txt)$/i.test(datei.name)) throw new Error("Bitte eine .csv- oder .json-Datei wählen.");
    const text = await liesDateiText(datei);
    const roh = importArt === "quellen" ? quellenRohdaten(datei.name, text) : tagsRohdaten(datei.name, text);
    if (!roh.length) throw new Error(`In der Datei wurden keine ${importArt === "quellen" ? "Quellen" : "Tags"} gefunden.`);
    zeigeVorschau(importArt === "quellen" ? bereiteQuellenVor(roh) : bereiteTagsVor(roh));
  } catch (e) {
    fehler.textContent = e.message;
  }
}

document.querySelectorAll("[data-import]").forEach((knopf) => knopf.addEventListener("click", () => {
  importArt = knopf.dataset.import;
  importBereit = null;
  $("import-titel").textContent = importArt === "quellen" ? "Quellen importieren" : "Tags importieren";
  $("import-datei").value = "";
  $("import-dateiname").textContent = "CSV oder JSON, höchstens 2 MB";
  $("import-vorschau").hidden = true;
  $("import-start").disabled = true;
  $("import-start").textContent = "Importieren";
  $("import-formate").replaceChildren(...FORMATE[importArt].map(([titel, beispiel]) =>
    el("div", { class: "format" }, el("p", {}, titel), el("pre", {}, beispiel))));
  oeffneDialog($("dialog-import"), $("import-datei"));
}));

$("import-datei").addEventListener("change", (e) => { if (e.target.files[0]) verarbeiteDatei(e.target.files[0]); });

const ablage = $("import-ablage");
ablage.addEventListener("dragover", (e) => { e.preventDefault(); ablage.classList.add("ziehen"); });
ablage.addEventListener("dragleave", () => ablage.classList.remove("ziehen"));
ablage.addEventListener("drop", (e) => {
  e.preventDefault();
  ablage.classList.remove("ziehen");
  if (e.dataTransfer.files[0]) verarbeiteDatei(e.dataTransfer.files[0]);
});

$("import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!importBereit) return;
  if (await listenBefehl(importArt, importBereit, e.submitter)) $("dialog-import").close();
  else $("import-fehler").textContent = $(`${importArt}-rueck`).textContent;
});
