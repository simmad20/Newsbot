# News-Bot mit eigener Webseite

Ein kleiner Nachrichten-Bot für den Eigengebrauch – ohne Discord, die Tags vergibt eine KI (DeepSeek oder Claude).

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
 └───┬──────────────┬───┘
     │ Titel +      │ verschlüsselte Benachrichtigung
     │ Vorschau     ▼
     ▼            Push-Dienst deines Browsers (Google, Apple, Mozilla, Microsoft) ──► Handy / PC
   KI-API (DeepSeek oder Claude): wählt passende Tags aus tags.csv
```

**Warum so aufgeteilt?** Kostenlose Render-Dienste schlafen nach 15 Minuten ohne Besuch ein und
vergessen bei jedem Neustart ihre Dateien. Deshalb arbeitet der Bot auf deinem PC und hält dort
alle Daten. Die Render-Seite ist Anzeige und Fernbedienung. Die Benachrichtigungen schickt der Bot
direkt an den Push-Dienst deines Browsers – das funktioniert also auch, wenn die Render-Seite
gerade schläft.

Kosten: **0 €** für Render und GitHub. Die Tags vergibt eine KI über ihre API (DeepSeek oder Claude) –
die kostet pro Anfrage ein wenig (siehe „Tags per KI“). Ohne API-Schlüssel läuft alles, nur ohne Tags.
Discord ist optional.

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
4. **Tags per KI:** Bei **DeepSeek** ([platform.deepseek.com](https://platform.deepseek.com)) oder
   **Claude** ([console.anthropic.com](https://console.anthropic.com)) ein Konto anlegen, etwas
   Guthaben aufladen und einen API-Schlüssel erstellen. In `bot/config.toml` eintragen (gibt es
   die Datei noch nicht: im Ordner `bot` `cp config.beispiel.toml config.toml` – die Vorlage
   erklärt jede Einstellung):
   ```toml
   [llm]
   api_key = "sk-..."
   ```
   Welcher Anbieter gemeint ist, erkennt der Bot am Schlüssel (Claude-Schlüssel beginnen mit
   `sk-ant-`). Für Claude zusätzlich einmal `pip install anthropic`. Der Schlüssel ist geheim wie
   ein Passwort – `config.toml` wird nie hochgeladen, also nie in eine andere Datei schreiben.
5. **Probelauf:** `python news_bot.py --test` zeigt nur in der Konsole, was gefunden wird – mit den
   Tags, die die KI vergeben hat.

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

## Bot ohne PC (GitHub Actions)

Ist der PC aus oder unerreichbar, kann GitHub den Bot laufen lassen: alle 30 Minuten ein Durchlauf
(`.github/workflows/newsbot.yml`). Einrichten geht komplett im Browser oder in der GitHub-App:

1. Im Repository **Settings → Secrets and variables → Actions → New repository secret**:
   - `DASHBOARD_URL` – die Adresse deiner Render-Seite, z. B. `https://newsbot-xxxx.onrender.com`
   - `BOT_TOKEN` – bei Render im Dienst unter **Environment**
   - `DEEPSEEK_API_KEY` oder `ANTHROPIC_API_KEY` – dein KI-Schlüssel, damit Tags vergeben werden
   - `DISCORD_WEBHOOK` – nur falls du Discord nutzt
2. **Actions → Newsbot → Run workflow** startet den ersten Lauf sofort. Danach läuft er von selbst.
3. Auf der Seite auf jedem Gerät **Benachrichtigungen aus- und wieder einschalten** (der Bot in
   GitHub hat einen eigenen Push-Schlüssel) und gleich danach noch einmal **Run workflow** drücken.
4. Quellen und Tags über die Seite eintragen oder per „Datei importieren“ – die Dateien vom PC hat
   GitHub nicht.

Gut zu wissen:
- **Nie gleichzeitig mit dem Bot auf dem PC** – sonst kommen Meldungen doppelt. Zurück zum PC:
  **Actions → Newsbot → ⋯ → Disable workflow**, dann den Bot auf dem PC starten.
- Die Seite zeigt zwischen den Läufen „Keine Verbindung“ – das ist hier normal.
- Befehle von der Seite (Quellen, Tags, Pausieren, Benachrichtigungen einschalten) holt der Bot erst
  beim nächsten Lauf ab. Die kostenlose Render-Seite vergisst sie aber, wenn sie vorher einschläft
  (nach 15 Minuten ohne Besuch) – also nach Änderungen gleich **Run workflow** drücken.
