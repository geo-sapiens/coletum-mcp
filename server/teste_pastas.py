"""Teste das pastas padrão (Documentos/Coletum e COLETUM_PASTA): sem API.

Confere a regra de pasta_padrao numa casa inventada (Documents, Documentos, OneDrive, nenhuma), a raiz única
COLETUM_PASTA (saídas em <pasta>/saidas, modelos em <pasta>/modelos) e que COLETUM_PASTA_SAIDA e
COLETUM_PASTA_MODELOS continuam valendo por cima dela.
Uso: uv run python server/teste_pastas.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import api  # noqa: E402
from api import pasta_padrao  # noqa: E402

VARS = ("COLETUM_PASTA", "COLETUM_PASTA_SAIDA", "COLETUM_PASTA_MODELOS")

# Lê o que o servidor resolveu ao subir, num processo novo (as pastas padrão são fixadas no import).
SONDA = """
import json, sys
sys.path.insert(0, %r)
import server, modelos
from api import config
print(json.dumps({"saida": str(server.resolver_pasta(None)), "modelos": str(modelos.pasta_modelos(config))}))
""" % str(AQUI)


def sonda(env_extra: dict, casa: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in VARS and k != "COLETUM_TOKEN"}
    env.update({"HOME": str(casa), "USERPROFILE": str(casa), **env_extra})
    r = subprocess.run([sys.executable, "-c", SONDA], env=env, capture_output=True, text=True, cwd=str(casa), timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def main() -> int:
    erros = []
    # nenhum .env nem variável do ambiente de quem roda o teste pode interferir
    api._ler_env_arquivo = lambda: {}
    antigo = {v: os.environ.pop(v, None) for v in VARS}
    try:
        casos = [("Documents", "Documents"), ("Documentos", "Documentos"), ("OneDrive/Documents", "OneDrive/Documents"), (None, "")]
        for criar, esperado in casos:
            with tempfile.TemporaryDirectory() as t:
                casa = Path(t)
                if criar:
                    (casa / criar).mkdir(parents=True)
                obtido = pasta_padrao("saidas", casa)
                alvo = (casa / esperado / "Coletum" / "saidas") if esperado else (casa / "Coletum" / "saidas")
                print(f"{str(criar):20s} -> {obtido.relative_to(casa)}")
                if obtido != alvo:
                    erros.append(f"{criar}: esperado {alvo}, obtido {obtido}")

        # COLETUM_PASTA: raiz única
        with tempfile.TemporaryDirectory() as t:
            raiz = Path(t) / "meus arquivos"
            os.environ["COLETUM_PASTA"] = str(raiz)
            for sub in ("saidas", "modelos"):
                if pasta_padrao(sub, Path(t) / "outra_casa") != raiz / sub:
                    erros.append(f"COLETUM_PASTA: {sub} fora de {raiz}")
            os.environ["COLETUM_PASTA"] = "~/coletum_teste_pasta"
            if pasta_padrao("saidas") != Path.home() / "coletum_teste_pasta" / "saidas":
                erros.append("COLETUM_PASTA com ~ não expandiu")
            for vazio in ("", "   "):
                os.environ["COLETUM_PASTA"] = vazio
                if pasta_padrao("saidas", Path(t)) != Path(t) / "Coletum" / "saidas":
                    erros.append(f"COLETUM_PASTA vazia ({vazio!r}) deveria cair no padrão")
            os.environ.pop("COLETUM_PASTA")
            print("COLETUM_PASTA (raiz única, ~ e vazia): verificada")

        # o servidor real, num processo novo: raiz única e as pastas separadas por cima
        with tempfile.TemporaryDirectory() as t:
            casa = Path(t) / "casa"
            casa.mkdir()
            raiz, s, m = Path(t) / "raiz", Path(t) / "so_saidas", Path(t) / "so_modelos"
            r = sonda({"COLETUM_PASTA": str(raiz)}, casa)
            if (Path(r["saida"]), Path(r["modelos"])) != (raiz / "saidas", raiz / "modelos"):
                erros.append(f"servidor com COLETUM_PASTA: {r}")
            r = sonda({"COLETUM_PASTA": str(raiz), "COLETUM_PASTA_SAIDA": str(s), "COLETUM_PASTA_MODELOS": str(m)}, casa)
            if (Path(r["saida"]), Path(r["modelos"])) != (s, m):
                erros.append(f"servidor com COLETUM_PASTA_SAIDA/MODELOS por cima: {r}")
            r = sonda({"COLETUM_PASTA": ""}, casa)
            if Path(r["saida"]).parent.name != "Coletum" or Path(r["saida"]).name != "saidas":
                erros.append(f"servidor com COLETUM_PASTA vazia deveria usar Coletum/saidas: {r}")
            print("servidor (processo novo): raiz única, pastas separadas por cima, raiz vazia")
    finally:
        for v, x in antigo.items():
            if x is not None:
                os.environ[v] = x
    for e in erros:
        print("ERRO:", e)
    print("ok" if not erros else "FALHOU")
    return 0 if not erros else 1


if __name__ == "__main__":
    sys.exit(main())
