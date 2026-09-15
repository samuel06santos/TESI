import json
from datetime import datetime
from time import perf_counter

import ollama

MODEL = "qwen3.8:27b-iq4xs"
PERGUNTA = "Qual é o horário, o portão e a situação do voo para Recife?"
MAX_PASSOS = 6
SYSTEM = (
    "Você é um assistente de aeroporto. Consulte as tools antes de responder "
    "sobre voos. Nunca invente horários, portões, destinos ou situações; use "
    "somente os dados retornados."
)
OPTIONS = {"temperature": 0, "seed": 42, "num_predict": 1024, "num_ctx": 8192}
_VOOS = {
    "Recife": {"horario": "14:20", "portao": "A12", "situacao": "No horário"},
    "Salvador": {"horario": "13:50", "portao": "B03", "situacao": "Atrasado"},
    "Curitiba": {"horario": "15:10", "portao": "C07", "situacao": "Embarque"},
    "Fortaleza": {"horario": "16:40", "portao": "A08", "situacao": "Cancelado"},
}


def listar_destinos() -> list[str]:
    """Lista os destinos dos voos exibidos no painel do aeroporto."""
    return list(_VOOS)


def consultar_voo(destino: str) -> dict:
    """Retorna horário programado, portão e situação do voo para o destino informado."""
    return _VOOS.get(
        destino, {"erro": f"Destino não encontrado no painel: {destino}"}
    ).copy()


FUNCS = {"listar_destinos": listar_destinos, "consultar_voo": consultar_voo}
TOOLS = [
    {"type": "function", "function": {
        "name": "listar_destinos", "description": listar_destinos.__doc__,
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "consultar_voo", "description": consultar_voo.__doc__,
        "parameters": {"type": "object", "properties": {"destino": {"type": "string"}},
                       "required": ["destino"], "additionalProperties": False},
    }},
]


def executar(tools: list, *, modelo=MODEL, pergunta=PERGUNTA, think=False,
             cliente=None, salvar=None) -> dict:
    """Executa uma condição com histórico novo e preserva inclusive falhas parciais."""
    cliente = cliente or ollama.Client(timeout=600)
    inicio = perf_counter()
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": pergunta}]
    registro = {"iniciado_em": datetime.now().astimezone().isoformat(), "modelo": modelo,
                "pergunta": pergunta, "max_passos": MAX_PASSOS, "options": OPTIONS.copy(),
                "think": think, "tools": tools, "passos": [], "mensagens": msgs,
                "status": "em_execucao"}
    if salvar:
        salvar(registro)
    for passo in range(1, MAX_PASSOS + 1):
        print(f"Passo {passo}: consultando o modelo...", flush=True)
        evento = {"passo": passo, "chamadas": []}
        registro["passos"].append(evento)
        # REASON: o modelo recebe todo o histórico e escolhe as ferramentas.
        try:
            r = cliente.chat(model=modelo, messages=msgs, tools=tools, think=think,
                             options=OPTIONS, keep_alive="10m")
        except Exception as erro:
            registro.update(status="erro_api", erro=f"{type(erro).__name__}: {erro}")
            evento["erro"] = registro["erro"]
            break
        except KeyboardInterrupt:
            registro.update(status="interrompido", total_passos=len(registro["passos"]),
                            duracao_segundos=round(perf_counter() - inicio, 3))
            if salvar:
                salvar(registro)
            raise
        msgs.append(r.message.model_dump(exclude_none=True))
        evento.update({campo: getattr(r, campo, None) for campo in (
            "done_reason", "total_duration", "load_duration", "prompt_eval_count",
            "prompt_eval_duration", "eval_count", "eval_duration")})
        if r.done_reason == "length":
            registro.update(status="limite_tokens", resposta=r.message.content)
            break
        if not r.message.tool_calls:
            registro["status"] = "resposta_final" if r.message.content.strip() else "resposta_vazia"
            registro["resposta"] = r.message.content
            break
        for call in r.message.tool_calls:
            nome, args = call.function.name, call.function.arguments
            # ACT: apenas funções explicitamente registradas podem ser executadas.
            try:
                resultado = FUNCS[nome](**args)
            except (KeyError, TypeError, ValueError) as erro:
                resultado = {"erro": str(erro)}
            evento["chamadas"].append({"nome": nome, "argumentos": args, "resultado": resultado})
            print(f"  {nome}({args}) -> {resultado}", flush=True)
            # OBSERVE: devolvemos os dados para a próxima iteração do modelo.
            msgs.append({"role": "tool", "tool_name": nome,
                         "content": json.dumps(resultado, ensure_ascii=False)})
        if salvar:
            salvar(registro)
    else:
        registro["status"] = "max_passos"
    registro["total_passos"] = len(registro["passos"])
    registro["total_chamadas"] = sum(len(p["chamadas"]) for p in registro["passos"])
    registro["duracao_segundos"] = round(perf_counter() - inicio, 3)
    registro["finalizado_em"] = datetime.now().astimezone().isoformat()
    if salvar:
        salvar(registro)
    return registro


if __name__ == "__main__":
    print("Para executar os 30 casos, use: python aula02/executar_experimentos.py")