- Der Stand (gesehene Artikel, Geräte, Quellen, Tags) liegt im Actions-Cache des Repositorys.
  Läuft der Workflow 7 Tage lang nicht, löscht GitHub ihn.
- Private Repositories haben 2000 Gratis-Minuten im Monat, jeder Lauf zählt mindestens 1 Minute
  (48 Läufe am Tag ≈ 1440 Minuten). Verbrauch: in deinen GitHub-Kontoeinstellungen unter **Billing**. Wird es knapp, in
  `newsbot.yml` bei `cron` z. B. `"7 * * * *"` (stündlich) eintragen.

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
| Tag anklicken | **Antippen kopiert den Tag-Namen** (z. B. `Spionage`) zum direkten Einfügen – unten erscheint kurz „Kopiert“. Am PC kopiert auch **Strg+C** den Tag unter der Maus. **Gedrückt halten** (Handy), **Rechtsklick** oder **Umschalt+Klick** (PC) zeigt, wo der Tag im Tag-Baum liegt – z. B. Newsinfo → geographische Lokationen → Kontinente und Staaten → Europa → Vereinigtes Königreich (bei mehreren Stellen alle); „Nur diese Artikel“ filtert danach. Am Handy als Blatt von unten. Unter „Details“ kopiert **Alle Tags kopieren** alle Tags des Artikels, einen pro Zeile |
| Aufräumen | Nicht abgehakte Artikel, die älter als **7 Tage** sind, löscht der Bot automatisch – auch auf der Seite. Abgehakte bleiben. Ändern mit `offene_artikel_tage` in `config.toml` (0 = nie löschen) |
| Abhaken | **Abhaken** an einem Artikel = angeschaut; er verschwindet aus „Nicht angeschaut“ (mit „Rückgängig“). Filter: Nicht angeschaut / Angeschaut / Alle; „Alle … als angeschaut markieren“ hakt die ganze gefilterte Liste ab. Gilt auf allen Geräten – der Bot speichert es in `state.json`; die Zahl am Reiter zählt die offenen Artikel |
| Reiter „Quellen“ | Tabelle: eine Zeile pro Quelle, eine Spalte pro Wochentag – Tag anklicken schaltet ihn ein/aus; Suche, Quellen hinzufügen, Datei importieren |
| Reiter „Tags“ | Karten: ein Tag pro Karte mit Beschreibung; bearbeiten (Stift) oder löschen; Suche, neuer Tag, Datei importieren (auch der ganze Tag-Baum) |
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
| Tags ändern | Reiter „Tags“ auf der Seite – oder `tags.csv` bearbeiten | nein |
| API-Schlüssel, KI-Modell | `config.toml` unter `[llm]` bearbeiten | **ja** |
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
Wochentag;URL                       Tag;Beschreibung
Montag;https://derstandard.at       Ransomware;Cyber > Cyber Security > Ransomware
Montag;https://orf.at/rss           Österreich;
Dienstag;https://derstandard.at     KI-Regulierung;AI Act und nationale KI-Gesetze, nicht: KI-Technik
```

Die Beschreibung ist freiwillig. Sie hilft der KI, den Tag richtig zu verstehen – z. B. der Pfad im
Tag-Baum oder ein Satz, worum es geht und was nicht dazugehört.

**Über die Webseite** (auch unterwegs):

- *Quellen hinzufügen:* Adressen eingeben (eine pro Zeile), Tage anklicken, „Hinzufügen“. In der
  Tabelle schaltet ein Klick auf einen Tag die Quelle für diesen Tag ein oder aus, der Mülleimer
  entfernt sie an allen Tagen.
- *Neuer Tag:* Namen und (freiwillig) eine Beschreibung eingeben. Der Stift in einer Karte ändert
  die Beschreibung, der Mülleimer löscht den Tag.
- *Datei importieren:* CSV- oder JSON-Datei auswählen oder hineinziehen. Die Seite zeigt vorher an,
  was neu ist, was schon vorhanden ist und was übersprungen wird (mit Grund). Unterstützt werden
  `quellen.csv`/`tags.csv` selbst, eine CSV mit einer Spalte pro Wochentag (wie die alte Excel),
  der Tag-Baum aus `tags-import/` (CSV oder JSON – der Pfad wird zur Beschreibung) und JSON –
  Beispiele stehen im Dialog unter „Welche Formate werden erkannt?“. Vorhandenes wird ergänzt, nie
  gelöscht; bei vorhandenen Tags gilt die Beschreibung aus der Datei.

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
- Tag-Namen (bis 80 Zeichen): Buchstaben, Ziffern, Leerzeichen und `- . , : & / ' + ( ) [ ]`, am
  Anfang ein Buchstabe, eine Ziffer oder eine Klammer (z. B. `[S]1 Cyber`). Beschreibungen (bis 300
  Zeichen): normaler Text ohne Steuerzeichen; `= + - @` am Anfang werden entfernt. Dadurch kann keine
  Zelle mit `=`, `+`, `-` oder `@` beginnen – Excel würde sie sonst beim Öffnen als Formel ausführen.
