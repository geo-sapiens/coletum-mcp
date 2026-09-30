"""Teste da subida do servidor: sem API e sem chamar ferramenta nenhuma.

Importa o server num processo novo e confere que todos os módulos do conector já estão carregados.
Import tardio (dentro da ferramenta) fazia o servidor misturar versões quando o código mudava com ele
no ar: o módulo novo procurava no achatar antigo, já na memória, uma função que ainda não existia.
Uso: uv run python server/teste_subida.py
"""
from __future__ import annotations

import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MODULOS = ("achatar", "api", "baixar", "contrato", "fotos_teste", "modelos", "planilha")


def main() -> int:
    antes = set(sys.modules)
    sys.path.insert(0, str(AQUI))
    import server  # noqa: F401

    # os .py do conector na pasta (menos testes e o próprio server) têm de estar todos na lista acima
    na_pasta = {p.stem for p in AQUI.glob("*.py") if not p.stem.startswith("teste_") and p.stem != "server"}
    fora_da_lista = sorted(na_pasta - set(MODULOS))
    ja_carregados = sorted(m for m in MODULOS if m in antes)
    faltam = [m for m in MODULOS if m not in sys.modules]
    for m in MODULOS:
        print(f"{m:10s} {'carregado' if m in sys.modules else 'FALTA'}")
    ok = True
    if fora_da_lista:
        print(f"ERRO: módulo do conector fora da lista do teste: {', '.join(fora_da_lista)}")
        ok = False
    if ja_carregados:
        print(f"ERRO: módulos carregados antes do server, o teste não prova nada: {', '.join(ja_carregados)}")
        ok = False
    if faltam:
        print(f"ERRO: não carregaram na subida: {', '.join(faltam)}")
        ok = False
    print("ok" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
