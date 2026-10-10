# News-Bot mit eigener Webseite

Ein kleiner Nachrichten-Bot für den Eigengebrauch – komplett kostenlos, ohne Discord.

```
   Dein PC                                   Render (kostenlos)
 ┌──────────────────────┐   alle 30 s     ┌──────────────────────────┐
 │ bot/news_bot.py      │ ──────────────► │ web/server.py            │ ◄── du im Browser
 │ • liest quellen.xlsx │  Status, neue   │ • Seite mit Login        │     (PC oder Handy)
 │ • prüft RSS-Feeds    │  Artikel, Fehler│ • Artikel, Filter, Fehler│
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
3. **Quellen:** `bot/quellen.xlsx` mit deinen Quellen füllen (oder deine Datei dort ablegen).
   Wichtig ist nur eine Kopfzelle „Montag“, „Dienstag“ … mit den URLs darunter.
4. **Probelauf:** `python news_bot.py --test` zeigt nur in der Konsole, was gefunden wird.

## Teil 2: Webseite auf Render

1. **GitHub:** Kostenloses Konto anlegen, **GitHub Desktop** installieren.
   File → Add local repository → `C:\NewsBot` → „create a repository“ → „Publish repository“,
   Häkchen **„Keep this code private“** gesetzt lassen.
   Die Datei `.gitignore` sorgt dafür, dass `config.toml`, `state.json`, `vapid_privat.pem`
   und deine Excel **nicht** hochgeladen werden.
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
| Statusband oben | grün = läuft, orange = pausiert, grau = Bot offline (PC aus?) |
| Jetzt prüfen | startet sofort eine Prüfung – auch wenn pausiert |
| Pausieren / Fortsetzen | stoppt bzw. startet das automatische Prüfen |
| Prüfen alle … | Intervall zwischen 5 Minuten und 2 Stunden |
| Testbenachrichtigung | schickt eine Probe an alle eingeschalteten Geräte (und Discord, falls eingerichtet) |
| Benachrichtigungen ein/aus | für das Gerät, auf dem du gerade bist |
| Artikelliste | Suche, Filter nach Tag und Medium, „nur gemeldete“; **neu** = seit deinem letzten Besuch |
| Fehler / Befehle | welche Quellen nicht gingen, was mit deinen Befehlen passiert ist |

**Weniger Benachrichtigungen:** `nur_mit_tags = true` in der `config.toml` – dann meldet sich der
Bot nur bei Artikeln zu deinen Themen. Auf der Seite stehen trotzdem alle neuen Artikel.

## Im Alltag

| Du willst … | So geht's | Neustart nötig? |
|---|---|---|
| Quellen ändern | Excel bearbeiten und speichern | nein |
| Tags/Schlagwörter oder `nur_mit_tags` ändern | `config.toml` bearbeiten | **ja** |
| Pausieren, Intervall, sofort prüfen | Knöpfe auf der Seite | nein |
| Neues Handy dazu | dort „Benachrichtigungen einschalten“ | nein |

Neustart ohne Fenster: im Task-Manager „pythonw.exe“ beenden und die Verknüpfung im
Autostart-Ordner doppelklicken (oder PC neu starten).

## Gut zu wissen

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
| `bot/config.toml` | alle Einstellungen und Tag-Schlagwörter |
| `bot/quellen.xlsx` | deine Quellen nach Wochentag |
| `bot/state.json` | gemeldete Artikel, Verlauf, Geräte, Pause/Intervall (entsteht automatisch) |
| `bot/vapid_privat.pem` | Schlüssel für Benachrichtigungen (entsteht automatisch, geheim) |
| `bot/newsbot.log` | Protokoll |
| `web/server.py` | die Webseite für Render |
| `web/static/` | Seite im Design „Leitstelle“, Logik, Service Worker, App-Symbol |
| `web/static/fonts/` | Schrift IBM Plex Sans (freie Lizenz, siehe `OFL.txt`) |
| `render.yaml` | sagt Render, wie der Dienst angelegt wird |
