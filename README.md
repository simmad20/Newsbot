# News-Bot mit eigener Webseite

Ein kleiner Nachrichten-Bot für den Eigengebrauch – komplett kostenlos, ohne Discord.

```
   Dein PC                                   Render (kostenlos)
 ┌──────────────────────┐   alle 30 s     ┌──────────────────────────┐
 │ bot/news_bot.py      │ ──────────────► │ web/server.py            │ ◄── du im Browser
 │ • quellen.csv,       │  Status, neue   │ • Seite mit Login        │     (PC oder Handy)
 │   tags.csv           │  Artikel, Listen│ • Artikel, Quellen, Tags │
 │ • prüft RSS-Feeds    │                 │ • Fehler                 │
 │ • schickt Benach-    │ ◄────────────── │ • Knöpfe für Befehle     │
 │   richtigungen       │  Befehle, Geräte└──────────────────────────┘
 │ • state.json         │
 └──────────┬───────────┘
            │ verschlüsselte Benachrichtigung
            ▼
   Push-Dienst deines Browsers (Google, Apple, Mozilla, Microsoft) ──► dein Handy / PC
```

**Warum so aufgeteilt?** Kostenlose Render-Dienste schlafen nach 15 Minuten ohne Besuch ein und
vergessen bei jedem Neustart ihre Dateien. Deshalb arbeitet der Bot auf deinem PC und hält dort
alle Daten. Die Render-Seite ist Anzeige und Fernbedienung. Die Benachrichtigungen schickt der Bot
direkt an den Push-Dienst deines Browsers – das funktioniert also auch, wenn die Render-Seite
gerade schläft.

Kosten: **0 €** (Render Free, GitHub Free). Discord ist optional.

---

## Teil 1: Bot auf dem PC

1. **Python 3.11 oder neuer** installieren (python.org, bei Windows „Add Python to PATH“ anhaken).
2. Den Ordner `newsbot` z. B. nach `C:\NewsBot` legen. Im Explorer `C:\NewsBot\bot` öffnen,
   in die Adresszeile `cmd` tippen, Enter. Dann:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Quellen und Tags:** Beim ersten Start legt der Bot `bot/quellen.csv` und `bot/tags.csv` an.
   Am einfachsten trägst du später alles über die Webseite ein (Reiter „Quellen“ und „Tags“).
   Von Hand geht es auch, mit Excel oder einem Texteditor – siehe „Quellen und Tags“ unten.
4. **Probelauf:** `python news_bot.py --test` zeigt nur in der Konsole, was gefunden wird.

## Teil 2: Webseite auf Render

1. **GitHub:** Kostenloses Konto anlegen, **GitHub Desktop** installieren.
   File → Add local repository → `C:\NewsBot` → „create a repository“ → „Publish repository“,
   Häkchen **„Keep this code private“** gesetzt lassen.
   Die Datei `.gitignore` sorgt dafür, dass `config.toml`, `state.json`, `vapid_privat.pem`
   und deine Quellen/Tags (`quellen.csv`, `tags.csv`) **nicht** hochgeladen werden.
2. **Render:** Konto auf render.com anlegen (am einfachsten „mit GitHub anmelden“).
   **New → Blueprint** → dein Repository wählen. Render fragt nach `DASHBOARD_PASSWORT` –
   wähle ein gutes Passwort (mind. 10 Zeichen). Warten, bis der Dienst „Live“ ist.
3. Im Dienst `newsbot` kopieren:
   - oben die Adresse, z. B. `https://newsbot-xxxx.onrender.com`
   - links unter **Environment** den Wert von `BOT_TOKEN`
4. In `bot/config.toml` eintragen:
   ```toml
   [dashboard]
   url = "https://newsbot-xxxx.onrender.com"
   bot_token = "der kopierte BOT_TOKEN"
   ```
