"use strict";
// Quellen und Tags verwalten: Tabelle, Karten, Dialoge und Datei-Import.
// Alles wird über el()/textContent angezeigt – nie als HTML. Dateien werden nur hier im Browser
// gelesen; an den Server gehen ausschließlich geprüfte Texte. Server und Bot prüfen trotzdem
// jede Änderung noch einmal selbst.

const MAX_PRO_BEFEHL = 50;        // darüber wird automatisch als Import geschickt
const MAX_QUELLEN = 700;
const MAX_TAGS = 100;
const MAX_WOERTER_PRO_TAG = 100;
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
const kartenEntwuerfe = new Map();                // angefangene Eingaben in Tag-Karten überleben das Neuzeichnen

// ---------------------------------------------------------------- Kleinteile

const SVG_NS = "http://www.w3.org/2000/svg";
const ICON = {
  haken: ["M20 6 9 17l-5-5"],
  muell: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6", "M10 11v6", "M14 11v6"],
  plus: ["M12 5v14", "M5 12h14"],
  x: ["M18 6 6 18", "m6 6 12 12"],
  extern: ["M15 3h6v6", "M10 14 21 3", "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"],
  pfeil: ["m6 9 6 6 6-6"],
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
    const k = { name: t.name, woerter: t.woerter.map((w) => ({ w, zustand: "da" })), wartend: false, geht: false };
    karten.push(k);
    nachName.set(klein(t.name), k);
  }
  for (const b of offeneBefehle(["tag_hinzufuegen", "tag_entfernen"])) {
    let k = nachName.get(klein(b.tag));
    if (b.aktion === "tag_hinzufuegen") {
      if (!k) {
        k = { name: b.tag, woerter: [], wartend: true, geht: false };
        karten.push(k);
        nachName.set(klein(b.tag), k);
      }
      for (const w of b.woerter) if (!k.woerter.some((x) => klein(x.w) === klein(w))) k.woerter.push({ w, zustand: "kommt" });
    } else if (k) {
      if (!b.woerter.length) k.geht = true;
      for (const x of k.woerter) if (b.woerter.some((w) => klein(w) === klein(x.w))) x.zustand = "geht";
    }
  }
  return karten;
}

function zeichneTags() {
  const tags = daten.listen ? daten.listen.tags : null;
  $("zahl-tags").textContent = tags && tags.length ? String(tags.length) : "";
  meldeErgebnis("tags");
  const suche = klein($("tags-suche").value.trim());
  const offen = offeneBefehle(["tag_hinzufuegen", "tag_entfernen", "tags_importieren"]);
  const schluessel = JSON.stringify([tags, offen.map((b) => b.id), suche, daten.bot.online]);
  if (schluessel === letzteAnsicht.tags) return;
  letzteAnsicht.tags = schluessel;

  $("tag-namen").replaceChildren(...(tags || []).map((t) => el("option", { value: t.name })));
  const modell = tagsModell();
  const woerterGesamt = (tags || []).reduce((n, t) => n + t.woerter.length, 0);
  $("tags-info").textContent = !tags
    ? "Die Tags erscheinen, sobald der Bot verbunden ist. Anlegen kannst du trotzdem schon."
    : `${anzahl(tags.length, "Tag", "Tags")} mit ${anzahl(woerterGesamt, "Schlagwort", "Schlagwörtern")} · gelten ab der nächsten Prüfung`
      + (!daten.bot.online && offen.length ? " · Gestrichelte Änderungen werden übertragen, sobald der Bot läuft." : "");
  $("tags-ausstehend").replaceChildren(...[importHinweis(offen.filter((b) => b.aktion === "tags_importieren"))].filter(Boolean));

  const leer = $("tags-leer");
  leer.hidden = modell.length > 0;
  if (!modell.length) {
    leer.replaceChildren(
      el("p", { class: "leer-titel" }, "Noch keine Tags"),
      el("p", {}, "Tags markieren Artikel, deren Titel oder Vorschau eines ihrer Schlagwörter enthält."));
  }
  const sichtbare = modell.filter((k) => !suche || klein(k.name).includes(suche) || k.woerter.some((x) => klein(x.w).includes(suche)));
  const raster = $("tags-karten");
  zeichneErhaltend(raster, () => raster.replaceChildren(...(sichtbare.length || !modell.length
    ? sichtbare.map((k) => tagKarte(k, suche))
    : [el("p", { class: "keine-treffer" }, "Kein Tag passt zur Suche.")])));
}

