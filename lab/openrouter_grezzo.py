"""Sonda: cosa passa DAVVERO sul filo tra noi e OpenRouter.

Fa una singola chiamata in streaming e stampa ogni riga ricevuta con repr(),
così vedi anche le righe vuote, i keepalive (": OPENROUTER PROCESSING"), i
chunk di soli metadati (usage, costi) e il "[DONE]" finale — tutto ciò che
llm.py normalmente filtra via.

Si lancia dalla radice del repo (dove sta il .env):
    python lab/openrouter_grezzo.py "conta fino a 3"

Come tutte le sonde: stampa, non asserisce — l'assert sei tu. E non importa
niente dal progetto: quello che vedi qui è l'API nuda, riproducibile ovunque.
"""
import os
import sys

import httpx
from dotenv import load_dotenv

MODEL = "anthropic/claude-sonnet-4-6"

load_dotenv()

# Il payload minimo che esista: modello, un messaggio, streaming attivo.
payload = {
    "model": MODEL,
    "messages": [{"role": "user", "content": sys.argv[1] if len(sys.argv) > 1 else "ciao"}],
    "stream": True,
}

with httpx.stream("POST", "https://openrouter.ai/api/v1/chat/completions",
                  headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
                  json=payload, timeout=300) as resp:
    print(f"HTTP {resp.status_code}")
    for line in resp.iter_lines():
        print(repr(line))  # repr: si vedono anche righe vuote e caratteri strani