5. Bot starten: `python news_bot.py`. Seite im Browser öffnen, anmelden – nach spätestens einer
   Minute steht dort „Bot läuft“.

## Teil 3: Benachrichtigungen einschalten

Auf **jedem Gerät**, das Benachrichtigungen bekommen soll, einmal:

- **PC (Chrome, Edge, Firefox) und Android (Chrome):** Seite öffnen, anmelden, auf
  **„Benachrichtigungen einschalten“** tippen und erlauben. Nach etwa 30 Sekunden kommt die
  Bestätigung „Benachrichtigungen sind an“.
- **iPhone/iPad (ab iOS 16.4):** Apple erlaubt das nur für Seiten auf dem Home-Bildschirm.
  1. Seite in **Safari** öffnen.
  2. Unten auf **Teilen** tippen → **„Zum Home-Bildschirm“**.
  3. Die Seite über das neue **News-Bot-Symbol** öffnen, anmelden, dann
     „Benachrichtigungen einschalten“ tippen und erlauben.

Tippst du auf eine Benachrichtigung, öffnet sich direkt der Artikel. Mit „Testbenachrichtigung“
prüfst du jederzeit, ob alles ankommt. Ausschalten geht über denselben Knopf.

## Bot automatisch mit Windows starten

`Win + R` → `shell:startup` → Enter. Im Ordner: Rechtsklick → Neu → Verknüpfung, als Ziel:
```
C:\NewsBot\bot\.venv\Scripts\pythonw.exe C:\NewsBot\bot\news_bot.py
```
`pythonw` läuft ohne Fenster. Ob er läuft, siehst du auf der Seite oder in `bot/newsbot.log`.
Vorher ein offenes Konsolenfenster mit dem Bot schließen – zweimal gleichzeitig startet er nicht.

---

## Was die Seite kann

| Bereich | Funktion |
|---|---|
| Kopfleiste | Status und **Abmelden** – bleibt beim Scrollen immer sichtbar |
| Statuskarte | grün = läuft bzw. prüft gerade (mit Fortschritt), orange = pausiert, grau = beendet, rot = abgestürzt oder keine Verbindung |
| Jetzt prüfen | startet sofort eine Prüfung – auch wenn pausiert |
| Pausieren / Fortsetzen | stoppt bzw. startet das automatische Prüfen |
| Prüfen alle … | Intervall zwischen 5 Minuten und 2 Stunden |
| Artikel bis … | wie alt ein Artikel höchstens sein darf, damit er noch gemeldet wird (6 Stunden bis 7 Tage) |
| Testbenachrichtigung | schickt eine Probe an alle eingeschalteten Geräte (und Discord, falls eingerichtet) |
| Benachrichtigungen ein/aus | für das Gerät, auf dem du gerade bist |
| Reiter „Artikel“ | nach Tagen gruppiert, je 30 auf einmal („Weitere anzeigen“); Suche, Filter nach Tag und Medium, „nur gemeldete“; **neu** = seit deinem letzten Besuch |
| Reiter „Quellen“ | Tabelle: eine Zeile pro Quelle, eine Spalte pro Wochentag – Tag anklicken schaltet ihn ein/aus; Suche, Quellen hinzufügen, Datei importieren |
| Reiter „Tags“ | Karten: ein Tag pro Karte mit seinen Schlagwörtern; direkt in der Karte ergänzen oder entfernen; Suche, neuer Tag, Datei importieren |
| Reiter „Fehler“ / „Befehle“ | welche Quellen nicht gingen, was mit deinen Befehlen passiert ist |

**Woher die Seite weiß, ob der Bot läuft:** Der Bot meldet sich alle 30 Sekunden, auch mitten in
einer langen Prüfung. Beendest du ihn normal (Strg+C oder Konsolenfenster schließen), meldet er sich
ab – die Seite zeigt sofort „Beendet“. Stürzt er ab, wird er im Task-Manager beendet oder ist der PC
aus, zeigt die Seite nach etwa 75 Sekunden ohne Lebenszeichen „Keine Verbindung“.

