"""Il loop agentico: l'unico file che parla con OpenRouter.

Collegamenti: importato da turno.py, che gli passa la conversazione caricata dal
file; importa tools.py per gli schemi e le funzioni del registry. Non sa cosa sia
un file JSONL né un terminale: riceve una lista di messaggi formato OpenAI, la
modifica in place, e genera eventi (dict) che il chiamante renderizza come vuole.

Contratto di run_turn:
- input: messages (lista formato OpenAI, mutata in place), model (stringa
  OpenRouter), tools_enabled (nomi di voci di tools.TOOLS), max_iterations.
- yield, nell'ordine in cui accadono: {"type": "reasoning", "text": str} (al più
  uno per iterazione, solo se il modello ragiona), {"type": "text", "text": str}
  (la risposta intera, non a pezzi: non streammiamo), {"type": "tool_call",
  "name", "args"}, {"type": "tool_result", "name", "preview"}, e in chiusura
  {"type": "done"}.
- effetto: appende a messages i messaggi assistant e tool prodotti; il chiamante
  li persiste (turno.py lo fa in un finally).
- errori: nessuna gestione (SPEC §1.5). Chiave mancante, rete giù, risposta
  malformata: eccezione e traceback.

Per modificare: il protocollo degli eventi si cambia qui e dove viene consumato
(l'elif di turno.py).
"""
import json
import os

import httpx

import tools

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_ITERATIONS = 5  # budget di giri del loop per turno


def run_turn(messages, model, tools_enabled, max_iterations):
    # La chiave viene dall'ambiente (caricato dal chiamante via .env). Se manca:
    # KeyError, che è tutta la gestione che serve (SPEC §1.5).
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}

    # Dal registry alla forma che l'API vuole: una lista di schemi "function".
    tool_schemas = [{"type": "function", "function": tools.TOOLS[name]["schema"]}
                    for name in tools_enabled]

    # IL LOOP. Ogni giro è una POST a OpenRouter con la conversazione com'è in
    # quel momento; si aspetta la risposta intera, niente streaming. Se il
    # modello risponde e basta, si esce; se chiama tool, si eseguono, i risultati
    # si accodano alla conversazione, e si rifà il giro: il modello rilegge tutto
    # e decide come proseguire. Tutta l'"agenticità" è qui.
    for _ in range(max_iterations):
        payload = {"model": model, "messages": messages, "stream": False}
        if tool_schemas:
            payload["tools"] = tool_schemas

        resp = httpx.post(OPENROUTER_URL, headers=headers, json=payload, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
        message = resp.json()["choices"][0]["message"]

        # I modelli reasoning (es. gpt-5) possono restituire il ragionamento in un
        # campo a parte: lo mostriamo intero e grezzo, non dietro un placeholder
        # (streaming dei reasoning token è comunque fuori scope, SPEC §10).
        if message.get("reasoning"):
            yield {"type": "reasoning", "text": message["reasoning"]}

        # "content" può essere null (l'API lo usa così quando c'è solo una tool
        # call): lo normalizziamo a stringa vuota per tenerlo omogeneo nel file.
        text = message.get("content") or ""
        if text:
            yield {"type": "text", "text": text}

        tool_calls = message.get("tool_calls")

        # Nessuna tool call: il modello ha semplicemente risposto. Il messaggio
        # entra in conversazione e il turno è finito.
        if not tool_calls:
            messages.append({"role": "assistant", "content": text})
            break

        # Ci sono tool call: arrivano già intere (niente streaming, niente
        # frammenti da riassemblare), quindi il messaggio dell'assistant entra in
        # conversazione così com'è (l'API esige di rivederlo al giro dopo)...
        messages.append({"role": "assistant", "content": text, "tool_calls": tool_calls})

        # ...poi si esegue ogni tool e il suo risultato entra in conversazione
        # come messaggio role=tool, legato alla chiamata dal tool_call_id.
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"] or "{}")
            yield {"type": "tool_call", "name": name, "args": args}
            result = tools.TOOLS[name]["fn"](**args)
            yield {"type": "tool_result", "name": name, "preview": result[:200]}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        # E si torna su: al giro dopo il modello vede i risultati e decide.

    # Se il budget si esaurisce mentre il modello chiede ancora tool, il turno
    # finisce qui senza testo conclusivo: comportamento accettato (SPEC §7).
    yield {"type": "done"}
