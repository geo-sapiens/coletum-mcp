"""Teste do cache de fotos em disco e da limpeza da pasta de trabalho: sem API e sem rede externa.

Sobe um servidor HTTP local que serve uma foto (e 404 para outra) e finge a escolha dos preenchimentos e a
estrutura do formulário (as funções do server.py são trocadas no teste). Confere:
  - a foto baixada vai para <COLETUM_PASTA>/fotos e o Baixador seguinte (outra conversa) lê dali, sem baixar;
  - usar renova a data do arquivo; o que passa de 30 dias sem uso sai ao começar a geração seguinte;
  - foto simulada (COLETUM_FOTOS_TESTE), barrada pela trava do bucket ou com erro no download não entra no cache;
  - gerar_pdf_preenchimento apaga a pasta trabalho_* quando o PDF sai e a mantém no erro, com o caminho na resposta;
  - gerar_pdf_modelo mantém a pasta, só a mais recente de cada modelo (a de outro modelo fica).
Uso: uv run python server/teste_cache_trabalho.py
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

PEDIDOS: list[str] = []


def jpeg() -> bytes:
    from PIL import Image
    saida = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(saida, format="JPEG")
    return saida.getvalue()


FOTO = jpeg()


class Bucket(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        PEDIDOS.append(self.path)
        if self.path.startswith("/foto"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(FOTO)))
            self.end_headers()
            self.wfile.write(FOTO)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args) -> None:
        pass


def main() -> int:
    erros: list[str] = []

    def conferir(ok: bool, msg: str) -> None:
        print(("ok    " if ok else "ERRO  ") + msg)
        if not ok:
            erros.append(msg)

    srv = HTTPServer(("127.0.0.1", 0), Bucket)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local = f"http://127.0.0.1:{srv.server_port}"

    with tempfile.TemporaryDirectory() as t:
        for v in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                  "COLETUM_PASTA_SAIDA", "COLETUM_PASTA_MODELOS", "COLETUM_FOTOS_TESTE"):
            os.environ.pop(v, None)
        raiz = Path(t) / "coletum"
        os.environ.update({"COLETUM_TOKEN": "token-de-teste", "COLETUM_BASE_URL": local, "COLETUM_PASTA": str(raiz),
                           "COLETUM_HOSTS_ANEXOS": "127.0.0.1", "COLETUM_INTERVALO_S": "0"})
        import api
        api._ler_env_arquivo = lambda: {}   # nenhum .env de quem roda o teste interfere
        import modelos
        import server
        from baixar import Baixador

        cache = raiz / "fotos"

        def no_cache(link: str) -> Path:
            return cache / hashlib.sha256(link.encode("utf-8")).hexdigest()

        # 1. cache em disco entre conversas
        link = f"{local}/foto1.jpg"
        bx = Baixador(True)
        dados, _ = bx.baixar(link)
        conferir(dados == FOTO and bx.baixadas == 1 and no_cache(link).read_bytes() == FOTO,
                 "1ª vez: baixa e grava em <COLETUM_PASTA>/fotos")
        bx.fechar()
        velho = time.time() - 10 * 86400
        os.utime(no_cache(link), (velho, velho))
        antes = len(PEDIDOS)
        bx = Baixador(True)
        dados, _ = bx.baixar(link)
        conferir(dados == FOTO and len(PEDIDOS) == antes and bx.tentativas == 0 and bx.do_cache == 1,
                 "outra conversa (Baixador novo): lê do cache, sem baixar")
        conferir(time.time() - no_cache(link).stat().st_mtime < 60, "usar renova a data do arquivo")
        bx.fechar()

        # 2. mais de 30 dias sem uso sai
        for nome, dias in (("velha", 31), ("recente", 29)):
            f = cache / nome
            f.write_bytes(b"x")
            os.utime(f, (time.time() - dias * 86400,) * 2)
        Baixador(True).fechar()
        conferir(not (cache / "velha").exists() and (cache / "recente").exists() and no_cache(link).exists(),
                 "ao começar: sai a de 31 dias, ficam a de 29 e a em uso")

        # 3. o que não entra no cache
        bx = Baixador(True)
        dados, motivo = bx.baixar(f"{local}/nao_existe.jpg")
        conferir(dados is None and motivo == "o link respondeu 404" and not no_cache(f"{local}/nao_existe.jpg").exists(),
                 "download com erro não entra")
        bx.fechar()
        os.environ["COLETUM_FOTOS_TESTE"] = "1"
        bx = Baixador(True)
        dados, _ = bx.baixar(f"{local}/nao_existe.jpg")
        conferir(dados is not None and bx.simulada(f"{local}/nao_existe.jpg")
                 and not no_cache(f"{local}/nao_existe.jpg").exists(), "foto simulada (download falhou) não entra")
        bx.fechar()
        os.environ.pop("COLETUM_HOSTS_ANEXOS")   # teste sem hosts: trava do bucket de produção
        prod = "https://storage.googleapis.com/bucket-de-producao/conta/foto.jpg"
        bx = Baixador(True)
        dados, _ = bx.baixar(prod)
        conferir(dados is not None and bx.simulada(prod) and not no_cache(prod).exists(),
                 "foto barrada pela trava (vira simulada) não entra")
        dados, motivo = bx.baixar(link)
        conferir(dados is None and motivo == "endereço fora dos hosts permitidos" and bx.do_cache == 0,
                 "link no cache, mas fora dos hosts permitidos: não sai do cache")
        bx.fechar()
        os.environ.pop("COLETUM_FOTOS_TESTE")
        os.environ["COLETUM_HOSTS_ANEXOS"] = "127.0.0.1"

        # 4. pastas de trabalho, pelas ferramentas
        estr = {"id": 1, "name": "Teste", "version": "1", "components": [
            {"id": "foto1", "type": "photo", "label": "Foto", "maximum": 1}]}
        prenc = {"id": "1.1", "answer": {"foto1": f"{local}/foto1.jpg"},
                 "meta_data": {"created_at": "2026-09-17T14:01:51-0300", "created_by_user_name": "Teste",
                               "created_at_source": "web_private"}}
        server._escolher_preenchimentos = lambda *a, **k: ([prenc], {"ids": ["1.1"]}, None)
        server.estrutura = lambda fid, cont, forcar=False: estr
        saida = Path(t) / "saida"

        def trabalhos(prefixo: str = "trabalho_") -> list[Path]:
            return sorted(p for p in saida.glob(prefixo + "*") if p.is_dir())

        antes = len(PEDIDOS)
        r = server.gerar_pdf_preenchimento(id_formulario=1, ids_preenchimentos=["1.1"], pasta_saida=str(saida))
        s = r.structuredContent
        conferir(s.get("ok") and Path(s["arquivos"][0]["caminho"]).is_file() and not trabalhos()
                 and "pasta_do_trabalho" not in s, "gerar_pdf_preenchimento: PDF pronto, pasta trabalho_* apagada")
        conferir(len(PEDIDOS) == antes and s["download_de_fotos"]["do_cache"] == 1 and s["download_de_fotos"]["baixadas"] == 0,
                 "a foto do PDF veio do cache, sem baixar")

        compilar = modelos.compilar

        def falha(*a, **k):
            raise modelos.ErroModelo("O Typst não compilou o template (falha forçada no teste).")

        modelos.compilar = falha
        r = server.gerar_pdf_preenchimento(id_formulario=1, ids_preenchimentos=["1.1"], pasta_saida=str(saida))
        s = r.structuredContent
        pasta = s.get("pasta_do_trabalho")
        conferir(not s.get("ok") and pasta and Path(pasta).is_dir() and (Path(pasta) / "dados.json").is_file()
                 and pasta in s["erro"] and trabalhos() == [Path(pasta)],
                 "com erro: a pasta fica e a resposta diz onde")
        modelos.compilar = compilar
        for p in trabalhos():
            shutil.rmtree(p)

        typ = '#import "/coletum.typ": *\n= Rascunho #dados.preenchimentos.len()\n'
        outro = saida / "trabalho_rascunho2_1_20260101_000000"
        outro.mkdir(parents=True)
        r1 = server.gerar_pdf_modelo(id_formulario=1, template_typst=typ, ids_preenchimentos=["1.1"],
                                     pasta_saida=str(saida)).structuredContent
        time.sleep(1.1)  # carimbo de segundo diferente
        r2 = server.gerar_pdf_modelo(id_formulario=1, template_typst=typ, ids_preenchimentos=["1.1"],
                                     pasta_saida=str(saida)).structuredContent
        conferir(r1.get("ok") and r2.get("ok") and r1["pasta_do_trabalho"] != r2["pasta_do_trabalho"]
                 and trabalhos("trabalho_rascunho_") == [Path(r2["pasta_do_trabalho"])],
                 "gerar_pdf_modelo: mantém a pasta, só a mais recente do modelo")
        conferir(outro.is_dir(), "a pasta de outro modelo (prefixo parecido) fica")

    srv.shutdown()
    for e in erros:
        print("ERRO:", e)
    print("ok" if not erros else "FALHOU")
    return 0 if not erros else 1


if __name__ == "__main__":
    sys.exit(main())
