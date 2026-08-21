# Harness

Un harness LLM a riga di comando: **una chat è un file, un turno è un comando**.
Circa 300 righe di codice, due dipendenze, leggibile per intero in un'ora. Il
progetto è didattico: mostra il nucleo irriducibile di un prodotto tipo claude.ai
o ChatGPT — che, spogliato di tutto, è un loop di richieste HTTP sopra un file di
testo. La costituzione (principi, vincoli, cosa è vietato) è `SPEC.md`: leggila
prima di toccare qualsiasi cosa.

## Avvio

```
cp .env.example .env        # chiave OpenRouter (openrouter.ai → Keys)
pip install -r requirements.txt
python src/harness/main.py chats/prova.jsonl "ciao, presentati in una riga"
```

La risposta viene stampata sul terminale (si aspetta la risposta intera, niente
streaming a caratteri) e `chats/prova.jsonl` viene creato con dentro il turno —
`chats/` è la cartella (ignorata da git) dove finiscono le chat che generi
usando l'harness da questo stesso repo, così il codice in `src/` resta pulito.
Per continuare la conversazione, stesso comando con il messaggio dopo; per
cambiare modello, terzo argomento (es. `openai/gpt-5`) — il default è la
costante `MODEL` in cima a `src/harness/main.py`. Se dimentichi la chiave,
crash con `KeyError`: è il design (SPEC §1.5), non un baco.

## Cos'è una chat (la parte importante)

Apri `chats/prova.jsonl`: ogni riga è un messaggio nel formato esatto che l'API
vuole. Questo compra tutto il resto senza una riga di codice:

```
cp chats/prova.jsonl chats/fork.jsonl   # fork della conversazione
scp chats/prova.jsonl amico@host:       # trasferirla: l'altro ce l'ha IDENTICA
sed -i '$d' chats/prova.jsonl           # riavvolgere di un messaggio (o: editor)
```

`chats/` qui dentro è solo un comodo playground locale, ignorato da git. Per
un uso vero, un "progetto" (sotto) è tipicamente una cartella tutta sua,
altrove sul disco: lì `git init && git add *.jsonl` ha senso, e i branch di
quella cartella sono fork delle tue chat, non del codice dell'harness.

Il system prompt è la prima riga, se ha `role: system` — la scrivi tu, a mano:

```
{"role": "system", "content": "Rispondi sempre in rima."}
```

Un "progetto" è una cartella dove metti le chat, con accanto (se vuoi) un file col
prompt da incollare come prima riga delle nuove. Non c'è codice per questo, ed è
il punto. E il modello NON fa parte della chat: lo stesso file può proseguire oggi
con Sonnet e domani con DeepSeek — la conversazione è solo testo, il modello è una
scelta del momento.

## Com'è fatto

```
src/harness/
  main.py     l'entry point: argomenti → carica file → loop → stampa eventi → salva
  llm.py      il loop agentico: parla con OpenRouter, esegue tool, ripete   ← IL CUORE
  store.py    leggere e allungare i file JSONL (≈15 righe di sostanza)
  tools.py    registry dei tool: puro dato (v1: vuoto, col formato documentato)
  lab/        le sonde: script standalone per guardare i pezzi da vicino
chats/        le chat che generi tu, ignorata da git — non è codice
```

Il grafo delle importazioni è una linea, senza cicli:

```
main.py ──> store.py
   └──> llm.py ──> tools.py
```

`llm.py` non sa cosa sia un file né un terminale; `store.py` non sa cosa sia
OpenRouter. Ogni file apre con un header che dichiara ruolo, collegamenti e punti
di modifica, e i blocchi di codice sono narrati da commenti (SPEC §1.8): l'header
è il contratto, i commenti sono la storia, il codice la implementa. La cartella
`src/harness/` è piatta esattamente come lo era la root prima: nessun ulteriore
livello di sottocartelle oltre a `lab/` (SPEC §3) — l'unico scopo dello spostarla
sotto `src/` è separare fisicamente il codice dai file che l'harness genera
(`chats/`) e dai metadati del progetto (README, SPEC, `.env.example`), che
restano nella root.