**Weniger Benachrichtigungen:** `nur_mit_tags = true` in der `config.toml` – dann meldet sich der
Bot nur bei Artikeln zu deinen Themen. Auf der Seite stehen trotzdem alle neuen Artikel.

## Im Alltag

| Du willst … | So geht's | Neustart nötig? |
|---|---|---|
| Quellen ändern | Reiter „Quellen“ auf der Seite – oder `quellen.csv` bearbeiten | nein |
| Tags/Schlagwörter ändern | Reiter „Tags“ auf der Seite – oder `tags.csv` bearbeiten | nein |
| Pausieren, Intervall, Höchstalter, sofort prüfen | Knöpfe auf der Seite | nein |
| `intervall_minuten`, `max_alter_stunden`, `nur_mit_tags` | `config.toml` bearbeiten und speichern | nein |
| Discord, Dashboard-Adresse, Zeitzone | `config.toml` bearbeiten | **ja** |
| Neues Handy dazu | dort „Benachrichtigungen einschalten“ | nein |

**Intervall und Höchstalter** kannst du auf der Seite oder in der `config.toml` einstellen. Es gilt,
was du zuletzt geändert hast: Speicherst du die `config.toml` mit einem neuen Wert, übernimmt der Bot
ihn innerhalb von 30 Sekunden – auch wenn auf der Seite vorher etwas anderes eingestellt war. Stellst
du danach auf der Seite um, gilt wieder die Seite. Erhöhst du das Höchstalter, meldet der Bot bei der
nächsten Prüfung auch ältere, noch nicht gemeldete Artikel (höchstens `max_meldungen_pro_lauf` auf einmal).

Neustart ohne Fenster: im Task-Manager „pythonw.exe“ beenden und die Verknüpfung im
Autostart-Ordner doppelklicken (oder PC neu starten).

## Quellen und Tags

Beides liegt als CSV-Datei im Ordner `bot` (Trennzeichen `;`, eine Zeile pro Eintrag):

```
quellen.csv                         tags.csv
Wochentag;URL                       Tag;Schlagwort
Montag;https://derstandard.at       Cyberkriminalität;cyber*
Montag;https://orf.at/rss           Cyberkriminalität;ransomware
Dienstag;https://derstandard.at     Österreich;wien*
```

**Über die Webseite** (auch unterwegs):

- *Quellen hinzufügen:* Adressen eingeben (eine pro Zeile), Tage anklicken, „Hinzufügen“. In der
  Tabelle schaltet ein Klick auf einen Tag die Quelle für diesen Tag ein oder aus, der Mülleimer
  entfernt sie an allen Tagen.
- *Neuer Tag:* Namen eingeben, Schlagwörter mit Enter oder Komma übernehmen. Bestehende Tags
  ergänzt du direkt in ihrer Karte, das × an einem Schlagwort entfernt es.
- *Datei importieren:* CSV- oder JSON-Datei auswählen oder hineinziehen. Die Seite zeigt vorher an,
  was neu ist, was schon vorhanden ist und was übersprungen wird (mit Grund). Unterstützt werden
  `quellen.csv`/`tags.csv` selbst, eine CSV mit einer Spalte pro Wochentag (wie die alte Excel) und
  JSON – Beispiele stehen im Dialog unter „Welche Formate werden erkannt?“. Vorhandenes wird ergänzt,
  nie gelöscht.

Die Seite schickt jede Änderung an den Bot, der sie in die CSV-Datei einträgt und „Erledigt: …“
zurückmeldet. Bis dahin sind die Einträge gestrichelt. Läuft der Bot gerade nicht, wartet der Befehl,
bis er wieder da ist (startet Render in der Zwischenzeit neu, geht ein wartender Befehl verloren –
dann einfach nochmal senden).

