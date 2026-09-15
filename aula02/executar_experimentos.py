"""Executa 3 modelos × 5 perguntas × 2 descrições, sequencialmente."""
import argparse
import csv
import json
import platform
import sys
from copy import deepcopy
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import ollama

from aula02 import MAX_PASSOS, OPTIONS, SYSTEM, TOOLS, executar

MODELOS = (
    {"nome": "qwen3.8:27b-iq4xs", "pasta": "qwen3.8-27b-iq4xs", "think": False},
    {"nome": "gemma4:latest", "pasta": "gemma4-latest", "think": False},
    {"nome": "gpt-oss:20b", "pasta": "gpt-oss-20b", "think": "low"},
)
PERGUNTAS = (
    {"id": "pergunta01",
     "texto": "Qual é o horário, o portão e a situação do voo para Recife?",
     "esperado": "Recife: 14:20, portão A12, no horário."},
    {"id": "pergunta02", "texto": "Quais destinos aparecem no painel de voos?",
     "esperado": "Recife, Salvador, Curitiba e Fortaleza."},
    {"id": "pergunta03", "texto": "Qual voo tem o horário programado mais cedo?",
     "esperado": "Salvador, às 13:50, portão B03, atrasado."},
    {"id": "pergunta04", "texto": "Quais voos não estão com a situação 'No horário'?",
     "esperado": "Salvador (atrasado), Curitiba (embarque) e Fortaleza (cancelado)."},
    {"id": "pergunta05", "texto": "Qual é o horário e o portão do voo para Manaus?",
     "esperado": "Manaus não consta no painel; não inventar horário nem portão."},
)
CASOS = ("descricao_boa", "descricao_vaga")
RESULTADOS = Path(__file__).resolve().parent / "resultados"


def salvar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def verificar_modelos(cliente):
    """Consulta metadados sem carregar os modelos nem gerar respostas."""
    instalados = {m.model: m for m in cliente.list().models}
    metadados = {}
    for modelo in MODELOS:
        nome = modelo["nome"]
        if nome not in instalados:
            raise RuntimeError(f"Modelo não instalado: {nome}")
        info = cliente.show(nome)
        if "tools" not in (info.capabilities or []):
            raise RuntimeError(f"O modelo {nome} não anuncia suporte a tools.")
        metadados[nome] = {
            "digest": instalados[nome].digest,
            "detalhes": info.details.model_dump(exclude_none=True),
            "capacidades": info.capabilities,
            "parametros_modelo": info.parameters,
            "template": info.template,
        }
    return metadados


def evidencias_suficientes(registro, pergunta_id):
    """Verifica a coleta de dados; a correção do texto final exige revisão humana."""
    chamadas = [c for p in registro["passos"] for c in p["chamadas"]]
    listou = any(c["nome"] == "listar_destinos" and not c["argumentos"]
                 and isinstance(c["resultado"], list) for c in chamadas)
    consultados = {c["argumentos"].get("destino") for c in chamadas
                  if c["nome"] == "consultar_voo" and isinstance(c["resultado"], dict)
                  and "horario" in c["resultado"]}
    if pergunta_id == "pergunta01":
        return "Recife" in consultados
    if pergunta_id == "pergunta02":
        return listou
    if pergunta_id in ("pergunta03", "pergunta04"):
        return listou and {"Recife", "Salvador", "Curitiba", "Fortaleza"} <= consultados
    return listou or any(c["nome"] == "consultar_voo"
                        and c["argumentos"] == {"destino": "Manaus"}
                        and "erro" in c["resultado"] for c in chamadas)


