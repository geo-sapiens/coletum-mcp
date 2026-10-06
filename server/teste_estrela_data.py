"""Teste de estrela e data no PDF: sem API e sem rede.

Gera os três modelos do Coletum com um formulário mínimo (campo estrela e campo data no 1º nível) e confere no
PDF o que a exportação do Coletum mostra: 5 estrelas, as da nota em #F5B600 e o resto em #BEBEBE (não o número),
e a data em dd/mm/aaaa (não a data crua da V2, que vem com hora e fuso).
Uso: uv run python server/teste_estrela_data.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import pdfplumber  # noqa: E402

import modelos  # noqa: E402
from baixar import fmt_valor  # noqa: E402

AMARELO, CINZA = (0.9607843, 0.7137255, 0.0), (0.745098, 0.745098, 0.745098)
ESTRUTURA = {"id": 1, "name": "Teste", "version": "1", "components": [
    {"id": "nota1", "type": "rating", "label": "Nota", "maximum": 1},
    {"id": "dia2", "type": "date", "label": "Dia", "maximum": 1}]}
PREENCHIMENTO = {"id": "1.1", "answer": {"nota1": 4, "dia2": "2026-09-23T00:00:00-03:00"},
                 "meta_data": {"created_at": "2026-09-17T14:01:51-0300", "created_by_user_name": "Teste",
                               "created_at_source": "web_private"}}


def perto(a, b) -> bool:
    return len(a) == 3 and all(abs(x - y) < 0.002 for x, y in zip(a, b))


def main() -> int:
    falhas = []
    # as duas grafias do fuso (a V2 serializa a data do campo com dois-pontos; a fixture interna, sem)
    for cru in ("2026-09-23T00:00:00-03:00", "2026-09-23T00:00:00-0300", "2026-09-23"):
        if fmt_valor(cru, "date") != "23/09/2026":
            falhas.append(f"fmt_valor({cru!r}, 'date') = {fmt_valor(cru, 'date')!r}")
    pasta = Path(tempfile.mkdtemp(prefix="coletum_teste_estrela_"))
    cfg = lambda n, d=None: str(pasta) if n == "COLETUM_PASTA_MODELOS" else d  # noqa: E731
    for nome in ("coletum_exportacao", "coletum_colunas", "coletum_fotografico"):
        typ, pm, _ = modelos.achar_modelo(nome, cfg)
        res, _ = modelos.gerar(ESTRUTURA, [PREENCHIMENTO], 1, typ.read_text(encoding="utf-8"), pm, nome,
                               None, None, None, None, None, "um_pdf", pasta)
        with pdfplumber.open(res["arquivos"][0]["caminho"]) as pdf:
            chars = [c for pg in pdf.pages for c in pg.chars]
        texto = "".join(c["text"] for c in chars)
        estrelas = [c["non_stroking_color"] for c in chars if c["text"] == "★"]
        cheias = sum(perto(c, AMARELO) for c in estrelas)
        vazias = sum(perto(c, CINZA) for c in estrelas)
        print(f"{nome:20s} estrelas={len(estrelas)} (amarelas {cheias}, cinzas {vazias}) "
              f"data={'23/09/2026' in texto} crua={'2026-09-23' in texto}")
        if (len(estrelas), cheias, vazias) != (5, 4, 1):
            falhas.append(f"{nome}: estrelas {len(estrelas)}, amarelas {cheias}, cinzas {vazias} (esperado 5, 4, 1)")
        if "23/09/2026" not in texto or "2026-09-23" in texto:
            falhas.append(f"{nome}: data fora do dd/mm/aaaa")
    for f in falhas:
        print("ERRO:", f)
    print("ok" if not falhas else "FALHOU")
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
