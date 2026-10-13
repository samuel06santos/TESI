"""Ferramentas MCP que operam a API HTTP do Estilo Marcado."""

from __future__ import annotations

import os
from datetime import date, datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from fastmcp import FastMCP


mcp = FastMCP("Estilo Marcado AP1")


class EstiloMarcadoAPI:
    def __init__(
        self,
        base_url: str | None = None,
        session_cookie: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        url = (base_url or os.getenv("ESTILO_MARCADO_API_URL", "http://localhost:8080")).rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query:
            raise ValueError("ESTILO_MARCADO_API_URL deve ser a origem HTTP(S) da API, sem caminho")
        self.base_url = url
        self.session_cookie = session_cookie if session_cookie is not None else os.getenv("ESTILO_MARCADO_SESSION", "")
        self.transport = transport

    def _client(self) -> httpx.Client:
        client = httpx.Client(base_url=self.base_url, timeout=15, transport=self.transport)
        if self.session_cookie:
            client.cookies.set("SESSION", self.session_cookie)
        return client

    @staticmethod
    def _result(response: httpx.Response) -> object:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = str(body.get("message") or body.get("mensagem") or body.get("erro") or "")
            except ValueError:
                pass
            raise ValueError(f"API Estilo Marcado: HTTP {response.status_code}" + (f" — {message}" if message else "")) from exc
        return response.json()

    def get(self, path: str, params: dict[str, object] | None = None) -> object:
        try:
            with self._client() as client:
                return self._result(client.get(path, params=params))
        except httpx.RequestError as exc:
            raise ValueError(f"Não foi possível acessar a API Estilo Marcado: {exc.__class__.__name__}") from exc

    def post_authenticated(self, path: str, body: dict[str, object], key: str) -> object:
        if not self.session_cookie:
            raise ValueError("Configure ESTILO_MARCADO_SESSION para usar ferramentas de escrita")
        try:
            with self._client() as client:
                csrf = self._result(client.get("/api/autenticacao/csrf"))
                if not isinstance(csrf, dict) or not csrf.get("token"):
                    raise ValueError("A API não retornou token CSRF")
                response = client.post(
                    path,
                    json=body,
                    headers={"X-XSRF-TOKEN": str(csrf["token"]), "Idempotency-Key": key},
                )
                return self._result(response)
        except httpx.RequestError as exc:
            raise ValueError(f"Não foi possível acessar a API Estilo Marcado: {exc.__class__.__name__}") from exc


def api() -> EstiloMarcadoAPI:
    return EstiloMarcadoAPI()


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def listar_filiais(busca: str = "", pagina: int = 1, tamanho: int = 12) -> object:
    """Liste filiais públicas da AP1. Use para encontrar a filial e seu ID antes de consultar serviços."""
    if pagina < 1 or not 1 <= tamanho <= 50:
        raise ValueError("pagina deve ser >= 1 e tamanho deve estar entre 1 e 50")
    return api().get("/api/filiais/publicas", {"busca": busca, "pagina": pagina, "tamanho": tamanho})


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def listar_servicos(unidade_id: int) -> object:
    """Liste serviços e profissionais ativos de uma filial. Use depois de descobrir o ID da filial."""
    if unidade_id < 1:
        raise ValueError("unidade_id deve ser positivo")
    return api().get(f"/api/unidades/{unidade_id}/servicos")


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def consultar_horarios(unidade_id: int, servico_id: int, data: str, profissional_id: int | None = None) -> object:
    """Consulte horários reais de um serviço numa data YYYY-MM-DD. Use antes de propor ou criar uma reserva."""
    if unidade_id < 1 or servico_id < 1 or (profissional_id is not None and profissional_id < 1):
        raise ValueError("IDs devem ser positivos")
    try:
        date.fromisoformat(data)
    except ValueError as exc:
        raise ValueError("data deve estar em YYYY-MM-DD") from exc
    params: dict[str, object] = {"data": data}
    if profissional_id is not None:
        params["profissionalId"] = profissional_id
    return api().get(f"/api/unidades/{unidade_id}/servicos/{servico_id}/horarios", params)


@mcp.tool(
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    meta={"anthropic/requiresUserInteraction": True},
)
def criar_agendamento(
    unidade_id: int,
    servico_id: int,
    profissional_id: int,
    inicio: str,
    chave_idempotencia: str | None = None,
) -> object:
    """Crie um agendamento real após o usuário autorizar a reserva. Use IDs e início retornados por consultar_horarios; reutilize a chave UUID se repetir a mesma tentativa."""
    if min(unidade_id, servico_id, profissional_id) < 1:
        raise ValueError("IDs devem ser positivos")
    try:
        parsed = datetime.fromisoformat(inicio)
    except ValueError as exc:
        raise ValueError("inicio deve ser data e hora local em ISO 8601") from exc
    if parsed.tzinfo is not None:
        raise ValueError("inicio deve ser hora local da filial, sem fuso no valor")
    key = str(UUID(chave_idempotencia)) if chave_idempotencia else str(uuid4())
    result = api().post_authenticated(
        f"/api/unidades/{unidade_id}/agendamentos",
        {"servicoId": servico_id, "profissionalId": profissional_id, "inicio": inicio},
        key,
    )
    return {"agendamento": result, "chaveIdempotencia": key}


if __name__ == "__main__":
    mcp.run(transport="stdio")
