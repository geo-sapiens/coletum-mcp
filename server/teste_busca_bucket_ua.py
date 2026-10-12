"""Teste da versão 1.1.4: busca aproximada de formulário, trava do bucket de produção e User-Agent.

Sem API real e sem rede externa: sobe um servidor HTTP local que finge a API (formulários inventados) e
serve uma foto de mentira. Confere:
  - listar_formularios com nome acha ignorando acento, maiúsculas, pontuação e ordem, em 1 chamada sem o
    filtro name; a paginação devolvida bate com o que foi filtrado;
  - conta com mais de 500 formulários cai no filtro name do servidor;
  - toda requisição leva User-Agent coletum-mcp/<versão do pyproject>;
  - fora da produção, sem COLETUM_HOSTS_ANEXOS, nada vai ao bucket de produção (e a foto barrada vira
    simulada só com COLETUM_FOTOS_TESTE); com COLETUM_HOSTS_ANEXOS explícito, baixa.
Uso: uv run python server/teste_busca_bucket_ua.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

RECEBIDAS: list[dict] = []
MUITOS = {"ligado": False}   # finge conta com mais de 500 formulários (total_pages 2)
NOMES = ["FWD - Parte II", "Inspeção Ambiental (2026)", "FWD Parte I", "Cadastro de Ocupação"]


class ApiDeMentira(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        RECEBIDAS.append({"caminho": u.path, "query": q, "ua": self.headers.get("User-Agent")})
        if u.path == "/foto.jpg":
            dados, tipo = b"\xff\xd8foto-de-mentira", "image/jpeg"
        else:
            nomes = NOMES
            if "name" in q:
                nomes = [n for n in NOMES if q["name"][0].lower() in n.lower()]
            corpo = {"data": [{"id": i + 1, "name": n, "status": "enabled", "category": "Teste", "version": 1}
                              for i, n in enumerate(nomes)],
                     "pagination": {"page": 1, "total_items": len(nomes), "has_next": MUITOS["ligado"],
                                    "total_pages": 2 if MUITOS["ligado"] else 1}}
            dados, tipo = json.dumps(corpo).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args) -> None:
        pass


def main() -> int:
    erros: list[str] = []

    def conferir(ok: bool, msg: str) -> None:
        print(("ok    " if ok else "ERRO  ") + msg)
        if not ok:
            erros.append(msg)

    srv = HTTPServer(("127.0.0.1", 0), ApiDeMentira)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = f"http://127.0.0.1:{srv.server_port}"

    with tempfile.TemporaryDirectory() as t:
        for v in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                  "COLETUM_PASTA_SAIDA", "COLETUM_PASTA_MODELOS", "COLETUM_HOSTS_ANEXOS", "COLETUM_FOTOS_TESTE"):
            os.environ.pop(v, None)
        os.environ.update({"COLETUM_TOKEN": "token-de-teste", "COLETUM_BASE_URL": local,
                           "COLETUM_PASTA": str(Path(t) / "coletum"), "COLETUM_INTERVALO_S": "0",
                           "COLETUM_MAX_CHAMADAS_HORA": "1000"})
        import api
        api._ler_env_arquivo = lambda: {}   # nenhum .env de quem roda o teste interfere
        import server
        from baixar import Baixador

        # 1. busca aproximada
        for busca in ("fwd parte ii", "Parte II FWD", "FWD-PARTE   ii"):
            antes = len(RECEBIDAS)
            r = server.listar_formularios(nome=busca)
            q = RECEBIDAS[-1]["query"]
            conferir(r.get("ok") and [f["nome"] for f in r["formularios"]] == ["FWD - Parte II"]
                     and r["chamadas_api"] == 1 and len(RECEBIDAS) == antes + 1
                     and "name" not in q and q.get("page_size") == ["500"],
                     f"'{busca}' acha só 'FWD - Parte II' em 1 chamada, sem filtro name e com page_size 500")
        r = server.listar_formularios(nome="inspecao AMBIENTAL 2026")
        conferir([f["nome"] for f in r["formularios"]] == ["Inspeção Ambiental (2026)"], "ignora acento e parênteses")
        r = server.listar_formularios(nome="fwd parte", tamanho_pagina=1)
        conferir(r["total"] == 2 and r["total_paginas"] == 2 and r["tem_proxima"] is True and len(r["formularios"]) == 1
                 and r["pagina"] == 1, "paginação local: 2 achados em páginas de 1, tem próxima")
        r2 = server.listar_formularios(nome="fwd parte", pagina=2, tamanho_pagina=1)
        conferir(r2["tem_proxima"] is False and r2["formularios"] != r["formularios"], "página 2 é a última e traz o outro")
        r = server.listar_formularios(nome="nao existe")
        conferir(r["total"] == 0 and r["formularios"] == [] and r["tem_proxima"] is False, "sem achado: total 0")

        # 2. mais de 500 formulários: filtro name do servidor
        MUITOS["ligado"] = True
        antes = len(RECEBIDAS)
        r = server.listar_formularios(nome="Ocupação")
        conferir(r.get("ok") and len(RECEBIDAS) == antes + 2 and RECEBIDAS[-1]["query"].get("name") == ["Ocupação"]
                 and r["chamadas_api"] == 2, "conta com mais de 500: 2ª chamada com o filtro name do servidor")
        MUITOS["ligado"] = False

        # 3. User-Agent em toda requisição
        versao = tomllib.loads((AQUI.parent / "pyproject.toml").read_text())["project"]["version"]
        uas = {x["ua"] for x in RECEBIDAS if x["caminho"] == "/forms"}
        conferir(uas == {f"coletum-mcp/{versao}"}, f"toda requisição leva User-Agent coletum-mcp/{versao} (veio {uas})")
        conferir("source" in RECEBIDAS[-1]["query"], "source=mcp continua na query")

        # 4. trava do bucket de produção
        foto_prod = "https://storage.googleapis.com/bucket-de-producao/conta/foto.jpg"
        bx = Baixador(True)
        dados, motivo = bx.baixar(foto_prod)
        conferir(bx.hosts == set() and dados is None and motivo == Baixador.TRAVA_TESTE and bx.tentativas == 0,
                 "base local, sem COLETUM_HOSTS_ANEXOS: bucket de produção bloqueado, nenhuma tentativa")
        dados, motivo = bx.baixar("https://outro-host.invalid/foto.jpg")
        conferir(motivo == "endereço fora dos hosts permitidos", "outro host segue com o motivo de antes")

        os.environ["COLETUM_FOTOS_TESTE"] = "1"
        bx = Baixador(True)
        dados, motivo = bx.baixar(foto_prod)
        conferir(dados is not None and bx.simulada(foto_prod) and bx.tentativas == 0
                 and bx.motivos_simuladas == {Baixador.TRAVA_TESTE: 1},
                 "com COLETUM_FOTOS_TESTE: a foto barrada pela trava vira simulada, sem download")
        dados, motivo = bx.baixar("https://outro-host.invalid/foto.jpg")
        conferir(dados is None and motivo == "endereço fora dos hosts permitidos", "fora dos hosts continua sem simular")
        dados, motivo = Baixador(False).baixar(foto_prod)
        conferir(dados is None and motivo == "download desligado na configuração", "download desligado continua sem simular")
        os.environ.pop("COLETUM_FOTOS_TESTE")

        os.environ["COLETUM_HOSTS_ANEXOS"] = "127.0.0.1"
        bx = Baixador(True)
        dados, motivo = bx.baixar(f"{local}/foto.jpg")
        conferir(dados == b"\xff\xd8foto-de-mentira" and motivo is None, "COLETUM_HOSTS_ANEXOS explícito abre, mesmo em teste")
        os.environ.pop("COLETUM_HOSTS_ANEXOS")

        os.environ.pop("COLETUM_BASE_URL")
        conferir(api.em_producao() and Baixador(True).hosts == {"storage.googleapis.com"},
                 "na produção (sem COLETUM_BASE_URL) o bucket segue permitido")

    srv.shutdown()
    for e in erros:
        print("ERRO:", e)
    print("ok" if not erros else "FALHOU")
    return 0 if not erros else 1


if __name__ == "__main__":
    sys.exit(main())
