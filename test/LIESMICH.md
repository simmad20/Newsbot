# Testdaten für den Datei-Import

Zum Ausprobieren von **Datei importieren** auf der Webseite (Reiter „Quellen“ bzw. „Tags“).
Die Adressen sind echte, öffentliche Nachrichten-Feeds.

| Datei | Reiter | Inhalt |
|---|---|---|
| `quellen.csv` | Quellen | 27 Einträge im Format `Wochentag;URL` (wie `bot/quellen.csv`) |
| `quellen.json` | Quellen | 15 Einträge im Format „nach Tagen“ |
| `tags.csv` | Tags | 5 Tags mit Beschreibung im Format `Tag;Beschreibung` (wie `bot/tags.csv`) |
| `tags.json` | Tags | 6 Tags im Format „JSON als Liste“, teils ohne Beschreibung |
| `quellen-mit-fehlern.csv` | Quellen | Sicherheitstest: 2 gültige, 9 gefährliche oder kaputte Zeilen |
| `tags-mit-fehlern.json` | Tags | Sicherheitstest: 2 gültige, 9 gefährliche oder kaputte Tags |

**Was du sehen solltest**

- CSV und JSON überschneiden sich absichtlich ein wenig. Importierst du erst `quellen.csv` und dann
  `quellen.json`, zeigt die Vorschau 2 Einträge als „schon vorhanden“. Bei den Tags zählen
  „Cyberkriminalität“ und „Datenschutz“ als „schon vorhanden“. Was du vorher schon eingetragen hattest, zählt ebenfalls als „schon vorhanden“ – die genauen Zahlen hängen also von deinem Stand ab.
- Die beiden `…-mit-fehlern`-Dateien enthalten Adressen ins Heimnetz (`192.168.0.1`, `localhost`,
  `127.0.0.1`), `file:`- und `javascript:`-Adressen, Zugangsdaten in der Adresse, Excel-Formeln
  (`=HYPERLINK(…)`, `=cmd|…`), Zeichen wie `+ - @` am Anfang, HTML/`<script>`, Steuerzeichen und
  zu lange Namen bzw. Beschreibungen. Bei „Auch gültig“ wird nur das `=` am Anfang der Beschreibung
  entfernt. Die Vorschau muss die übrigen unter „übersprungen“ mit Grund auflisten und darf nur die
  gültigen Einträge importieren.
  Im Fenster erscheint `<script>` nur als Text, es wird nie ausgeführt.

**Danach aufräumen:** Testeinträge entfernst du in der Tabelle (Mülleimer) bzw. in den Karten
(Mülleimer). Alternativ den Bot beenden und `bot/quellen.csv` bzw. `bot/tags.csv` bearbeiten.

**Der ganze Tag-Baum:** `tags-import/tags.csv` (oder `tags.json`) im Hauptordner enthält alle Tags
aus dem Tag-Baum, mit dem Pfad als Beschreibung – einfach über „Datei importieren“ hochladen.