- Höchstens 700 Einträge in `quellen.csv` (eine Quelle an 3 Tagen = 3 Einträge) und 1000 Tags. Ein Import darf bis zu dieser Grenze alles auf einmal bringen; was darüber
  hinausgeht, wird übersprungen und gemeldet.
- Importierte Dateien liest nur dein Browser (höchstens 2 MB). An Server und Bot gehen nur die
  einzelnen, geprüften Einträge – die Datei selbst kommt nie auf deinen PC und wird nie ausgeführt.

Ungültige Zeilen, die du von Hand einträgst, überspringt der Bot und zeigt sie im Reiter „Fehler“ –
gelöscht werden sie nicht. Die Webseite kann nur diese festen Befehle schicken; Programme starten,
andere Dateien anfassen oder Einstellungen in `config.toml` ändern kann sie nicht.

**Umstieg von der alten Version:** Tags aus `config.toml` übernimmt der Bot beim ersten Start
automatisch in `tags.csv`. Eine `tags.csv` mit Schlagwörtern (`Tag;Schlagwort`) stellt er beim Start
auf `Tag;Beschreibung` um: Die Tags bleiben, die Schlagwörter fallen weg (Sicherung in
`tags-schlagwoerter-alt.csv`). Eine alte `quellen.xlsx` wird nicht mehr gelesen – ihre Quellen einmal
über die Webseite eintragen und die Excel-Datei danach löschen.

## Tags per KI

Für jeden neuen Artikel schickt der Bot **Medium, Titel und Vorschautext** an die KI (DeepSeek oder
Claude), zusammen mit deiner Tag-Liste. Die KI entscheidet zuerst, ob der Artikel zum Thema gehört
(siehe Themenfilter), und vergibt dann Tags – nur Tags, die es in `tags.csv` gibt; erfundene Namen
verwirft der Bot.

Regeln für die Tags (Prompt in `bot/ki_tags.py`):

- **Nur die untersten Tags** des Tag-Baums – also keine, die noch Untertags haben. Die KI bekommt nur
  diese zur Auswahl (mit ihrem Pfad als Erklärung); schickt sie trotzdem einen Ober-Tag, wirft der
  Bot ihn weg. Welche Tags unten liegen, erkennt der Bot am Pfad in der Beschreibung – deshalb den
  Tag-Baum mit Pfad importieren (`tags-import/tags.csv`).
- **Die wichtigsten belegten Tags** – 15 bis höchstens 25 pro Artikel, nach Wichtigkeit sortiert. Die KI geht jeden
  Artikel mit elf Blickwinkeln durch: wer, was, wie (Technik), wo, warum (Politik/Recht),
  Infrastruktur, Gesellschaft/Wirtschaft, Fahrzeuge, Information/Dokument, Zukunftstechnik,
  Krisenarten. Jeder Tag muss sich auf Titel oder Vorschau stützen; eindeutig Erschlossenes ist
  erlaubt, Geratenes nicht. Vor der Antwort prüft sie still eine Checkliste.
- **Beleg zu jedem Tag:** Die KI gibt zu jedem Tag an, warum er passt – ein kurzes Zitat aus Titel oder
  Vorschau oder eine knappe Begründung. Zu sehen in der Pfad-Karte (gedrückt halten bzw. Rechtsklick
  auf den Tag) unter „Warum dieser Tag?“ und am PC beim Darüberfahren mit der Maus.
