"""Agente Ollama que usa as ferramentas de leitura do servidor MCP da AP1."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import ollama
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport


SERVIDOR = Path(__file__).with_name("server.py")
FERRAMENTAS_PERMITIDAS = {"listar_filiais", "listar_servicos"}
MAX_PASSOS = 6


async def consultar(modelo: str, pergunta: str, api_url: str) -> str:
    # A consulta é apenas de leitura; não repassamos um cookie de sessão ao MCP.
    ambiente = {chave: valor for chave, valor in os.environ.items()
                if chave != "ESTILO_MARCADO_SESSION"}
    ambiente["ESTILO_MARCADO_API_URL"] = api_url
    transporte = PythonStdioTransport(SERVIDOR, env=ambiente)

    async with Client(transporte) as mcp:
        disponiveis = {tool.name: tool for tool in await mcp.list_tools()
                       if tool.name in FERRAMENTAS_PERMITIDAS}
        ferramentas = [
            {"type": "function", "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }}
            for tool in disponiveis.values()
        ]
        mensagens = [
            {"role": "system", "content": (
                "Você consulta filiais do Estilo Marcado usando as ferramentas. "
                "Para encontrar um serviço de corte, liste filiais e examine os serviços; "
                "confirme o serviço na filial escolhida. A busca de listar_filiais filtra "
                "o nome da filial, não o nome do serviço. Consulte páginas adicionais "
                "se necessário. Responda somente com dados recebidos e não faça reservas."
            )},
            {"role": "user", "content": pergunta},
        ]
        agente = ollama.Client(timeout=120)

        for _ in range(MAX_PASSOS):
            resposta = agente.chat(
                model=modelo,
                messages=mensagens,
                tools=ferramentas,
                think=False,
                options={"temperature": 0, "num_ctx": 8192},
            )
            mensagens.append(resposta.message.model_dump(exclude_none=True))
            chamadas = resposta.message.tool_calls or []
            if not chamadas:
                return resposta.message.content or "O modelo encerrou sem resposta."

            for chamada in chamadas:
                nome = chamada.function.name
                argumentos = chamada.function.arguments
                if nome not in disponiveis:
                    resultado = {"erro": f"Ferramenta não permitida: {nome}"}
                else:
                    try:
                        resultado = (await mcp.call_tool(nome, argumentos)).data
                    except Exception as exc:
                        resultado = {"erro": str(exc)}
                print(f"MCP: {nome}({argumentos})", flush=True)
                mensagens.append({
                    "role": "tool",
                    "tool_name": nome,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })
    return "O agente atingiu o limite de passos sem concluir a consulta."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", default="qwen3.8:27b-iq4xs")
    parser.add_argument("--api-url", default=os.getenv("ESTILO_MARCADO_API_URL", "http://localhost:8080"))
    parser.add_argument("--pergunta", default=(
        "Encontre uma filial com serviço de corte, confirme o nome e o preço "
        "de um serviço de corte nessa filial. Não faça reserva."
    ))
    args = parser.parse_args()
    print(asyncio.run(consultar(args.modelo, args.pergunta, args.api_url)))


if __name__ == "__main__":
    main()
