"""Teste dos limites de uso da API: sem rede externa e sem dado real.

Sobe um servidor HTTP local que finge a API (lista de formulários inventada) e confere:
  - source=mcp chega na query de toda requisição;
  - o intervalo mínimo entre requisições é respeitado;
  - chamadas_api e cota_consumida (cada chamada pesa 0,2; erro não conta);
  - o teto por hora recusa ANTES de chamar, vale entre sessões (arquivo .uso_api.json) e poda o que passou de 1 h;
  - sem arquivo gravável, segue só com a contagem em memória.
Uso: uv run python server/teste_limites.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

RECEBIDAS: list[dict] = []   # o que a API de mentira recebeu: caminho, query e instante


class ApiDeMentira(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        RECEBIDAS.append({"caminho": u.path, "query": parse_qs(u.query), "t": time.monotonic()})
        if u.path == "/forms":
            corpo = {"data": [{"id": 1, "name": "Formulário de exemplo", "status": "enabled", "category": "Teste",
                               "version": 1}],
                     "pagination": {"page": 1, "page_size": 100, "total_items": 1, "total_pages": 1,
                                    "has_next": False}}
            codigo = 200
        else:
            corpo, codigo = {"error": {"message": "não existe"}}, 404
        dados = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args) -> None:  # silêncio
        pass


def main() -> int:
    erros: list[str] = []

    def conferir(ok: bool, msg: str) -> None:
        print(("ok    " if ok else "ERRO  ") + msg)
        if not ok:
            erros.append(msg)

    srv = HTTPServer(("127.0.0.1", 0), ApiDeMentira)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as t:
        raiz = Path(t) / "coletum"
        for v in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(v, None)
        os.environ.update({
            "COLETUM_TOKEN": "token-de-teste", "COLETUM_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
            "COLETUM_PASTA": str(raiz), "COLETUM_INTERVALO_S": "0.15", "COLETUM_MAX_CHAMADAS_HORA": "4"})
        for v in ("COLETUM_PASTA_SAIDA", "COLETUM_PASTA_MODELOS"):
            os.environ.pop(v, None)
        import api
        api._ler_env_arquivo = lambda: {}   # nenhum .env de quem roda o teste interfere
        import server

        arquivo = raiz / ".uso_api.json"

        def novo_processo() -> None:
            """Outra sessão: memória vazia, arquivo igual."""
            api._limites = api._Limites()

        # 1. source=mcp e chamadas_api / cota_consumida
        novo_processo()
        r = server.listar_formularios()
        conferir(r.get("ok") is True and r["total"] == 1, "listar_formularios responde pela API de mentira")
        conferir(RECEBIDAS[-1]["query"].get("source") == ["mcp"], "source=mcp vai na query")
        conferir(r.get("chamadas_api") == 1 and r.get("cota_consumida") == 0.2,
                 f"1 chamada = chamadas_api 1 e cota_consumida 0,2 (veio {r.get('chamadas_api')} e {r.get('cota_consumida')})")
        conferir("acessos_gastos" not in r, "acessos_gastos não existe mais")
        conferir(api.Contador(chamadas=5).cota == 1.0 and api.cota_de(3) == 0.6 and api.PESO_COTA_V2 == 0.2,
                 "5 chamadas = 1,0 de cota; 3 chamadas = 0,6")

        # erro da API não conta
        e = server.estrutura_formulario(999)
        conferir(e.get("ok") is False and e["chamadas_api"] == 0 and e["cota_consumida"] == 0.0
                 and e["requisicoes_feitas"] == 1, "erro da API: requisição feita, 0 chamadas e 0 de cota")
        conferir(RECEBIDAS[-1]["query"].get("source") == ["mcp"], "source=mcp também na requisição que deu erro")

        # 2. intervalo mínimo (as 2 chamadas acima já foram em sequência; mais 2 só para medir)
        server.listar_formularios()
        server.listar_formularios()
        ts = [x["t"] for x in RECEBIDAS]
        folgas = [b - a for a, b in zip(ts, ts[1:])]
        conferir(all(f >= 0.14 for f in folgas),
                 f"intervalo mínimo de 0,15 s entre requisições (menor folga: {min(folgas):.3f} s)")

        # 3. teto por hora: 4 chamadas já feitas desde o arquivo novo? conta o que o arquivo guardou
        gravado = json.loads(arquivo.read_text(encoding="utf-8"))["chamadas"]
        conferir(len(gravado) == 4, f"{arquivo.name} guarda os horários das chamadas feitas ({len(gravado)})")
        antes = len(RECEBIDAS)
        r = server.listar_formularios()
        conferir(r.get("ok") is False and "Limite de segurança" in r["erro"] and "4 chamadas" in r["erro"],
                 "a 5ª chamada na hora é recusada, com mensagem clara")
        conferir(len(RECEBIDAS) == antes and r["requisicoes_feitas"] == 0 and r["chamadas_api"] == 0,
                 "a recusa vem ANTES de chamar a API")
        conferir("libera" in r["erro"].lower() and "min" in r["erro"], "a mensagem diz quando libera")

        # 4. vale entre sessões (processo novo lê o arquivo)
        novo_processo()
        r = server.listar_formularios()
        conferir(r.get("ok") is False and "Limite de segurança" in r["erro"], "outra sessão também é recusada (arquivo)")

        # 5. janela móvel: o que passou de 1 h sai da conta
        agora = time.time()
        arquivo.write_text(json.dumps({"chamadas": [agora - 3700] * 4}), encoding="utf-8")
        novo_processo()
        r = server.listar_formularios()
        conferir(r.get("ok") is True, "chamadas de mais de 1 h atrás não contam")
        conferir(len(json.loads(arquivo.read_text(encoding="utf-8"))["chamadas"]) == 1, "o arquivo poda o que passou de 1 h")

        # 6. arquivo ilegível ou ausente: segue com a contagem em memória
        arquivo.write_text("isto não é json", encoding="utf-8")
        novo_processo()
        r = server.listar_formularios()
        conferir(r.get("ok") is True, "arquivo corrompido não quebra (é refeito)")

        # 7. pasta impossível de gravar: só memória, e o teto ainda vale
        bloqueio = Path(t) / "arquivo_comum"
        bloqueio.write_text("x", encoding="utf-8")
        os.environ["COLETUM_PASTA"] = str(bloqueio / "sub")
        novo_processo()
        seguidas = [server.listar_formularios() for _ in range(5)]
        conferir([x.get("ok") for x in seguidas] == [True, True, True, True, False],
                 "sem arquivo gravável: 4 chamadas passam e a 5ª é recusada pela contagem em memória")

    srv.shutdown()
    for e in erros:
        print("ERRO:", e)
    print("ok" if not erros else "FALHOU")
    return 0 if not erros else 1


if __name__ == "__main__":
    sys.exit(main())