## Il flusso di un turno

`python src/harness/main.py chat.jsonl "riassumi quanto detto finora"`:

1. `main.py` carica il file riga per riga (`store.load`: ogni riga un
   `json.loads`), appende il tuo messaggio alla lista E al file — subito, così
   esiste anche se tra un istante tutto crasha.
2. Passa la lista a `llm.run_turn`, un generatore. Questo fa la POST a OpenRouter
   con `stream: false` e aspetta la risposta intera — niente frammenti da
   ricomporre. Se il modello ha ragionato (es. gpt-5), il testo del ragionamento
   arriva per intero in un evento `reasoning`, mostrato così com'è, non dietro un
   placeholder. Il contenuto della risposta arriva per intero in un evento `text`.
   Se il modello chiama un tool, `run_turn` lo esegue (`TOOLS[nome]["fn"](**args)`),
   accoda il risultato alla conversazione come messaggio `role: tool`, e **rifà la
   richiesta da capo** con la conversazione allungata. Tutto il segreto
   dell'"agente" è questo: una richiesta HTTP dentro un ciclo `for`, con un budget
   di giri (`MAX_ITERATIONS`). In v1 il registry è vuoto, quindi il ramo tool non
   scatta mai: l'esercizio 0 serve a vederlo in azione.
3. Nel `finally`, main.py appende al file i messaggi che il turno ha prodotto:
   anche un turno crashato a metà persiste quello che c'era.

Due proprietà da interiorizzare. **Non c'è stato nascosto da nessuna parte**: né
nel processo (che muore a ogni turno), né nel modello (che rilegge tutto ogni
volta): la conversazione vive per intero nel file, e ogni turno la rispedisce
integralmente a OpenRouter — è per questo che i turni diventano più lenti e
costosi man mano che la chat cresce. E **il payload è sempre ricostruibile**: il
body spedito è il file incartato in `{"model", "messages", "stream"}` — niente da
loggare, la chat È il log (la sonda `payload_chat.py` lo stampa).

## I contratti, precisamente