function tagKarte(k, suche) {
  const schluessel = klein(k.name);
  const chips = k.woerter.map(({ w, zustand }) => {
    const text = w.endsWith("*")
      ? [w.slice(0, -1), el("span", { class: "stern", title: "Wortanfang – findet auch längere Wörter" }, "*")]
      : [w];
    const treffer = suche && klein(w).includes(suche) ? " treffer" : "";
    return el("li", { class: `wort ${zustand}${treffer}` }, ...text,
      zustand === "da" && !k.geht
        ? el("button", { type: "button", class: "wort-weg", title: "Entfernen", "aria-label": `${w} aus ${k.name} entfernen`,
          "data-tag": k.name, "data-wort": w, "data-fokus": `w|${schluessel}|${klein(w)}` }, symbol(ICON.x, 14))
        : null);
  });

  const eingabe = el("input", { type: "text", class: "karte-feld", placeholder: "Schlagwort hinzufügen", maxlength: "600",
    autocomplete: "off", spellcheck: "false", autocapitalize: "off", "aria-label": `Schlagwort zu ${k.name} hinzufügen`,
    "data-tag": k.name, "data-fokus": `e|${schluessel}` });
  eingabe.value = kartenEntwuerfe.get(schluessel) || "";

  let rechts;
  if (k.geht) rechts = el("span", { class: "karte-status" }, "wird gelöscht");
  else if (k.wartend) rechts = el("span", { class: "karte-status" }, "wird angelegt");
  else rechts = el("button", { type: "button", class: "symbol-knopf gefahr", title: "Tag löschen", "aria-label": `Tag ${k.name} löschen`,
    "data-loeschen": k.name, "data-fokus": `l|${schluessel}` }, symbol(ICON.muell));

  return el("article", { class: `tag-karte${k.wartend ? " wartend" : ""}${k.geht ? " geht" : ""}`, "aria-label": `Tag ${k.name}` },
    el("header", { class: "karte-kopf" },
      el("h3", { class: "karte-titel" }, k.name),
      el("span", { class: "zahl" }, String(k.woerter.length)),
      rechts),
    k.woerter.length ? el("ul", { class: "woerter" }, ...chips) : el("p", { class: "leise klein" }, "Keine Schlagwörter."),
    k.geht ? null : el("form", { class: "karte-eingabe", "data-tag": k.name, novalidate: "" },
      eingabe,
      el("button", { type: "submit", class: "symbol-knopf", title: "Hinzufügen", "aria-label": `Zu ${k.name} hinzufügen` }, symbol(ICON.plus))),
    el("p", { class: "karte-fehler", role: "alert" }));
}

/** Text in Schlagwörter zerlegen. Gibt [gültige, ungültige] zurück. */
function zerlegeWoerter(text) {
  const teile = [...new Set(String(text).split(/[,;\n]+/).map(einRaum).filter(Boolean))];
  return [teile.filter((w) => WORT_MUSTER.test(w)), teile.filter((w) => !WORT_MUSTER.test(w))];
}

const WORT_REGEL = "nur Buchstaben, Ziffern, Leerzeichen, - . & / ' + und * am Ende; am Anfang ein Buchstabe oder eine Ziffer";

function tagBefehl(name, woerter) {
  // Mehr als 50 Wörter auf einmal gehen als Import – dafür gilt die 50er-Grenze nicht.
  return woerter.length <= MAX_PRO_BEFEHL
    ? { aktion: "tag_hinzufuegen", tag: name, woerter }
    : { aktion: "tags_importieren", tags: [{ name, woerter: woerter.slice(0, MAX_WOERTER_PRO_TAG) }] };
}

$("tags-karten").addEventListener("submit", async (e) => {
  const form = e.target.closest("form.karte-eingabe");
  if (!form) return;
  e.preventDefault();
  const feld = form.querySelector("input");
  const fehler = form.parentElement.querySelector(".karte-fehler");
  const [gute, falsche] = zerlegeWoerter(feld.value);
  fehler.textContent = falsche.length ? `Nicht erlaubt: ${falsche.slice(0, 3).join(", ")} – ${WORT_REGEL}.` : "";
  if (falsche.length || !gute.length) return;
  if (await listenBefehl("tags", tagBefehl(form.dataset.tag, gute), form.querySelector("button"))) {
    kartenEntwuerfe.delete(klein(form.dataset.tag));
    feld.value = "";
  }
});

$("tags-karten").addEventListener("input", (e) => {
  if (e.target.matches("input.karte-feld")) kartenEntwuerfe.set(klein(e.target.dataset.tag), e.target.value);
});