**Von Hand:** Datei mit Excel oder dem Editor öffnen, bearbeiten, speichern. Der Bot liest beide
Dateien bei jeder Prüfung neu – kein Neustart nötig. Excel vor dem nächsten Befehl von der Webseite
wieder schließen, sonst kann der Bot die Datei nicht ändern (er meldet das dann auf der Seite).

**Was erlaubt ist** – das prüfen Webseite, Server **und** Bot jeweils selbst:

- Adressen: nur `http://` oder `https://` zu öffentlichen Servern im Internet. Gesperrt sind
  Adressen ins eigene Netz (localhost, 127.x, 192.168.x, 10.x, Router-Namen wie `fritz.box.lan` …),
  Zugangsdaten in der Adresse (`user:pass@`) und andere Arten wie `file:` oder `javascript:`.
  Der Bot prüft vor jedem Abruf und nach jeder Weiterleitung zusätzlich, wohin die Adresse wirklich
  zeigt.
- Tags (bis 40 Zeichen) und Schlagwörter (bis 60 Zeichen): Buchstaben, Ziffern, Leerzeichen und
  `- . & / ' +`, am Anfang immer ein Buchstabe oder eine Ziffer, bei Schlagwörtern `*` am Ende.
  Dadurch kann keine Zelle mit `=`, `+`, `-` oder `@` beginnen – Excel würde sie sonst beim Öffnen
  als Formel ausführen.
- Höchstens 700 Einträge in `quellen.csv` (eine Quelle an 3 Tagen = 3 Einträge) und 100 Tags mit je
  100 Schlagwörtern. Ein Import darf bis zu dieser Grenze alles auf einmal bringen; was darüber
  hinausgeht, wird übersprungen und gemeldet.
- Importierte Dateien liest nur dein Browser (höchstens 2 MB). An Server und Bot gehen nur die
  einzelnen, geprüften Einträge – die Datei selbst kommt nie auf deinen PC und wird nie ausgeführt.

Ungültige Zeilen, die du von Hand einträgst, überspringt der Bot und zeigt sie im Reiter „Fehler“ –
gelöscht werden sie nicht. Die Webseite kann nur diese festen Befehle schicken; Programme starten,
andere Dateien anfassen oder Einstellungen in `config.toml` ändern kann sie nicht.

**Umstieg von der alten Version:** Tags aus `config.toml` übernimmt der Bot beim ersten Start
automatisch in `tags.csv`. Eine alte `quellen.xlsx` wird nicht mehr gelesen – ihre Quellen einmal
über die Webseite eintragen und die Excel-Datei danach löschen.

## Seiten ohne RSS-Feed

Der Bot probiert pro Quelle der Reihe nach, bis etwas klappt:

1. **RSS/Atom-Feed** – die Adresse selbst, ein Feed-Hinweis in der Seite oder übliche Pfade wie `/rss`.
2. **News-Sitemap** – die Liste, die Nachrichtenseiten für Google News bereitstellen (Titel und
   Veröffentlichungszeit). Gefunden über die `robots.txt` oder übliche Pfade.
3. **Normale Sitemap** – Adressen mit Änderungsdatum.
4. **Startseite** (Notlösung) – der Bot erkennt neue Artikel-Links auf der eingetragenen Seite.
   Beim allerersten Mal meldet er nur die obersten 10, alles andere merkt er sich als bekannt.

Bei 2–4 holt er Titel, Zusammenfassung, Autor und Datum aus den öffentlichen Angaben der Artikelseite
(die Daten für Suchmaschinen und soziale Netzwerke) – Paywalls umgeht er nicht. Höchstens
20 Artikelseiten pro Quelle und Prüfung; der Rest kommt bei der nächsten Prüfung. Ohne Feed schaut
er einmal am Tag nach, ob es inzwischen einen gibt. In der Quellen-Tabelle steht bei jeder Quelle,
welcher Weg genutzt wird, in den Artikel-Details „über Sitemap“ bzw. „über Startseite“.

