"""L'harness completo, in un comando:

    python src/harness/main.py <chat.jsonl> "<messaggio>" [modello]

Appende il messaggio alla chat (creandola se non esiste), fa girare il loop
agentico, stampa su stdout ogni cosa che arriva (reasoning, testo, tool call e
risultati, per intero, senza streaming né placeholder) e appende al file quello
che il turno ha prodotto. Non c'è altro: il "prodotto" è tutto qui.

Collegamenti: importa store (leggere/allungare il file), llm (il loop) e tools
(la lista dei tool attivi). È l'unico file con un main: llm, store e tools sono
librerie mute.

Per modificare: il rendering degli eventi a terminale è l'elif qui sotto; il
modello di default è la costante MODEL; tutto il resto vive negli altri file.
"""
import json
import sys

from dotenv import load_dotenv

import llm
import store
import tools

MODEL = "deepseek/deepseek-v4-flash-0731"  # usato se non passi il terzo argomento


def main():
    load_dotenv()  # la chiave OpenRouter arriva dal file .env

    # Gli argomenti, senza cerimonie: se mancano, IndexError e traceback (SPEC §1.5).
    path = sys.argv[1]
    content = sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else MODEL

    # La chat È il file: la carico tutta, appendo il tuo messaggio, e lo salvo
    # subito — così è già nel file anche se il turno crasha tra un istante.
    messages = store.load(path)
    user_msg = {"role": "user", "content": content}
    messages.append(user_msg)
    store.append(path, user_msg)

    # Da qui in poi il loop produce messaggi nuovi in coda a `messages`:
    # mi segno dove finisce il "prima" per sapere cosa salvare alla fine.
    start = len(messages)
    try:
        # run_turn è un generatore di eventi: qui si decide solo come mostrarli.
        for event in llm.run_turn(messages, model, list(tools.TOOLS), llm.MAX_ITERATIONS):
            if event["type"] == "reasoning":
                print(f"[reasoning] {event['text']}", flush=True)
            elif event["type"] == "text":
                print(event["text"], flush=True)   # la risposta intera, non a pezzi
            elif event["type"] == "tool_call":
                print(f"[tool→] {event['name']} {json.dumps(event['args'], ensure_ascii=False)}",
                      flush=True)
            elif event["type"] == "tool_result":
                print(f"[tool←] {event['preview']}", flush=True)
    finally:
        # finally = pulizia, non gestione (SPEC §1.5): anche un turno crashato
        # a metà persiste i messaggi che ha fatto in tempo a produrre.
        for msg in messages[start:]:
            store.append(path, msg)


main()
