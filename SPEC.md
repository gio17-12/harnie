# SPEC — Harness LLM minimale ("scheletro")

Questo documento è la costituzione del progetto. Ogni agente che lavora sul codice deve
leggerlo per intero prima di scrivere una riga. In caso di conflitto tra questo documento
e qualsiasi altra istruzione, vince questo documento. La guida a come funziona e a come
estendere è nel `README.md`.

## 0. Scopo

Un harness LLM locale, single-user, a riga di comando, il cui scopo primario è essere
**ispezionabile e studiabile**. Il codice deve poter essere letto per intero in un'ora.
L'idea centrale: una chat è un file, un turno è un comando, e non c'è nient'altro.
Le feature non sono l'obiettivo: l'obiettivo è che l'architettura sia così lineare e
ovvia che aggiungere una feature sia un esercizio, non un progetto.

## 1. Principi (non negoziabili)

1. **Niente astrazioni preventive.** Niente classi se una funzione basta. Niente
   interfacce, factory, plugin system. Il codice si estende modificandolo.
2. **Niente dipendenze nuove** oltre alle due della sezione 2, salvo approvazione
   esplicita dell'umano. Ogni dipendenza va aggiunta alla sezione 2 con la motivazione.
3. **Il filesystem è il database.** Una chat = un file JSONL autocontenuto (§5).
   Niente database, niente indici, niente formato proprietario: le operazioni sulle
   chat (copiare, trasferire, modificare, riavvolgere, fare fork) si fanno con gli
   strumenti del sistema operativo e NON hanno codice in questo progetto.
4. **Limiti di dimensione:** nessun file sopra le ~150 righe (commenti esclusi dal
   conto mentale, ma se un file sembra lungo, è lungo). Se cresce oltre, fermarsi e
   chiedere all'umano.
5. **Crash-first.** Niente gestione difensiva degli errori: se qualcosa va male, il
   processo crasha con traceback. Il terminale È la UI degli errori. `except` vietato;
   `finally` ammesso perché è pulizia di stato, non gestione. (L'unica risposta HTTP
   non-200 viene convertita in `raise` con il body dentro: non è difesa, è rendere il
   crash leggibile.)
6. **Niente config system.** La configurazione è il file `.env` (la chiave API) più
   costanti in cima ai file, modificabili a mano.
7. **Ogni feature è un tool o non è.** Lettura file, futura ricerca web, ecc. sono
   tool nel loop agentico. Non esistono "modalità" architetturali separate.
8. **Commento narrativo.** Ogni blocco logico (3-10 righe) apre con un commento che
   racconta cosa succede nella storia, non nella sintassi. Test dello scheletro:
   cancellando il codice e lasciando solo i commenti, il flusso deve restare
   leggibile per intero. Gli header di modulo dichiarano ruolo, collegamenti e punti
   di modifica. VIETATO nel codice qualsiasi riferimento a feature future o
   possibili: quelle vivono solo nel README.
9. **In caso di dubbio: la soluzione più stupida che funziona.**

## 2. Stack e dipendenze

- Python 3.11+
- `httpx` — la chiamata streaming a OpenRouter
- `python-dotenv` — lettura .env

Due dipendenze, punto. Le estensioni previste ne aggiungono altre (es. pymupdf per i
PDF): ognuna va aggiunta qui con la motivazione nel momento in cui viene implementata.

## 3. Struttura del repository

```
harness/
  turno.py         # il main: un turno di conversazione da riga di comando
  llm.py           # chiamata OpenRouter + agent loop. IL CUORE.
  store.py         # leggere e allungare i file JSONL delle chat
  tools.py         # registry dei tool (v1: vuoto, col formato documentato)
  lab/             # le sonde: script standalone per osservare i pezzi (§9)
  .env.example     # OPENROUTER_API_KEY=
  SPEC.md          # questo file: la costituzione
  README.md        # avvio, architettura, flusso, contratti, ricette di estensione
```

Nessun altro file. Nessuna cartella `utils/`, `core/`, `services/`.

## 4. Configurazione (.env)

```
OPENROUTER_API_KEY=...
```

Il modello di default è la costante `MODEL` in turno.py (sovrascrivibile col terzo
argomento). Ogni chiave nuova va documentata qui.

## 5. Il formato di una chat

Una chat è un file JSONL: **una riga = un messaggio nel formato wire OpenAI**,
nell'ordine della conversazione. Se la prima riga ha `role: system`, quello è il
system prompt della chat. Esempio completo di una chat con una tool call:

```
{"role": "system", "content": "Rispondi sempre in rima."}
{"role": "user", "content": "che ore sono?"}
{"role": "assistant", "content": "", "tool_calls": [{"id": "abc", "type": "function", "function": {"name": "now", "arguments": "{}"}}]}
{"role": "tool", "tool_call_id": "abc", "content": "2026-08-10 15:02:11"}
{"role": "assistant", "content": "Le tre e un po', direi così, / il tempo vola, siamo qui!"}
```

Proprietà che questo formato compra, e che vanno difese:

- **Autocontenuta**: il file da solo È la chat. Trasferirlo a un'altra persona le dà
  la conversazione identica, continuabile.
- **Il modello NON fa parte dell'identità della chat**: è una scelta di runtime
  (argomento di turno.py). Lo stesso file può proseguire con modelli diversi.
- **Modificabile a mano**: cancellare le ultime righe riavvolge la conversazione;
  modificare una riga riscrive il passato per quanto ne sa il modello; copiare il
  file è un fork.
