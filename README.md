# Rassegna ER

La rassegna stampa quotidiana dell'Emilia-Romagna: https://fulgei-a11y.github.io/rassegna/

Ogni mattina alle 6 GitHub Actions legge i feed delle testate locali, Gemini scrive la rassegna
divisa per sezioni e province, e la voce Paola la trasforma in un MP3 sincronizzato con il testo.

## Cosa c'è nel sito

- **Filtro per provincia** ricordato tra una visita e l'altra; con un filtro attivo l'audio legge solo quelle notizie.
- **Ricerca**, archivio delle edizioni, **PDF** per la stampa.
- **Condividi**: l'intera edizione o la singola notizia (il link porta dritto a quella notizia).
- **App installabile** (Android, iPhone, computer) che funziona anche senza rete per le edizioni già aperte.
- **Anteprima dei link** su WhatsApp, Telegram e social con immagine e descrizione.

## Fonti

Ansa, Resto del Carlino (tutte le edizioni), i siti "Today" di ogni provincia, Estense, PiacenzaSera, IlPiacenza,
Reggionline, ReggioSera, SulPanaro, RavennaNotizie, ParmaDaily, AltaRimini e, tramite Google News, Gazzetta di Parma,
Libertà, Corriere Romagna, Corriere di Bologna, Repubblica Bologna, Gazzetta di Reggio e di Modena, Nuova Ferrara, Dire.
Nessuna testata può superare il 28% delle notizie passate a Gemini (`MAX_SHARE`), così la rassegna resta varia.
L'elenco è in `RSS_FEEDS`, all'inizio di `tools/fetch_and_analyze.py`.

## Avviso in caso di problemi

Alla fine di ogni aggiornamento `tools/check_health.py` controlla che l'edizione del giorno esista, sia scritta
da Gemini, abbia abbastanza notizie e l'audio. Se qualcosa non va, il workflow apre una **issue** nel repository
("⚠️ Rassegna: aggiornamento non riuscito"): GitHub la manda per e-mail. Al primo aggiornamento riuscito la issue
si chiude da sola. Lo stato dell'ultima esecuzione è anche in `stato.json`.

## File

| File | A cosa serve |
|---|---|
| `index.html` | il sito (una sola pagina) |
| `manifest.webmanifest`, `sw.js`, `icons/` | app installabile, icone, immagine di anteprima |
| `tools/fetch_and_analyze.py` | legge le fonti e scrive la rassegna con Gemini |
| `tools/build_audio.py` | genera l'MP3 con la voce Paola |
| `tools/check_health.py` | controllo finale e testo dell'avviso |
| `.github/workflows/daily.yml` | l'aggiornamento automatico di ogni mattina |