**Gli eventi del loop** (prodotti da `run_turn`, consumati dall'elif di main.py),
nell'ordine in cui accadono; `done` chiude sempre un turno riuscito:

```
{"type": "reasoning", "text": "…"}                    al più uno per iterazione, solo se il modello ragiona
{"type": "text", "text": "risposta intera"}           al più uno per iterazione, non a pezzi
{"type": "tool_call", "name": "x", "args": {...}}     se il modello chiama un tool
{"type": "tool_result", "name": "x", "preview": "…"}  prime 200 battute del risultato
{"type": "done"}                                      fine turno
```

**Le righe del file** sono messaggi wire OpenAI, quattro forme possibili (system,
user, assistant con eventuali `tool_calls` e un `reasoning` opzionale, tool con
`tool_call_id`): l'esempio completo è in SPEC §5. Non esiste una forma "nostra":
ciò che sta nel file è ciò che parte sul filo — **compreso il reasoning**: se non
finisse nel file sarebbe l'unica cosa che vedi a schermo e poi sparisce per
sempre, il che romperebbe la promessa "la chat È il log".

**Una voce del registry** è documentata in testa a `tools.py`: schema JSON formato
OpenAI (ciò che il modello vede) + funzione Python (ciò che gira), nomi dei
parametri coincidenti perché l'esecuzione è `fn(**args)`.

## Le sonde (src/harness/lab/)

Tre script per guardare i pezzi in isolamento. Stampano, non asseriscono:
l'assert sei tu. E non importano niente dal progetto: sono l'API nuda, il che
dimostra che nell'harness non c'è magia. Si lanciano dalla radice del repo:

```
python src/harness/lab/openrouter_grezzo.py "conta fino a 3"   # le righe SSE come arrivano,
                                                                # keepalive e usage compresi
python src/harness/lab/payload_chat.py chats/prova.jsonl       # il body esatto che partirebbe
python src/harness/lab/tool_call_grezza.py                     # una tool call arrivare A FRAMMENTI
```

La terza è la più istruttiva: fa vedere perché una tool call in streaming arriva
a frammenti — il problema che `llm.py` evita del tutto scegliendo `stream: false`
(risposta intera o niente, mai pezzi da ricomporre). E nella prima noterai il
chunk `usage` con token e costo: l'harness non lo estrae, ma è lì ogni volta.

## Esempi reali (esempi/)

Se non vuoi (o non puoi) fare una chiamata vera per capire come si comporta
l'harness, `esempi/` ha output reali e verificati, generati con
`deepseek/deepseek-v4-flash-0731` via OpenRouter:

```
esempi/conversazione.jsonl        due turni di testo, uno con reasoning
esempi/tool.jsonl                 un turno con tool call vera (esercizio 0)
esempi/sonde/openrouter_grezzo.txt    SSE grezzo di "conta fino a 3"
esempi/sonde/payload_chat.txt         il body ricostruito da conversazione.jsonl
esempi/sonde/tool_call_grezza.txt     una tool call che arriva a frammenti
```

Apri `esempi/conversazione.jsonl` e nota una cosa non ovvia: il modello ragiona
in **inglese** ma risponde in **italiano** — il campo `reasoning` non segue
necessariamente la lingua della risposta finale, ed è un'altra ragione per cui
vale la pena salvarlo per intero invece di riassumerlo o nasconderlo dietro un
placeholder. `esempi/tool.jsonl` è stato prodotto registrando temporaneamente il
tool dell'Esercizio 0 (sotto) — il registry in `tools.py` resta comunque vuoto
di default, com'è previsto per la v1.

## Il modello degli errori: crash-first (SPEC §1.5)

Non c'è gestione difensiva da nessuna parte, ed è una scelta. Chiave mancante,
rete giù, risposta malformata, argomento dimenticato sulla riga di comando:
traceback e fine. Il terminale È la UI degli errori. `except` è vietato;
`finally` è ammesso perché è pulizia (salvare ciò che il turno ha prodotto), non
gestione. Il vantaggio didattico: ogni riga di codice fa una cosa sola, il
percorso felice. Siccome non c'è streaming, non c'è nemmeno testo parziale da
perdere: la POST a OpenRouter o torna con la risposta intera o solleva, e in quel
caso il messaggio assistant di quel giro semplicemente non viene mai prodotto —
resta nel file solo ciò che i giri precedenti hanno già completato.

## Come estendere

### La ricetta base: aggiungere un tool

Una funzione + una voce nel dict `TOOLS` di `tools.py` (formato in testa al
file). Fine: main.py attiva tutti i tool registrati, al turno dopo il modello lo
vede. La funzione ritorna una stringa; se solleva, il turno crasha. Quando
aggiungi tool veri che parlano con la rete, il primo raffinamento sensato è
restituire l'errore al modello come testo — deroga consapevole al crash-first,
fatta *dentro* il tool:

```python
def web_search(query):
    try:
        ...
    except httpx.HTTPError as e:
        return f"Errore di rete: {e}"   # il modello legge e decide come reagire
```

### Esercizio 0: l'orologio (5 minuti, zero dipendenze)

Il "hello world" del loop agentico. In `tools.py`:

```python
from datetime import datetime

def now():
    return datetime.now().isoformat(sep=" ", timespec="seconds")

TOOLS["now"] = {
    "schema": {"name": "now",
               "description": "Ritorna data e ora correnti.",
               "parameters": {"type": "object", "properties": {}}},
    "fn": now,
}
```

`python src/harness/main.py chats/t.jsonl "che ore sono?"` → vedrai `[tool→]` e
`[tool←]` seguiti dalla risposta, e nel file le due righe nuove (assistant con
tool_calls, tool col risultato). Se hai dovuto toccare altro oltre a
`src/harness/tools.py`, l'architettura si è rotta (SPEC §11.6).

### Esercizio 1: ricerca web

Un provider con API semplice (Tavily o Brave: una POST, JSON, chiave da aggiungere
a `.env` e SPEC §4). In `tools.py`: `web_search(query)` con httpx (già in
requirements), risultati concatenati come testo semplice; facoltativo
`fetch_url(url)` che scarica una pagina e strippa i tag. Nessun toggle da
costruire: i tool registrati sono sempre attivi (se vuoi selezionarli per turno,
è un argomento in più a main.py che filtra `list(tools.TOOLS)`).

### Esercizio 2: deep research

Non è un sistema: è lo stesso `run_turn` con più carburante. Serve l'esercizio 1.
Una costante `MAX_ITERATIONS_DEEP` (es. 25) in llm.py, un file di system prompt
che istruisce a cercare a fondo e incrociare fonti (che incolli come prima riga
della chat: il meccanismo esiste già!), e un modo per scegliere il budget da
main.py. Se ti scopri a progettare orchestratori e sotto-agenti, rileggi SPEC §7:
il punto didattico è che non serve.

### Esercizio 3: leggere documenti

Nel mondo-file è quasi banale: un tool `read_file(path)` che ritorna il contenuto
del file (`pathlib.Path(path).read_text()`), così puoi scrivere "leggi
appunti.md e riassumilo". Per i PDF, un ramo con pymupdf (dipendenza da motivare
in SPEC §2). L'avvertenza imparata sul campo: PDF con font malmappati producono
testo spazzatura, e la spazzatura nel contesto degrada visibilmente il modello.