- **Pflicht für jeden Artikel:** `[S]1 Cyber` (Struktur; zusätzlich `[S]2 KriMiSi` bei Krisen-,
  Militär- und Sicherheitsthemen, `[S]3 InnoTech` bei Innovation und Forschung), ein Tag aus *Newsinfo > Dokumententyp*
  (meist „News“), aus *zeitlicher Aspekt* (z. B. „2026-2030“), aus *geographische Lokationen* (jedes
  betroffene Land einzeln; weltweit „Global“, im All „Weltraum“, ohne Ortsbezug „kein Standort“) und aus *Quellentyp* (meist „Nachrichtenseite“). Bei allem
  mit **Künstlicher Intelligenz** zusätzlich ein Tag aus *Auftragstags > HSC > HSC-KI*.
- Vergisst die KI einen Pflicht-Ast, ergänzt der Bot den naheliegenden Tag selbst („[S]1 Cyber“,
  „News“, den aktuellen Zeitraum, „kein Standort“, „Nachrichtenseite“, bei KI „[KI_]Tools und
  Usecases“).
- Inhaltliche Tags stehen vorne, die Einordnung (Struktur, Newsinfo, Auftragstags) dahinter. Auf der
  Artikelkarte stehen die ersten 6, alle unter „Details“.
- Ein Land passt nur, wenn der Artikel von dort handelt – nicht, weil das Medium von dort ist. Texte
  aus den Artikeln behandelt die KI nur als Material, nie als Anweisung.

Einstellungen in `config.toml`:

```toml
[llm]
api_key = "sk-..."            # Pflicht – sonst kommen die Artikel ohne Tags
anbieter = "deepseek"         # freiwillig: "deepseek" oder "anthropic" – sonst am Schlüssel erkannt
modell = "deepseek-v4-flash"  # freiwillig; Standard: deepseek-v4-flash bzw. claude-opus-5-5
effort = "low"                # freiwillig, nur Claude: low, medium oder high
thema = "Cyber und Technologie"  # freiwillig – siehe Themenfilter; thema = "" schaltet ihn aus
```

Statt in `config.toml` darf der Schlüssel auch in der Umgebungsvariable `DEEPSEEK_API_KEY` bzw.
`ANTHROPIC_API_KEY` stehen.

| | DeepSeek | Claude |
|---|---|---|
| Preis | sehr günstig | teurer (`claude-haiku-5-5` deutlich günstiger als der Standard) |
| Antwortform | JSON per Anweisung – der Bot prüft jede Antwort | JSON per Schema erzwungen |
| Server | China (es gehen nur öffentliche Artikeltitel und -vorschauen hin) | USA |
| Extra-Paket | keins | `pip install anthropic` |

- **Themenfilter:** Die KI entscheidet zuerst, ob ein Artikel überhaupt zum Thema gehört –
  Standard ist **Cyber und Technologie** (IT-Sicherheit, Cyberangriffe, Datenschutz, KI, Software,
  Hardware und Chips, Internet, Telekommunikation, digitale Infrastruktur, Tech-Firmen,
  Digitalpolitik). Sport, Kultur, allgemeine Politik, Krieg, Wirtschaft usw. werden verworfen –
  außer das Thema ist darin der Kern (z. B. ein Cyberangriff im Krieg, ein KI-Gesetz). Verworfene
  Artikel erscheinen nicht auf der Seite und lösen keine Benachrichtigung aus; im Log und in der
  Statuskarte steht nur „… nicht zum Thema“. Anderes Thema: `thema = "..."` in `config.toml`.
  Tipp: Wo es eine eigene Rubrik gibt, trag besser die ein (z. B.
  `https://www.theguardian.com/uk/technology` statt `https://www.theguardian.com/`) – weniger
  Artikel, weniger Kosten.
- **Mindestens 3 Cyber-Tags:** Ein Artikel gilt nur als relevant, wenn sich mindestens 3 Tags aus dem
  Ast „Cyber“ belegen lassen (z. B. Ransomware, Phishing, Datenleck – nicht „[S]1 Cyber“, „Soziale Medien“
  oder „Erpressung“). Das steht im Prompt und wird vom Bot zusätzlich nachgezählt; zu wenige → aussortiert.
  Anzahl ändern mit `min_cyber_tags = 3` unter `[llm]` (0 = aus).