$("tags-karten").addEventListener("click", (e) => {
  const knopf = e.target.closest("button");
  if (!knopf) return;
  if (knopf.dataset.loeschen) {
    if (!confirm(`Tag „${knopf.dataset.loeschen}“ mit allen Schlagwörtern löschen?`)) return;
    listenBefehl("tags", { aktion: "tag_entfernen", tag: knopf.dataset.loeschen, woerter: [] }, knopf);
  } else if (knopf.dataset.wort) {
    listenBefehl("tags", { aktion: "tag_entfernen", tag: knopf.dataset.tag, woerter: [knopf.dataset.wort] }, knopf);
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

// ---- Neuer Tag (Schlagwörter als Chips)

const neueWoerter = [];

function zeichneTagChips() {
  $("tag-chip-liste").replaceChildren(...neueWoerter.map((w, i) =>
    el("li", { class: "wort da" }, w,
      el("button", { type: "button", class: "wort-weg", title: "Entfernen", "aria-label": `${w} entfernen`, "data-index": String(i) },
        symbol(ICON.x, 14)))));
}

/** Übernimmt vollständige Wörter aus dem Eingabefeld; Ungültiges bleibt zum Korrigieren stehen. */
function uebernimmWoerter(alles) {
  const feld = $("tag-wort-eingabe");
  const teile = feld.value.split(/[,;\n]/);
  const rest = alles ? "" : teile.pop();
  const [gute, falsche] = zerlegeWoerter(teile.join(","));
  for (const w of gute) if (!neueWoerter.some((x) => klein(x) === klein(w))) neueWoerter.push(w);
  feld.value = [...falsche, rest].filter(Boolean).join(", ");
  $("tag-fehler").textContent = falsche.length ? `Nicht erlaubt: ${falsche.slice(0, 3).join(", ")} – ${WORT_REGEL}.` : "";
  zeichneTagChips();
  return falsche.length === 0;
}

$("tag-wort-eingabe").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    uebernimmWoerter(true);
  } else if (e.key === "Backspace" && !e.target.value && neueWoerter.length) {
    neueWoerter.pop();
    zeichneTagChips();
  }
});
$("tag-wort-eingabe").addEventListener("input", (e) => { if (/[,;\n]/.test(e.target.value)) uebernimmWoerter(false); });
$("tag-chip-liste").addEventListener("click", (e) => {
  const knopf = e.target.closest("button[data-index]");
  if (!knopf) return;
  neueWoerter.splice(Number(knopf.dataset.index), 1);
  zeichneTagChips();
  $("tag-wort-eingabe").focus();
});
$("tag-name").addEventListener("input", () => {
  const name = einRaum($("tag-name").value);
  const vorhanden = (daten?.listen?.tags || []).find((t) => klein(t.name) === klein(name));
  $("tag-name-hinweis").textContent = vorhanden ? `„${vorhanden.name}“ gibt es schon – die Schlagwörter werden dort ergänzt.` : "";
});

$("tag-neu").addEventListener("click", () => {
  neueWoerter.length = 0;
  zeichneTagChips();
  $("tag-name").value = "";
  $("tag-wort-eingabe").value = "";
  $("tag-name-hinweis").textContent = "";
  oeffneDialog($("dialog-tag"), $("tag-name"));
});