### Esercizio 4: tool bash

Il più potente e il più pericoloso: dare una shell al modello.

```python
import subprocess

def bash(command):
    r = subprocess.run(command, shell=True, capture_output=True, text=True,
                       timeout=30)
    return (r.stdout + r.stderr)[:20000] or "(nessun output)"
```

**Avvertenza seria, non rituale**: il modello esegue comandi arbitrari sulla tua
macchina con i tuoi permessi, e può sbagliare o essere manipolato dal contenuto
che legge (prompt injection: una pagina web o un documento possono contenere
istruzioni che il modello esegue). Da solo e in locale è un rischio che puoi
correre consapevolmente; combinato con la ricerca web va pensato due volte. La
conferma manuale prima di eseguire (un `input()` nel rendering di `tool_call` in
main.py) è il naturale esercizio 5.

### Esercizio 6: una UI sopra i file

La UI che questo progetto NON ha è ricostruibile come strato sottile: un piccolo
server che legge gli stessi JSONL e streamma gli stessi eventi via SSE a una
pagina. Il punto didattico: la UI è un *viewer*, non il prodotto — il prodotto è
il file più il loop, e deve restare usabile senza UI.

## Regole per contribuire

1. Leggi `SPEC.md` per intero. In caso di conflitto con qualsiasi altra idea, vince la SPEC.
2. Nessuna dipendenza nuova senza aggiungerla a SPEC §2 con la motivazione.
3. Niente gestione difensiva (SPEC §1.5) e niente riferimenti a feature future nel
   codice (SPEC §1.8): il codice descrive ciò che esiste, questo README ciò che
   potrebbe esistere.
4. Ogni modulo mantiene header e narrazione aggiornati; se cambi un contratto
   (eventi del loop, formato delle righe, formato registry), aggiorna gli header,
   "I contratti" qui sopra e SPEC.
5. Le operazioni sulle chat non si implementano: sono operazioni sui file (SPEC §1.3).
6. In caso di dubbio: la soluzione più stupida che funziona.

## Ordine di lettura consigliato

`SPEC.md` → questo file → `src/harness/store.py` → `src/harness/tools.py` →
`src/harness/llm.py` → `src/harness/main.py` → le sonde in `src/harness/lab/`.