- **Sprache:** Der Prompt ist englisch (damit kommen die Modelle am besten zurecht); die Tag-Namen bleiben
  deutsch, eigene Begründungen in den Belegen schreibt die KI auf Deutsch.
- **Prompt ansehen:** `python news_bot.py --prompt` schreibt genau das, was an die KI geht – mit deiner
  aktuellen Tag-Liste – in `bot/prompt-vorschau.txt` (ansehen z. B. mit `less prompt-vorschau.txt`).
- **Denkmodus (DeepSeek):** ist aus – für Tags reicht der ausführliche Prompt, und Nachdenken kostete
  tausende Tokens pro Artikel („Antwort zu lang“). Mit `denken = true` unter `[llm]` wieder einschalten
  (gründlicher, aber deutlich teurer und langsamer). Wird eine Antwort trotzdem zu lang, teilt der Bot
  das Paket und fragt bei einem einzelnen Artikel einmal knapp nach.
- **Kosten:** Die Artikel gehen in Paketen zu 5 hinaus. Die Tag-Liste wird zwischengespeichert
  und kostet bei weiteren Anfragen nur einen Bruchteil. Was du tatsächlich verbrauchst, steht in
  `newsbot.log` („KI-Tags: … Tokens“) und auf der Seite des Anbieters.
- **Klappt die Tag-Vergabe nicht** (Schlüssel falsch, Guthaben leer, KI nicht erreichbar), steht
  das im Reiter „Fehler“. Die Artikel werden dann ohne Tags gemeldet – auch bei `nur_mit_tags = true`,
  damit nichts verloren geht.
- Die Tags gelten ab der nächsten Prüfung; bereits gemeldete Artikel behalten ihre Tags.

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

- **Neu anfangen:** Bot beenden, dann im Ordner `bot`: `python news_bot.py --zuruecksetzen`. Er
  vergisst alle **noch nicht angeschauten** Artikel und die Fehler. **Abgehakte Artikel bleiben** (und
  kommen auch nicht als neu wieder), ebenso Quellen, Tags, `config.toml`, die Geräte für
  Benachrichtigungen und Pause/Intervall. Der alte Stand liegt danach in
  `state.vorher.json`. Beim nächsten Start übernimmt die Seite automatisch den neuen Stand; nicht
  angeschaute Artikel der letzten 24 Stunden (bzw. des Höchstalters) kommen dann neu getaggt wieder.
  `vapid_privat.pem` **nie** löschen (siehe unten).

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
| `bot/ki_tags.py` | Tags per KI: Prompt und Anbindung an DeepSeek bzw. Claude |
| `bot/seiten.py` | Seiten ohne Feed: Sitemaps, Angaben aus Artikelseiten, Links der Startseite |
| `bot/config.toml` | alle Einstellungen (geheim, wird nie hochgeladen – muss existieren, sonst startet der Bot nicht) |
| `bot/config.beispiel.toml` | Vorlage mit Testwerten und Erklärung jeder Einstellung: `cp config.beispiel.toml config.toml`, dann eigene Werte eintragen |
| `bot/quellen.csv` | deine Quellen nach Wochentag (entsteht automatisch) |
| `bot/tags.csv` | deine Tags mit Beschreibung (entsteht automatisch) |
| `bot/state.json` | gemeldete Artikel, Verlauf, Geräte, Pause/Intervall (entsteht automatisch) |
| `bot/vapid_privat.pem` | Schlüssel für Benachrichtigungen (entsteht automatisch, geheim) |
| `bot/newsbot.log` | Protokoll |
| `web/server.py` | die Webseite für Render |
| `web/static/` | Seite im Design „Leitstelle“, Logik, Service Worker, App-Symbol |
| `web/static/verwaltung.js` | Quellen-Tabelle, Tag-Karten, Dialoge und Datei-Import |
| `tags-import/` | der komplette Tag-Baum als CSV und JSON zum Importieren |
| `web/static/fonts/` | Schrift IBM Plex Sans (freie Lizenz, siehe `OFL.txt`) |
| `render.yaml` | sagt Render, wie der Dienst angelegt wird |
