"""Teste das versões 1.1.5 e 1.1.6: o conector conforme o Webservice V2 do Coletum 1.71.0. Sem API real, sem dado real.

Uma API de mentira em 127.0.0.1 faz o papel da 1.71: rota /account (cota, sem gastar cota), separadores na
estrutura, filtro id e ordem. Confere:
  - configurar_token testa pela /account, não gasta cota e devolve o saldo; contar_preenchimentos traz o saldo;
  - separador aparece em estrutura_formulario como título e fica fora do resumo e da planilha; no PDF da
    exportação e no em colunas vira título de seção antes do campo seguinte (fotográfico: fora); ocultar e
    ordem levam a seção junto;
  - ordem=mais_antigos vira order=asc; o padrão não manda order;
  - PDF pelos ids: 1 chamada com id=..., na ordem pedida, sem criado_em; id inválido não chama a API;
    id que não existe dá erro; API que ignora o filtro id (anterior à 1.71) dá erro em vez de PDF errado;
  - 403 explica que o plano não inclui o webservice;
  - PDF padrão com o nome e o logo da conta (da /account); o pedido vale por cima; conta sem logo, o do Coletum.
Uso: uv run --frozen python server/teste_api_171.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pdfplumber

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

RECEBIDAS: list[dict] = []
ESTADO = {"ignora_id": False, "logo": False}  # True = API anterior à 1.71, que não conhece o filtro id

ESTRUTURA = {"id": 1, "name": "Vistoria", "version": "1", "components": [
    {"id": "secao1", "type": "separator", "label": "Seção Identificação", "help_block": "Quem e onde"},
    {"id": "nome2", "type": "text", "label": "Nome", "maximum": 1},
    {"id": "grupo3", "type": "group", "label": "Itens", "maximum": 0, "components": [
        {"id": "secao4", "type": "separator", "label": "Seção Interna"},
        {"id": "obs5", "type": "text", "label": "Obs", "maximum": 1}]}]}


def preenchimento(pid: str, dia: int) -> dict:
    return {"id": pid, "answer": {"nome2": f"Nome {pid}", "grupo3": [{"obs5": "ok"}]},
            "meta_data": {"created_at": f"2026-10-{dia:02d}T10:00:00-0300", "created_by_user_name": "Teste",
                          "created_at_source": "web_private"}}


RESPOSTAS = [preenchimento("10.3", 3), preenchimento("10.2", 2), preenchimento("10.1", 1)]  # mais recente primeiro


class ApiDeMentira(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        RECEBIDAS.append({"caminho": u.path, "query": q, "ua": self.headers.get("User-Agent")})
        if u.path == "/logo.png":  # o logo da conta, link público do bucket
            import io
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (60, 30), (200, 30, 30)).save(buf, format="PNG")
            self.send_response(200)
            self.send_header("Content-Length", str(len(buf.getvalue())))
            self.end_headers()
            self.wfile.write(buf.getvalue())
            return
        codigo, corpo = 200, None
        if self.headers.get("Token") == "sem_plano":
            codigo, corpo = 403, {"code": 403, "type": "access_denied", "message": "Access denied"}
        elif u.path == "/account":
            logo = f"http://127.0.0.1:{self.server.server_port}/logo.png" if ESTADO["logo"] else None
            corpo = {"id": 7810, "name": "Conta Exemplo", "logo": logo,
                     "quota": {"limit": 1000, "used": 12.4, "remaining": 987.6}}
        elif u.path == "/forms/1":
            corpo = ESTRUTURA
        elif u.path == "/forms/1/answers":
            dados = list(RESPOSTAS)
            if q.get("id") and not ESTADO["ignora_id"]:
                ids = q["id"][0].split(",")
                dados = [p for p in dados if p["id"] in ids]
            if q.get("order") == ["asc"]:
                dados.reverse()
            tam = int(q.get("page_size", ["20"])[0])
            corpo = {"data": dados[:tam], "pagination": {"page": 1, "page_size": tam, "total_items": len(dados),
                                                         "total_pages": 1, "has_next": False}}
        else:
            codigo, corpo = 404, {"error": {"message": "Entity not found"}}
        dados_b = json.dumps(corpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados_b)))
        self.end_headers()
        self.wfile.write(dados_b)

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
    pasta = Path(tempfile.mkdtemp(prefix="coletum_teste_171_"))
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(v, None)
    os.environ.update({"COLETUM_TOKEN": "bom", "COLETUM_BASE_URL": f"http://127.0.0.1:{srv.server_port}",
                       "COLETUM_PASTA": str(pasta), "COLETUM_INTERVALO_S": "0", "COLETUM_HOSTS_ANEXOS": "127.0.0.1"})
    import api
    api._ler_env_arquivo = lambda: {}
    import keyring
    from keyring.backend import KeyringBackend

    class Cofre(KeyringBackend):
        priority = 1
        dados: dict = {}

        def get_password(self, s, c):
            return self.dados.get((s, c))

        def set_password(self, s, c, v):
            self.dados[(s, c)] = v

        def delete_password(self, s, c):
            self.dados.pop((s, c), None)

    keyring.set_keyring(Cofre())
    import modelos
    import server

    # 1. token e cota pela /account
    r = server.configurar_token("bom")
    conferir(r["ok"] and RECEBIDAS[-1]["caminho"] == "/account", "configurar_token testa pela /account")
    conferir(r.get("chamadas_api") == 0 and r.get("cota_consumida") == 0, "configurar_token não gasta cota")
    conferir(r.get("cota_do_mes") == {"conta": "Conta Exemplo", "limite": 1000, "usado": 12.4, "restante": 987.6},
             "configurar_token devolve conta e saldo da cota")
    conferir(all("source" not in x["query"] for x in RECEBIDAS), "nenhuma requisição leva source=")
    conferir(RECEBIDAS[-1]["ua"] == f"coletum-mcp/{api.VERSAO}", "User-Agent coletum-mcp/<versão>")
    r = server.contar_preenchimentos(1)
    conferir(r["ok"] and r["total"] == 3 and (r.get("cota_do_mes") or {}).get("restante") == 987.6,
             "contar_preenchimentos traz o saldo da cota")
    conferir(r["cota_consumida"] == 0.2, "a /account não entra na cota_consumida da contagem")

    # 2. separadores
    r = server.estrutura_formulario(1)
    sep = r["campos"][0]
    conferir(sep == {"chave": "secao1", "rotulo": "Seção Identificação", "tipo": "separator", "ajuda": "Quem e onde"},
             "estrutura_formulario mostra o separador só como título")
    conferir(r["campos"][2]["campos"][0]["tipo"] == "separator", "separador dentro de grupo também aparece")
    r = server.buscar_preenchimentos(1)
    texto = json.dumps(r, ensure_ascii=False)
    conferir(r["ok"] and "Seção" not in texto and "Nome 10.3" in texto, "resumo sem coluna de separador")
    r = server.exportar_preenchimentos(1, formato="csv", pasta_saida=str(pasta / "csv"))
    csvs = "".join(f.read_text(encoding="utf-8") for f in (pasta / "csv").rglob("*.csv"))
    conferir("Seção" not in csvs and "Nome 10.1" in csvs, "planilha sem coluna de separador")
    cfg = lambda n, d=None: str(pasta) if n == "COLETUM_PASTA_MODELOS" else d  # noqa: E731
    def texto_pdf(nome, aparencia=None):
        typ, pm, _ = modelos.achar_modelo(nome, cfg)
        res, _ = modelos.gerar(ESTRUTURA, RESPOSTAS[:1], 1, typ.read_text(encoding="utf-8"), pm, nome,
                               None, None, None, None, None, "um_pdf", pasta, aparencia=aparencia)
        with pdfplumber.open(res["arquivos"][0]["caminho"]) as pdf:
            return "".join(pg.extract_text() or "" for pg in pdf.pages), res

    for nome in server.MODELOS_COLETUM:
        txt, _ = texto_pdf(nome)
        if nome == "coletum_fotografico":
            conferir("Seção" not in txt, "PDF coletum_fotografico sem seção (é resumo)")
            continue
        i_sec, i_nome, i_int, i_obs = (txt.find(x) for x in ("Seção Identificação", "Nome 10.3", "Seção Interna", "Obs"))
        conferir(txt.count("Seção Identificação") == 1 and "Quem e onde" in txt and -1 < i_sec < i_nome,
                 f"PDF {nome}: seção com ajuda, uma vez, antes do 1º campo")
        conferir(-1 < i_int < i_obs, f"PDF {nome}: seção dentro do grupo, antes do campo dela")

    # ocultar e ordem levam a seção junto
    import contrato
    def secoes(aparencia):
        mt = contrato.Montador(ESTRUTURA, 1, pasta / "mt", 0)
        dados = {"preenchimentos": [mt.preenchimento(RESPOSTAS[0])]}
        sem = contrato.aplicar_aparencia(dados, aparencia)
        return [(c["rotulo"], [x["rotulo"] for x in c["secoes"]]) for c in dados["preenchimentos"][0]["campos"]], sem
    conferir(secoes(None)[0] == [("Nome", ["Seção Identificação"]), ("Itens", [])], "contrato: seção no campo seguinte")
    conferir(secoes({"campos": {"ocultar": ["Nome"]}})[0] == [("Itens", ["Seção Identificação"])],
             "ocultar o 1º campo passa a seção ao seguinte")
    conferir(secoes({"campos": {"ocultar": ["Seção Identificação"]}}) == ([("Nome", []), ("Itens", [])], []),
             "ocultar pelo nome da seção tira só o título")
    conferir(secoes({"campos": {"ordem": ["Itens"]}})[0] == [("Itens", []), ("Nome", ["Seção Identificação"])],
             "ordem: campo levado ao começo não leva a seção")
    conferir(secoes({"campos": {"ordem": ["Nome"]}})[0] == [("Nome", []), ("Itens", ["Seção Identificação"])],
             "ordem: a seção fica com o campo que ficou no lugar")

    # 3. ordem
    server.buscar_preenchimentos(1, ordem="mais_antigos")
    conferir(RECEBIDAS[-1]["query"].get("order") == ["asc"], "ordem=mais_antigos vira order=asc")
    server.buscar_preenchimentos(1)
    conferir("order" not in RECEBIDAS[-1]["query"], "o padrão não manda order")

    # 4. PDF pelos ids
    escolher = server._escolher_preenchimentos
    antes = len(RECEBIDAS)
    esc, filtros, _ = escolher(1, None, ["10.3", "10.1", "10.3"], None, None, None, None, 20, api.Contador(), [])
    conferir([p["id"] for p in esc] == ["10.3", "10.1"], "ids: na ordem pedida, sem repetir")
    conferir(len(RECEBIDAS) - antes == 1 and RECEBIDAS[-1]["query"].get("id") == ["10.3,10.1"],
             "ids: 1 chamada com id=10.3,10.1")
    esc, _, _ = escolher(1, [{"id": "10.2", "criado_em": "qualquer coisa"}], None, None, None, None, None, 20,
                         api.Contador(), [])
    conferir([p["id"] for p in esc] == ["10.2"], "preenchimentos: só o id vale, criado_em é ignorado")
    for ids, trecho, msg in ((["abc"], "inválido", "id inválido é recusado"),
                             (["10.9"], "Não encontrei", "id que não existe dá erro")):
        antes = len(RECEBIDAS)
        try:
            escolher(1, None, ids, None, None, None, None, 20, api.Contador(), [])
            conferir(False, msg)
        except api.ErroColetum as e:
            conferir(trecho in str(e), msg)
        if ids == ["abc"]:
            conferir(len(RECEBIDAS) == antes, "id inválido não chama a API")
    ESTADO["ignora_id"] = True
    try:
        escolher(1, None, ["10.1"], None, None, None, None, 20, api.Contador(), [])
        conferir(False, "API sem filtro id")
    except api.ErroColetum as e:
        conferir("1.71" in str(e), "API que ignora o filtro id dá erro, não PDF errado")
    ESTADO["ignora_id"] = False

    # 5. nome e logo da conta no PDF padrão
    def pdf_padrao(**k):
        r = server.gerar_pdf_preenchimento(id_formulario=1, ids_preenchimentos=["10.1"], pasta_saida=str(pasta / "pdf"),
                                           **k).structuredContent
        with pdfplumber.open(r["arquivos"][0]["caminho"]) as pdf:
            pg = pdf.pages[0]
            return r, pg.extract_text() or "", [tuple(i["srcsize"]) for i in pg.images]
    ESTADO["logo"] = True
    r, txt, imgs = pdf_padrao()
    conferir(r["ok"] and "Conta Exemplo" in txt and r["cabecalho"] == {"empresa": "Conta Exemplo", "logo": "o da conta"},
             "PDF padrão: nome da conta no cabeçalho, sem pedir")
    conferir((60, 30) in imgs, "PDF padrão: logo da conta no topo")
    cota_com_conta = r["cota_consumida"]
    r, txt, _ = pdf_padrao(ajustes={"empresa": {"nome": "Outra Empresa"}})
    conferir("Outra Empresa" in txt and "Conta Exemplo" not in txt, "empresa.nome pedido vale por cima")
    r, txt, _ = pdf_padrao(ajustes={"empresa": {"nome": "", "logo": ""}})
    conferir(r["cota_consumida"] == cota_com_conta, "nome e logo da conta não gastam cota")
    conferir("Conta Exemplo" not in txt and r["cabecalho"]["empresa"] is None, 'empresa.nome "" tira a linha')
    ESTADO["logo"] = False
    r, _, imgs = pdf_padrao()
    conferir(r["cabecalho"]["logo"] == "o do Coletum" and (60, 30) not in imgs, "conta sem logo: o do Coletum")

    # 6. 403 de plano sem webservice
    r = server.configurar_token("sem_plano")
    conferir(not r["ok"] and "plano" in r["erro"], "403 explica o plano sem webservice")

    print("ok" if not erros else "FALHOU")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
