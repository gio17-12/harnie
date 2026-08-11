"""Il loop agentico: l'unico file che parla con OpenRouter.

Collegamenti: importato da turno.py, che gli passa la conversazione caricata dal
file; importa tools.py per gli schemi e le funzioni del registry. Non sa cosa sia
un file JSONL né un terminale: riceve una lista di messaggi formato OpenAI, la
modifica in place, e genera eventi (dict) che il chiamante renderizza come vuole.

Contratto di run_turn:
- input: messages (lista formato OpenAI, mutata in place), model (stringa
  OpenRouter), tools_enabled (nomi di voci di tools.TOOLS), max_iterations.
- yield, nell'ordine in cui accadono: {"type": "thinking"} (al più uno per
  iterazione), {"type": "text", "delta": str}, {"type": "tool_call", "name",
  "args"}, {"type": "tool_result", "name", "preview"}, e in chiusura
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

    # IL LOOP. Ogni giro è una chiamata a OpenRouter con la conversazione com'è
    # in quel momento. Se il modello risponde e basta, si esce; se chiama tool,
    # si eseguono, i risultati si accodano alla conversazione, e si rifà il giro:
    # il modello rilegge tutto e decide come proseguire. Tutta l'"agenticità" è qui.
    for _ in range(max_iterations):
        payload = {"model": model, "messages": messages, "stream": True}
        if tool_schemas:
            payload["tools"] = tool_schemas

        # Accumulatori del giro: il testo della risposta, le tool call (che
        # arrivano a frammenti, indicizzati), e se abbiamo già segnalato il thinking.
        text = ""
        calls = {}       # index -> {id, name, args}
        thinking = False

        # La chiamata, in streaming: la risposta arriva come SSE, righe
        # "data: {json}" chiuse da "data: [DONE]".
        with httpx.stream("POST", OPENROUTER_URL, headers=headers,
                          json=payload, timeout=300) as resp:
            if resp.status_code != 200:
                resp.read()  # httpx: il body va consumato prima di leggere .text
                raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")

            for line in resp.iter_lines():
                # Scarto tutto ciò che non è un evento dati (righe vuote, keepalive).
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    break
                chunk = json.loads(data)

                # OpenRouter manda anche chunk di soli metadati (es. usage): senza
                # choices non c'è niente da streammare.
                choices = chunk.get("choices")
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                # I modelli reasoning (es. gpt-5) pensano prima di scrivere: i loro
                # delta di reasoning non vengono streammati (SPEC §10), ma senza
                # questo evento il chiamante resterebbe muto per tutta la durata.
                if (delta.get("reasoning") or delta.get("reasoning_details")) and not thinking:
                    thinking = True
                    yield {"type": "thinking"}

                # Il testo vero e proprio: accumulato per il messaggio finale,
                # streammato subito come evento.
                if delta.get("content"):
                    text += delta["content"]
                    yield {"type": "text", "delta": delta["content"]}

                # Le tool call arrivano SPEZZATE su più delta: l'id nel primo
                # frammento, nome e argomenti a pezzi. Si riassemblano per index.
                for tc in delta.get("tool_calls") or []:
                    call = calls.setdefault(tc["index"], {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        call["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    call["name"] += fn.get("name") or ""
                    call["args"] += fn.get("arguments") or ""

        # Nessuna tool call: il modello ha semplicemente risposto. Il messaggio
        # entra in conversazione e il turno è finito.
        if not calls:
            messages.append({"role": "assistant", "content": text})
            break

        # Ci sono tool call: prima si mette in conversazione il messaggio
        # dell'assistant che le contiene (l'API esige di rivederlo al giro dopo)...
        assistant_msg = {
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {"id": calls[i]["id"], "type": "function",
                 "function": {"name": calls[i]["name"], "arguments": calls[i]["args"]}}
                for i in sorted(calls)
            ],
        }
        messages.append(assistant_msg)

        # ...poi si esegue ogni tool e il suo risultato entra in conversazione
        # come messaggio role=tool, legato alla chiamata dal tool_call_id.
        for tc in assistant_msg["tool_calls"]:
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