Sitemaps werden mit `defusedxml` gelesen (präparierte XML-Dateien werden abgelehnt), jede Antwort ist
auf wenige MB begrenzt – auch gepackt. Es gelten dieselben Regeln wie für Feeds: nur öffentliche
Server, `robots.txt`, 1 Sekunde Pause zwischen Abrufen.

Tipp: Bei einer Ressortseite (z. B. nur „Wirtschaft“) liefern Sitemaps die Artikel der *ganzen*
Seite. Gibt es für das Ressort einen eigenen Feed, trag besser den ein.

## Gut zu wissen

- **Neu anfangen:** Bot beenden und `bot/state.json` löschen – er vergisst dann alle gesehenen
  Artikel und den Verlauf. Beim nächsten Start übernimmt die Seite automatisch den leeren Stand.
  `vapid_privat.pem` dabei **nicht** löschen (siehe unten).

- **Aufwachen dauert:** War der PC aus, schläft die Seite; der erste Aufruf dauert dann etwa eine
  Minute. Benachrichtigungen sind davon nicht betroffen.
- **Freistunden:** Render gibt pro Monat 750 kostenlose Stunden. Ein Dienst, der den ganzen Monat
  wach ist, braucht höchstens 744 – das passt, solange das dein einziger kostenloser Web Service ist.
- **`vapid_privat.pem`** entsteht beim ersten Start und ist der geheime Schlüssel für die
  Benachrichtigungen. Nicht weitergeben. Löschst du ihn, musst du die Benachrichtigungen auf allen
  Geräten neu einschalten.
- **Sicherheit:** Login mit Passwort (nach 20 Fehlversuchen 15 Minuten Sperre). Nur der Bot mit dem
  richtigen `BOT_TOKEN` darf Daten schicken. Die Seite kann nur feste Befehle auslösen. Der Bot
  schickt Benachrichtigungen nur an echte Push-Dienste der Browser, verschlüsselt pro Gerät.
- **Zusammenfassung:** Angezeigt wird der Vorschautext aus dem Feed, keine KI-Zusammenfassung.
- Der Bot hält sich an die `robots.txt` der Seiten, wartet 1 Sekunde zwischen Abrufen und umgeht
  keine Paywalls.
- **Discord zusätzlich?** Webhook-URL in `config.toml` bei `discord_webhook` eintragen – dann kommt
  jede Meldung auch dort an.

## Dateien

| Datei | Zweck |
|---|---|
| `bot/news_bot.py` | der Bot |
| `bot/webpush.py` | verschickt die Browser-Benachrichtigungen |
| `bot/listen.py` | liest, prüft und ändert `quellen.csv` und `tags.csv` |
| `bot/seiten.py` | Seiten ohne Feed: Sitemaps, Angaben aus Artikelseiten, Links der Startseite |
| `bot/config.toml` | alle Einstellungen |
| `bot/quellen.csv` | deine Quellen nach Wochentag (entsteht automatisch) |
| `bot/tags.csv` | deine Tags und Schlagwörter (entsteht automatisch) |
| `bot/state.json` | gemeldete Artikel, Verlauf, Geräte, Pause/Intervall (entsteht automatisch) |
| `bot/vapid_privat.pem` | Schlüssel für Benachrichtigungen (entsteht automatisch, geheim) |
| `bot/newsbot.log` | Protokoll |
| `web/server.py` | die Webseite für Render |
| `web/static/` | Seite im Design „Leitstelle“, Logik, Service Worker, App-Symbol |
| `web/static/verwaltung.js` | Quellen-Tabelle, Tag-Karten, Dialoge und Datei-Import |
| `web/static/fonts/` | Schrift IBM Plex Sans (freie Lizenz, siehe `OFL.txt`) |
| `render.yaml` | sagt Render, wie der Dienst angelegt wird |
