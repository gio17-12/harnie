"""La persistenza: una chat è un file JSONL, e questo file sa solo leggerlo e allungarlo.

Collegamenti: importato da turno.py. Non sa cos'è OpenRouter né cos'è un turno:
vede solo righe JSON. Il formato è in SPEC §5: una riga = un messaggio formato
OpenAI, la prima riga può essere il system prompt (role: system).

Per modificare: qui non dovrebbe servire quasi mai. Le operazioni "avanzate"
(fork, riavvolgimento, trasferimento) non hanno codice: sono cp, editor, scp.
"""
import json
import os


def load(path):
    # Chat inesistente = chat nuova: lista vuota, nessun errore. È l'unico "if"
    # di tutto il file, e serve perché "parti da zero" è un caso d'uso, non un guasto.
    if not os.path.exists(path):
        return []
    # Una riga = un messaggio. Le righe vuote si ignorano (un editor può lasciarne).
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append(path, message):
    # Append puro: mai riscrittura. Il file cresce solo in coda, come la conversazione.
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(message, ensure_ascii=False) + "\n")
