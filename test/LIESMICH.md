# Testdaten für den Datei-Import

Zum Ausprobieren von **Datei importieren** auf der Webseite (Reiter „Quellen“ bzw. „Tags“).
Die Adressen sind echte, öffentliche Nachrichten-Feeds.

| Datei | Reiter | Inhalt |
|---|---|---|
| `quellen.csv` | Quellen | 27 Einträge im Format `Wochentag;URL` (wie `bot/quellen.csv`) |
| `quellen.json` | Quellen | 15 Einträge im Format „nach Tagen“ |
| `tags.csv` | Tags | 5 Tags mit 27 Schlagwörtern im Format `Tag;Schlagwort` (wie `bot/tags.csv`) |
| `tags.json` | Tags | 6 Tags mit 26 Schlagwörtern im Format „nach Tags“ |
| `quellen-mit-fehlern.csv` | Quellen | Sicherheitstest: 2 gültige, 9 gefährliche oder kaputte Zeilen |
| `tags-mit-fehlern.json` | Tags | Sicherheitstest: 2 gültige, 9 gefährliche oder kaputte Schlagwörter |

**Was du sehen solltest**

- CSV und JSON überschneiden sich absichtlich ein wenig. Importierst du erst `quellen.csv` und dann
  `quellen.json`, zeigt die Vorschau 2 Einträge als „schon vorhanden“. Bei den Tags werden
  „Cyberkriminalität“ und „Datenschutz“ ergänzt statt verdoppelt. Was du vorher schon eingetragen
  hattest, zählt ebenfalls als „schon vorhanden“ – die genauen Zahlen hängen also von deinem Stand ab.
- Die beiden `…-mit-fehlern`-Dateien enthalten Adressen ins Heimnetz (`192.168.0.1`, `localhost`,
  `127.0.0.1`), `file:`- und `javascript:`-Adressen, Zugangsdaten in der Adresse, Excel-Formeln
  (`=HYPERLINK(…)`, `=cmd|…`), Zeichen wie `+ - @` am Anfang sowie HTML/`<script>`. Die Vorschau
  muss diese unter „übersprungen“ mit Grund auflisten und darf nur die gültigen Einträge importieren.
  Im Fenster erscheint `<script>` nur als Text, es wird nie ausgeführt.

**Danach aufräumen:** Testeinträge entfernst du in der Tabelle (Mülleimer) bzw. in den Karten
(× oder Mülleimer). Alternativ den Bot beenden und `bot/quellen.csv` bzw. `bot/tags.csv` bearbeiten.