$("tag-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fehler = $("tag-fehler");
  if (!uebernimmWoerter(true)) return;
  const name = einRaum($("tag-name").value);
  let problem = "";
  if (!name) problem = "Bitte einen Namen eintragen.";
  else if (!TAG_MUSTER.test(name)) problem = "Name: nur Buchstaben, Ziffern, Leerzeichen und - . & / ' + (höchstens 40 Zeichen, am Anfang ein Buchstabe oder eine Ziffer).";
  else if (!neueWoerter.length) problem = "Bitte mindestens ein Schlagwort eintragen.";
  fehler.textContent = problem;
  if (problem) return;
  if (await listenBefehl("tags", tagBefehl(name, [...neueWoerter]), e.submitter)) $("dialog-tag").close();
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
    ["CSV, eine Zeile pro Schlagwort (wie tags.csv)", "Tag;Schlagwort\nCyberkriminalität;cyber*\nCyberkriminalität;ransomware\nÖsterreich;wien*"],
    ["CSV, alle Schlagwörter in einer Zeile", "Tag;Schlagwörter\nCyberkriminalität;cyber*, ransomware, phishing\nÖsterreich;wien*;graz*"],
    ["JSON nach Tags", '{\n  "Cyberkriminalität": ["cyber*", "ransomware"],\n  "Österreich": ["wien*"]\n}'],
    ["JSON als Liste", '[\n  {"name": "Österreich", "woerter": ["wien*", "graz*"]}\n]'],
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

/** Liefert [[tag-text, [wort-text, …]], …] aus jedem unterstützten Format. */
function tagsRohdaten(name, text) {
  const roh = [];
  const woerterAus = (wert) => alsListe(wert).flatMap((w) => (typeof w === "string" ? w.split(/[,;]/) : [w]));
  if (istJson(name, text)) {
    let d = liesJson(text);
    if (istObjekt(d) && "tags" in d) d = d.tags;
    if (Array.isArray(d)) {
      for (const e of d.slice(0, MAX_DATEI_ZEILEN)) {
        if (istObjekt(e)) roh.push([e.name ?? e.tag, woerterAus(e.woerter ?? e.schlagwoerter ?? e["schlagwörter"] ?? e.keywords ?? e.words)]);
        else roh.push([e, []]);
      }
    } else if (istObjekt(d)) {
      for (const [tag, woerter] of Object.entries(d)) roh.push([tag, woerterAus(woerter)]);
    } else {
      throw new Error("Unbekanntes JSON-Format – siehe „Welche Formate werden erkannt?“.");
    }
    return roh;
  }
  const zeilen = liesCsv(text);
  const start = zeilen.length && /^(tag|name)$/i.test(zeilen[0][0]) ? 1 : 0;
  for (const z of zeilen.slice(start)) roh.push([z[0], woerterAus(z.slice(1))]);
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

function bereiteTagsVor(roh) {
  const fehler = [];
  const tags = new Map();  // klein(name) → { name, woerter: Map(klein → wort) }
  let zuViel = 0;
  for (const [nameText, woerter] of roh) {
    const name = typeof nameText === "string" ? einRaum(nameText) : "";
    if (!TAG_MUSTER.test(name)) {
      fehler.push([zeigeText(nameText), "Tag-Name nicht erlaubt"]);
      continue;
    }
    if (!tags.has(klein(name))) {
      if (tags.size >= MAX_TAGS) { zuViel += woerter.length; continue; }
      tags.set(klein(name), { name, woerter: new Map() });
    }
    const t = tags.get(klein(name));
    for (const w of woerter) {
      const wort = typeof w === "string" ? einRaum(w) : "";
      if (!wort) continue;
      if (!WORT_MUSTER.test(wort)) fehler.push([`${name} · ${zeigeText(w)}`, "Schlagwort nicht erlaubt"]);
      else if (t.woerter.size >= MAX_WOERTER_PRO_TAG) zuViel++;
      else t.woerter.set(klein(wort), wort);
    }
  }
  const bekannt = new Map((daten?.listen?.tags || []).map((t) => [klein(t.name), new Set(t.woerter.map(klein))]));
  const senden = [];
  let erkannt = 0;
  let vorhanden = 0;
  for (const t of tags.values()) {
    erkannt += t.woerter.size;
    const alt = bekannt.get(klein(t.name)) || new Set();
    const neu = [...t.woerter.values()].filter((w) => !alt.has(klein(w)));
    vorhanden += t.woerter.size - neu.length;
    if (neu.length) senden.push({ name: t.name, woerter: neu });
  }
  const neueWoerterZahl = senden.reduce((n, t) => n + t.woerter.length, 0);
  const neueTags = senden.filter((t) => !bekannt.has(klein(t.name)));
  return {
    befehl: senden.length ? { aktion: "tags_importieren", tags: senden } : null,
    knopf: `${anzahl(neueWoerterZahl, "Schlagwort", "Schlagwörter")} importieren`,
    zahlen: [[erkannt, "Schlagwörter erkannt"], [neueWoerterZahl, "neu"], [neueTags.length, neueTags.length === 1 ? "neuer Tag" : "neue Tags"],
      [vorhanden, "schon vorhanden"], [zuViel, "über dem Limit"], [fehler.length, "übersprungen"]],
    fehler,
    details: senden.length ? el("ul", { class: "vorschau-chips", "aria-label": "Tags mit neuen Schlagwörtern" },
      ...senden.slice(0, 30).map((t) => el("li", {}, el("strong", {}, t.name), ` +${t.woerter.length}`)),
      senden.length > 30 ? el("li", {}, `… ${senden.length - 30} weitere`) : null) : null,
    hinweis: daten?.listen ? "" : "Der Bot ist noch nicht verbunden – vorhandene Schlagwörter erkennt er beim Eintragen selbst.",
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