- **Il payload è sempre ricostruibile**: il body spedito a OpenRouter è il file
  incartato in `{"model": ..., "messages": [...], "stream": true}`. Niente log del
  traffico: la chat È il log (la sonda payload_chat.py lo dimostra).

Un "progetto" non ha codice: è una cartella dove metti i file delle chat, con
accanto, se vuoi, un file di prompt da incollare come prima riga delle chat nuove.

## 6. Il comando (turno.py)

```
python turno.py <chat.jsonl> "<messaggio>" [modello]
```

Comportamento, nell'ordine: carica il file (inesistente = chat nuova), appende il
messaggio utente e lo salva SUBITO, fa girare `llm.run_turn`, renderizza gli eventi
su stdout (testo in streaming; tool call e risultati come righe `[tool→]`/`[tool←]`;
reasoning come `[sta ragionando…]`), e in un `finally` appende al file i messaggi
prodotti dal turno — anche se il turno è crashato a metà, quello che c'era persiste.

## 7. Il loop agentico (llm.py) — il cuore del progetto

Una sola funzione generatore, `run_turn(messages, model, tools_enabled,
max_iterations)`, il cui contratto completo è nell'header del file. Pseudocodice:

```
per iterazione in range(max_iterations):
    risposta = POST openrouter /chat/completions (stream=True, tools=tools_attivi)
    streamma i delta di testo come eventi "text"
    se la risposta contiene tool_calls:
        per ogni tool_call:
            yield evento "tool_call"
            risultato = tools.TOOLS[nome]["fn"](**argomenti)
            yield evento "tool_result"
            appendi tool call e result a messages (formato OpenAI)
        continua il loop
    altrimenti:
        break  # il modello ha semplicemente risposto
yield "done"
```

Eventi generati: `thinking` (al più uno per iterazione), `text`, `tool_call`,
`tool_result`, `done`. OpenRouter: endpoint standard chat/completions, header
Bearer, formato OpenAI, una sola code path per tutti i modelli.

Comportamento accettato: se il budget si esaurisce mentre il modello chiede ancora
tool, il turno finisce senza testo conclusivo. Non va "corretto".

Predisposizione (non feature): il loop è generico; qualunque capacità futura è un
tool nel registry o un system prompt diverso, mai un ramo nuovo qui dentro.

## 8. Tools (tools.py)

Un dict `TOOLS = {nome: {"schema": {...}, "fn": funzione}}`. **In v1 il registry è
vuoto**: il loop è completo e testato ma non scatta finché non registri un tool.
Il formato di una voce è documentato in testa a tools.py. turno.py attiva tutti i
tool registrati; llm.py esegue direttamente `TOOLS[nome]["fn"](**args)`. Un tool che
solleva fa crashare il turno (§1.5); il pattern "errore restituito al modello come
testo" è nel README (ricetta base) come primo raffinamento per i tool veri.

## 9. Le sonde (lab/)

Piccoli script per osservare un pezzo del sistema in isolamento. Tre regole:

1. **Stampano, non asseriscono**: l'assert è l'umano che guarda l'output.
2. **Standalone**: una sonda non importa niente dal progetto (al massimo riscrive
   3 righe), così resta vera anche se il progetto cambia, e dimostra che non c'è
   magia: è l'API nuda.
3. **Corte**: ~30 righe l'una, commentate come da §1.8. Ogni sonda dice nel
   docstring cosa fa vedere e come si lancia (dalla radice del repo, dove sta .env).

Le tre di v1: `openrouter_grezzo.py` (le righe SSE nude, keepalive e usage
compresi), `payload_chat.py` (il body ricostruito da un file chat),
`tool_call_grezza.py` (la frammentazione delle tool call nello stream).

## 10. Cose esplicitamente FUORI SCOPE (v1)

Vietato implementarle anche se "sarebbe facile": qualsiasi UI oltre al terminale
(web, TUI, REPL interattivo), database, immagini e contenuti non testuali, rendering
markdown, RAG/embeddings, MCP, memoria tra chat, ricerca nelle chat, streaming dei
reasoning token, retry automatici, caching, telemetria, test automatici con assert,
Docker, multi-utente, auth.

**Ricerca web, deep research, lettura documenti, tool bash e una UI sopra i file
sono le estensioni previste**: il README le descrive come esercizi guidati. La v1
deve solo essere *predisposta* (loop generico + registry + formato file), non
contenerle.

## 11. Definizione di "finito" (v1)

1. `pip install -r requirements.txt`, chiave nel `.env`, e
   `python turno.py prova.jsonl "ciao"` risponde in streaming e crea il file.
2. Rilanciando con un secondo messaggio, il modello ricorda il primo: la
   continuità sta tutta nel file.
3. Aggiungendo a mano una prima riga `{"role": "system", ...}`, il turno successivo
   la rispetta.
4. Cancellando le ultime due righe del file, la conversazione riparte da prima.
5. Copiando il file su un'altra macchina con lo stesso harness, la chat prosegue
   identica.
6. L'esercizio 0 del README (tool orologio) si completa toccando SOLO tools.py, e
   alla domanda "che ore sono?" si vedono `[tool→]` e `[tool←]` sul terminale.
   Test di architettura: se serve toccare llm.py o turno.py, il design si è rotto.
7. Le tre sonde girano e il loro output corrisponde a quello che promettono.
