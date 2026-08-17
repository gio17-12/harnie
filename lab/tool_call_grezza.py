"""Sonda: come arriva una tool call sul filo IN STREAMING — cioè A FRAMMENTI.

Dichiara al modello un tool finto ("ora": basta la promessa, non serve che
esista) e fa una domanda che lo costringe a usarlo, con `stream: true`. Poi
stampa le righe grezze: vedrai la tool call arrivare spezzata su più delta —
l'id nel primo frammento, il nome e gli argomenti a pezzi. Questo è il problema
che `llm.py` evita del tutto: usa `stream: false`, quindi le tool call gli
arrivano già intere, senza bisogno di riassemblare nulla.

    python lab/tool_call_grezza.py
"""
import os

import httpx
from dotenv import load_dotenv

MODEL = "anthropic/claude-sonnet-4-6"

load_dotenv()

payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "che ore sono? usa il tool."}],
    "stream": True,
    # Lo schema minimo di un tool: al modello arriva solo questa descrizione.
    "tools": [{"type": "function", "function": {
        "name": "ora",
        "description": "Ritorna l'ora corrente.",
        "parameters": {"type": "object", "properties": {}},
    }}],
}

with httpx.stream("POST", "https://openrouter.ai/api/v1/chat/completions",
                  headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                  json=payload, timeout=300) as resp:
    print(f"HTTP {resp.status_code}")
    for line in resp.iter_lines():
        print(repr(line))
