# Touchline — Every moment, explained.

**Ein ausführbarer Hackathon-Prototyp für die Synthetic Match Insights Engine.** Touchline übersetzt synthetische Fußballereignisse in belegbare Geschichten, personalisierte Fan-Ansichten und zeitgesteuerte Broadcast-Einblendungen.

## In zwei Minuten starten

**Ohne Installation:** Die zusätzlich gelieferte Datei `Touchline-Demo.html` direkt im Browser öffnen. Sie enthält die vollständige Browser-Demo; Server-Streaming und echte Azure-KI benötigen die unten beschriebene Servervariante.

Voraussetzung: Node.js 22 oder neuer. Keine Paketinstallation und keine Zugangsdaten für die lokale Demo erforderlich.

**Windows:** `Start-Touchline.cmd` öffnen. Danach im Browser **http://localhost:8765** öffnen. Zum Beenden das Serverfenster schließen oder Strg+C drücken.

**Alle Systeme:**

```sh
node server.mjs
```

Die App beginnt pausiert bei 62:25. Auf **„Pressing → Ballgewinn → Tor“** klicken, die **sechs Ereignisbelege** öffnen und zwischen Fan, Analyst und Spielerfokus wechseln. Die UI ist deutsch; Geschichten und Zusammenfassungen unterstützen Deutsch, Englisch und Spanisch.

## Neu: Player Pulse

Einen Spieler auswählen, seine Laufspur und seinen erklärbaren Live-Index verfolgen und mit zwölf synthetischen Saisonspielen sowie 48 Karrierespielen vergleichen – immer bis zur gleichen Spielminute. Jede Indexänderung führt zum Ereignisbeleg. [Bedienung und Formel](docs/PLAYER-PULSE.md).

## Was tatsächlich funktioniert

- Vollständiger synthetischer 90-Minuten-Replay mit Seed, 22 fiktiven Spielern, 6 Ereignistypen und Spielertracking.
- Streaming über Server-Sent Events; Browser-Replay auch ohne Backend. Im Data & Vision Lab startet „Server-Livestream starten“ den echten lokalen Server-Stream.
- Berechnete Passdistanz, Passgenauigkeit, Passschwierigkeit, Ball-/Einwurfgeschwindigkeit, Laufdistanz und Spitzengeschwindigkeit.
- Erkennung von Druckhäufungen, progressiven Pässen, Abschlüssen und Umschaltketten; nachvollziehbare Beleg-IDs.
- Fan-/Analysten-/Spielermodus, Clubfilter, drei Erzählsprachen, Metrikfilter im Storyboard.
- Automatische personalisierte Zusammenfassung bis zum aktuellen Spielzeitpunkt.
- Redaktionelle Overlay-Vorschau mit Freigabe, Feed-Versatz, Ablaufzeit und JSON-Export.
- Pixelbasiertes Vision-Labor auf einem generierten Bildstrom: trainierter Farbprototyp-Klassifikator, Ballgeschwindigkeit und Übergabeerkennung.
- Optionaler serverseitiger Azure-OpenAI-Aufruf mit Zugriffstoken, Timeout, Begrenzung, Faktenprüfung und explizitem Regelfallback.
- Dockerfile und Bicep für Azure Container Apps; Beispielparameter verwenden Key-Vault-Referenzen statt eingecheckter Geheimnisse.

## Status und Grenzen

Dies ist ein **funktionsfähiger Einreichungsprototyp**, keine bestätigte finale Hackathon-Abgabe. Die private Sites-Veröffentlichung wurde vorbereitet, konnte aber wegen einer automatischen Freigabesperre bei der Repository-Zugangsdaten-Übergabe nicht abgeschlossen werden. Es gibt deshalb noch keine bestätigte Online-Demo. Die Datei `Touchline-Demo.html` und der lokale Server funktionieren unabhängig davon.

