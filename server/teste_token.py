"""Teste do token pela conversa (configurar_token): sem API real, sem dado real.

Uma API de mentira em 127.0.0.1 aceita só o token "bom". Um cofre de mentira, em memória, faz o papel do Keychain.
Confere: sem token, a ferramenta pede o token; token ruim não é guardado; token bom é guardado e passa a valer;
o token nunca volta na resposta.
Uso: uv run --frozen python server/teste_token.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import keyring
from keyring.backend import KeyringBackend

AQUI = Path(__file__).resolve().parent


class CofreDeMentira(KeyringBackend):
    priority = 1
    dados: dict = {}

    def get_password(self, servico, conta):
        return self.dados.get((servico, conta))

    def set_password(self, servico, conta, senha):
        self.dados[(servico, conta)] = senha

    def delete_password(self, servico, conta):
        self.dados.pop((servico, conta), None)


class ApiDeMentira(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Token") != "bom":
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"error": {"message": "invalid token"}}')
            return
        corpo = json.dumps({"data": [{"id": 1, "name": "Formulário Exemplo", "status": "enabled"}],
                            "pagination": {"page": 1, "total_items": 1, "total_pages": 1, "has_next": False}})
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(corpo.encode())

    def log_message(self, *args) -> None:
        pass


def main() -> int:
    http = HTTPServer(("127.0.0.1", 0), ApiDeMentira)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    pasta = tempfile.mkdtemp(prefix="coletum_teste_token_")
    os.environ.update({"COLETUM_BASE_URL": f"http://127.0.0.1:{http.server_port}", "COLETUM_PASTA": pasta,
                       "COLETUM_INTERVALO_S": "0", "COLETUM_TOKEN": "${user_config.token}"})
    keyring.set_keyring(CofreDeMentira())
    sys.path.insert(0, str(AQUI))
    import server  # noqa: E402

    falhas = []

    def conferir(ok, msg):
        print(("ok    " if ok else "FALHA ") + msg)
        if not ok:
            falhas.append(msg)

    r = server.listar_formularios()
    conferir(not r["ok"] and "configurar_token" in r["erro"], "sem token, a ferramenta pede o token e aponta configurar_token")
    r = server.configurar_token("ruim")
    conferir(not r["ok"] and not CofreDeMentira.dados, "token ruim não é guardado")
    r = server.configurar_token("  bom  ")
    conferir(r["ok"] and CofreDeMentira.dados.get(("coletum-mcp", "token")) == "bom", "token bom é guardado no cofre")
    conferir("bom" not in json.dumps(r, ensure_ascii=False).replace("Pode seguir", ""), "o token não volta na resposta")
    server._api = None  # simula uma conversa nova: o token sai do cofre
    r = server.listar_formularios()
    conferir(r["ok"] and r["total"] == 1, "conversa nova lê o token do cofre")
    print("ok" if not falhas else "FALHOU")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
