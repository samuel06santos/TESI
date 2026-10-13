import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from fastmcp import Client


MODULE_PATH = Path(__file__).resolve().parents[1] / "server.py"
spec = importlib.util.spec_from_file_location("estilo_marcado_mcp", MODULE_PATH)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class APITests(unittest.TestCase):
    def test_mcp_exposes_four_tools_with_write_approval_metadata(self):
        async def inspect_tools():
            async with Client(server.mcp) as client:
                return {tool.name: tool for tool in await client.list_tools()}

        tools = asyncio.run(inspect_tools())
        self.assertEqual(set(tools), {"listar_filiais", "listar_servicos", "consultar_horarios", "criar_agendamento"})
        for name in ("listar_filiais", "listar_servicos", "consultar_horarios"):
            self.assertTrue(tools[name].annotations.read_only_hint)
            self.assertTrue(tools[name].description)
        self.assertFalse(tools["criar_agendamento"].annotations.read_only_hint)
        self.assertTrue(tools["criar_agendamento"].meta["anthropic/requiresUserInteraction"])

    def test_public_read_routes_and_query(self):
        seen = []

        def respond(request):
            seen.append((request.method, request.url.path, dict(request.url.params)))
            return httpx.Response(200, json={"ok": True})

        api = server.EstiloMarcadoAPI(transport=httpx.MockTransport(respond))
        with patch.object(server, "api", return_value=api):
            self.assertEqual(server.listar_filiais("Centro")["ok"], True)
            server.listar_servicos(7)
            server.consultar_horarios(7, 9, "2026-10-13", 3)
        self.assertEqual(seen[0], ("GET", "/api/filiais/publicas", {"busca": "Centro", "pagina": "1", "tamanho": "12"}))
        self.assertEqual(seen[1][1], "/api/unidades/7/servicos")
        self.assertEqual(seen[2], ("GET", "/api/unidades/7/servicos/9/horarios", {"data": "2026-10-13", "profissionalId": "3"}))

    def test_write_sends_session_csrf_and_idempotency_key(self):
        seen = []

        def respond(request):
            seen.append(request)
            if request.url.path.endswith("/csrf"):
                return httpx.Response(200, json={"headerName": "X-XSRF-TOKEN", "token": "csrf-test"})
            return httpx.Response(201, json={"id": 42, "status": "AGENDADO"})

        api = server.EstiloMarcadoAPI(session_cookie="sessao-teste", transport=httpx.MockTransport(respond))
        key = "123e4567-e89b-12d3-a456-426614174000"
        with patch.object(server, "api", return_value=api):
            result = server.criar_agendamento(7, 9, 3, "2026-10-13T14:00:00", key)
        self.assertEqual(result["agendamento"]["id"], 42)
        self.assertEqual(result["chaveIdempotencia"], key)
        self.assertEqual([r.method for r in seen], ["GET", "POST"])
        self.assertEqual(seen[1].url.path, "/api/unidades/7/agendamentos")
        self.assertIn("SESSION=sessao-teste", seen[1].headers["cookie"])
        self.assertEqual(seen[1].headers["X-XSRF-TOKEN"], "csrf-test")
        self.assertEqual(seen[1].headers["Idempotency-Key"], key)
        self.assertEqual(__import__("json").loads(seen[1].content), {"servicoId": 9, "profissionalId": 3, "inicio": "2026-10-13T14:00:00"})

    def test_write_needs_session(self):
        api = server.EstiloMarcadoAPI(session_cookie="")
        with patch.object(server, "api", return_value=api):
            with self.assertRaisesRegex(ValueError, "ESTILO_MARCADO_SESSION"):
                server.criar_agendamento(1, 2, 3, "2026-10-13T14:00:00")

    def test_http_error_keeps_public_message(self):
        def respond(request):
            return httpx.Response(409, json={"mensagem": "horário indisponível"})

        api = server.EstiloMarcadoAPI(transport=httpx.MockTransport(respond))
        with self.assertRaisesRegex(ValueError, "HTTP 409 — horário indisponível"):
            api.get("/api/filiais/publicas")


if __name__ == "__main__":
    unittest.main()