**Noch erforderlich:** Azure-Ressourcen und ein geeignetes Modell-Deployment konfigurieren, den echten KI-Aufruf prüfen, ein **öffentliches GitHub-Repository** und ein **öffentliches Demo-Video unter zwei Minuten** bereitstellen sowie die vollständigen Teilnahmebedingungen bestätigen. Agentisches Design zählt laut nachgereichtem Auszug 20 % der Bewertung; die aktuelle Version besitzt noch keine echte Agentenorchestrierung. Es wurde nichts beim Hackathon eingereicht und kein kostenpflichtiger Azure-Dienst angelegt.

Das Vision-Modell funktioniert ausschließlich auf den kontrollierten synthetischen Frames. Reale Fernsehbilder, OCR und Kamerakalibrierung sind nicht umgesetzt. Metriken und Erzählungen sind im Offline-Modus regelbasiert; die Oberfläche behauptet keine aktive Cloud-KI. Die Fehlerprüfung der KI ist eine Schutzschicht, kein Beweis für vollständige faktische Korrektheit.

## Prüfungen und Datenexport

```sh
node --test tests/*.test.mjs
node scripts/export-data.mjs
node scripts/benchmark.mjs
node scripts/build-standalone.mjs
```

25 automatisierte Tests prüfen unter anderem Reproduzierbarkeit, 20 Seeds, Ereignisreihenfolge, Dubletten, Zählwerte, fehlende Zukunftsdaten, Sprachen, Filter, Einblendzeiten, Pixelanalyse, API-Zugriff, SSE-Wiederaufnahme und KI-Fallbacks. Der tatsächliche Messbericht liegt in `docs/benchmark.json`.

## Projektunterlagen

| Datei | Zweck |
|---|---|
| [PROJEKT-DE.md](docs/PROJEKT-DE.md) | Produktkonzept, Differenzierung, Architektur und Anforderungsmatrix |
| [SUBMISSION-EN.md](docs/SUBMISSION-EN.md) | Ehrlicher englischer Einreichungstext mit aktuellem Implementierungsstand |
| [DEMO-SCRIPT.md](docs/DEMO-SCRIPT.md) | Vorführung in 1:50 inklusive Sprechertext; unter der Zwei-Minuten-Grenze |
| [HACKATHON-ABGLEICH.md](docs/HACKATHON-ABGLEICH.md) | Neue Pflichtangaben, Preise, Bewertungsrubrik und priorisierte Lücken |
| [AZURE-SETUP.md](docs/AZURE-SETUP.md) | Modellanbindung und Azure-Bereitstellung |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Datenfluss, Komponenten, Sicherheit und Skalierungsgrenzen |
| [DATA-CARD.md](docs/DATA-CARD.md) | Herkunft, Formeln, Vereinfachungen und Grenzen der Daten |
| [API.md](docs/API.md) | Server-Verträge, SSE und Overlay-Schema |
| [EVALUATION.md](docs/EVALUATION.md) | Was geprüft wurde und was noch live geprüft werden muss |
| [RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) | Letzte Schritte bis zur tatsächlichen Abgabe |

## Aufbau

```text
dist/          Browser-App und gemeinsam genutzte Analyse-/Vision-Module
server.mjs     HTTP-Server, geschützte API, synthetischer SSE-Feed
narrator.mjs   Azure-OpenAI-Adapter und Ausgabeprüfung
tests/         Automatisierte fachliche und HTTP-Tests
data/          722 synthetische Events (Seed 42), Overlay und Zusammenfassung
infra/         Azure Container Apps Bicep und Parameterbeispiel
docs/          Projekt, Einreichung, Demo, Betrieb und Bewertung
scripts/       Reproduzierbarer Export und lokaler Benchmark
```

Es werden keine echten Premier-League-Daten oder Markenassets verwendet. Die Namen und Clubs sind fiktiv. Touchline ist ein unabhängiger Prototyp und kein offizielles Produkt von Microsoft oder der Premier League.
