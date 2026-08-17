"""Sonda: il body esatto che turno.py spedirebbe a OpenRouter per una chat.

Dimostra la proprietà centrale del design: siccome il file JSONL è già in
formato wire, il payload di qualsiasi turno è ricostruibile in ogni momento —
è letteralmente il file, incartato. Niente da loggare: la chat È il log.

    python lab/payload_chat.py mia_chat.jsonl

La lettura del JSONL è riscritta qui in una riga, di proposito: una sonda non
dipende dal progetto, così resta vera anche se il progetto cambia.
"""
import json
import sys

MODEL = "anthropic/claude-sonnet-4-6"

messages = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]

payload = {"model": MODEL, "messages": messages, "stream": False}
print(json.dumps(payload, ensure_ascii=False, indent=2))
