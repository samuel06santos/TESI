"""Escolhe um horário e cria um agendamento pelo servidor MCP da AP1."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport


SERVIDOR = Path(__file__).with_name("server.py")


async def agendar(api_url: str, unidade_id: int, servico_id: int, data: str) -> None:
    sessao = getpass.getpass("Valor do cookie SESSION (não será exibido): ").strip()
    if not sessao:
        raise ValueError("A sessão é obrigatória para criar um agendamento")

    ambiente = os.environ.copy()
    ambiente["ESTILO_MARCADO_API_URL"] = api_url
    ambiente["ESTILO_MARCADO_SESSION"] = sessao
    del sessao

    async with Client(PythonStdioTransport(SERVIDOR, env=ambiente)) as mcp:
        servicos = (await mcp.call_tool("listar_servicos", {"unidade_id": unidade_id})).data
        servico = next((item for item in servicos if item["id"] == servico_id), None)
        if servico is None:
            raise ValueError("Serviço não encontrado na filial")

        resposta = (await mcp.call_tool("consultar_horarios", {
            "unidade_id": unidade_id, "servico_id": servico_id, "data": data,
        })).data
        horarios = resposta["horarios"]
        if not horarios:
            print("Não há horários disponíveis nessa data.")
            return

        profissionais = {p["id"]: p["nome"] for p in servico["profissionais"]}
        print(f"\n{servico['unidadeNome']} — {servico['nome']} — R$ {servico['preco']:.2f}")
        print(f"Horários em {data} ({resposta['fusoHorario']}):")
        for indice, horario in enumerate(horarios, 1):
            nome = profissionais.get(horario["profissionalId"], str(horario["profissionalId"]))
            print(f"{indice:>2}. {horario['inicio'][11:16]} — {nome}")

        escolha = input("\nNúmero do horário desejado (Enter cancela): ").strip()
        if not escolha:
            print("Cancelado; nenhum agendamento foi criado.")
            return
        if not escolha.isdigit() or not 1 <= int(escolha) <= len(horarios):
            raise ValueError("Número de horário inválido")
        horario = horarios[int(escolha) - 1]
        nome = profissionais.get(horario["profissionalId"], str(horario["profissionalId"]))
        print(f"Reserva: {servico['unidadeNome']}, {servico['nome']}, {data} "
              f"às {horario['inicio'][11:16]}, com {nome}, R$ {servico['preco']:.2f}.")
        if input("Digite AGENDAR para confirmar: ").strip() != "AGENDAR":
            print("Cancelado; nenhum agendamento foi criado.")
            return

        chave = str(uuid4())
        try:
            resultado = (await mcp.call_tool("criar_agendamento", {
                "unidade_id": unidade_id,
                "servico_id": servico_id,
                "profissional_id": horario["profissionalId"],
                "inicio": horario["inicio"],
                "chave_idempotencia": chave,
            })).data
        except Exception:
            print(f"Falha na tentativa; chave de idempotência: {chave}")
            raise
        print("Agendamento criado pelo MCP:")
        print(json.dumps(resultado, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="https://estilomarcado.samuelsantos.qzz.io")
    parser.add_argument("--unidade-id", type=int, default=1000)
    parser.add_argument("--servico-id", type=int, default=1000)
    parser.add_argument("--data", default=(date.today() + timedelta(days=1)).isoformat())
    args = parser.parse_args()
    asyncio.run(agendar(args.api_url, args.unidade_id, args.servico_id, args.data))


if __name__ == "__main__":
    main()
