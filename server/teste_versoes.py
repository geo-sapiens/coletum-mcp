"""Teste das versões: sem API e sem rede.

O plugin tem a versão em três lugares: o manifesto do Claude, o do ChatGPT (Codex) e o pyproject. O Codex só
atualiza o plugin instalado quando a versão do manifesto dele muda, então os três precisam andar juntos.
Uso: uv run --frozen python server/teste_versoes.py
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    versoes = {
        ".claude-plugin/plugin.json": json.loads((RAIZ / ".claude-plugin/plugin.json").read_text())["version"],
        ".codex-plugin/plugin.json": json.loads((RAIZ / ".codex-plugin/plugin.json").read_text())["version"],
        "pyproject.toml": tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]["version"],
    }
    assert len(set(versoes.values())) == 1, f"versões divergentes: {versoes}"
    print(f"ok: versão {versoes['pyproject.toml']} nos três arquivos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