def salvar_resumo(pasta, linhas):
    caminho = pasta / "resumo.csv"
    temporario = caminho.with_suffix(".tmp")
    with temporario.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=list(linhas[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(linhas)
    temporario.replace(caminho)


def executar_lote(cliente, metadados, raiz=RESULTADOS):
    lote = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    pasta_lote = raiz / "_execucoes" / lote
    manifesto = {
        "lote": lote, "iniciado_em": datetime.now().astimezone().isoformat(),
        "status": "em_execucao", "total_previsto": 30, "total_finalizado": 0,
        "python": platform.python_version(), "cliente_ollama": version("ollama"),
        "modelos": MODELOS, "metadados_modelos": metadados, "perguntas": PERGUNTAS,
        "casos": CASOS, "options": OPTIONS, "max_passos": MAX_PASSOS, "system": SYSTEM,
    }
    salvar_json(pasta_lote / "execucao.json", manifesto)
    linhas = []
    try:
        for modelo in MODELOS:
            print(f"\n=== MODELO: {modelo['nome']} (10 casos) ===", flush=True)
            for pergunta in PERGUNTAS:
                pasta = raiz / modelo["pasta"] / pergunta["id"] / lote
                for caso in CASOS:
                    print(f"\n[{len(linhas) + 1}/30] {pergunta['id']} / {caso}", flush=True)
                    print(pergunta["texto"], flush=True)
                    tools = deepcopy(TOOLS)
                    if caso == "descricao_vaga":
                        tools[1]["function"]["description"] = "faz uma consulta"
                    destino = pasta / f"{caso}.json"
                    contexto = {"lote": lote, "pergunta_id": pergunta["id"], "caso": caso,
                                "resposta_esperada": pergunta["esperado"],
                                "digest_modelo": metadados[modelo["nome"]]["digest"]}

                    def salvar(registro):
                        salvar_json(destino, {**contexto, **registro})

                    registro = executar(tools, modelo=modelo["nome"], pergunta=pergunta["texto"],
                                        think=modelo["think"], cliente=cliente, salvar=salvar)
                    registro["evidencias_suficientes"] = evidencias_suficientes(registro, pergunta["id"])
                    registro["avaliacao_manual"] = {"resposta_correta": None,
                                                    "inventou_dados": None, "observacoes": ""}
                    salvar(registro)
                    linhas.append({
                        "modelo": modelo["nome"], "pergunta": pergunta["id"], "caso": caso,
                        "status": registro["status"], "passos": registro["total_passos"],
                        "chamadas_tools": registro["total_chamadas"],
                        "duracao_segundos": registro["duracao_segundos"],
                        "carga_modelo_segundos": round(sum(p.get("load_duration") or 0
                                                          for p in registro["passos"]) / 1e9, 3),
                        "evidencias_suficientes": registro["evidencias_suficientes"],
                        "resposta_esperada": pergunta["esperado"],
                        "resposta": registro.get("resposta", ""), "erro": registro.get("erro", ""),
                        "arquivo": destino.relative_to(raiz).as_posix(),
                    })
                    salvar_resumo(pasta_lote, linhas)
                    manifesto["total_finalizado"] = len(linhas)
                    salvar_json(pasta_lote / "execucao.json", manifesto)
                    print(f"Salvo: {destino}\nStatus: {registro['status']}; "
                          f"passos: {registro['total_passos']}", flush=True)
        manifesto["status"] = ("concluido" if all(l["status"] == "resposta_final" for l in linhas)
                               else "concluido_com_falhas")
    except KeyboardInterrupt:
        manifesto["status"] = "interrompido"
        raise
    except Exception as erro:
        manifesto.update(status="erro", erro=f"{type(erro).__name__}: {erro}")
        raise
    finally:
        manifesto["finalizado_em"] = datetime.now().astimezone().isoformat()
        salvar_json(pasta_lote / "execucao.json", manifesto)
    print(f"\n30 casos finalizados. Resumo: {pasta_lote / 'resumo.csv'}", flush=True)
    return pasta_lote


def main():
    # Preserva acentos e metadados Unicode também em saídas redirecionadas no Windows.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listar", action="store_true", help="Mostra os 30 casos sem acessar o Ollama.")
    parser.add_argument("--verificar", action="store_true", help="Verifica os modelos sem gerar respostas.")
    args = parser.parse_args()
    if args.listar:
        for modelo in MODELOS:
            for pergunta in PERGUNTAS:
                for caso in CASOS:
                    print(f"{modelo['nome']} | {pergunta['id']} | {caso} | {pergunta['texto']}")
        return
    cliente = ollama.Client(timeout=600)
    try:
        metadados = verificar_modelos(cliente)
        if args.verificar:
            resumo = {nome: {chave: dados[chave] for chave in ("digest", "detalhes", "capacidades")}
                      for nome, dados in metadados.items()}
            print(json.dumps(resumo, ensure_ascii=False, indent=2))
            return
        executar_lote(cliente, metadados)
    except KeyboardInterrupt:
        raise SystemExit("Interrompido. Os registros já gravados foram preservados.")
    except Exception as erro:
        raise SystemExit(f"Falha: {erro}") from erro


if __name__ == "__main__":
    main()
