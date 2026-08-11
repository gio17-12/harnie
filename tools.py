"""Il registry dei tool: puro dato, nessuna logica.

Collegamenti: importato da llm.py (che manda gli "schema" a OpenRouter ed esegue
le "fn" con fn(**args)) e da turno.py (che attiva list(TOOLS)). In v1 il registry
è vuoto: il loop agentico è completo ma non scatta finché non registri un tool.

Per aggiungere un tool: una funzione + una voce qui, nient'altro (ricette pronte
nel README). Formato di una voce:

TOOLS["nome"] = {
    "schema": {          # JSON Schema formato OpenAI: è ciò che il modello vede
        "name": "nome",
        "description": "Cosa fa, scritto per il modello.",
        "parameters": {"type": "object",
                       "properties": {"argomento": {"type": "string"}},
                       "required": ["argomento"]},
    },
    "fn": funzione,      # def funzione(argomento): return "risultato come stringa"
}

I nomi dei parametri nello schema devono coincidere con quelli della funzione:
llm.py esegue fn(**args) con gli argomenti così come il modello li ha scritti.
Un tool che solleva un'eccezione fa crashare il turno (SPEC §1.5).
"""

TOOLS = {}
