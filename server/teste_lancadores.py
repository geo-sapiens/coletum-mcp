"""Teste do par de lançadores do ChatGPT (Codex): sem API e sem rede.

O Codex chama ./scripts/iniciar (sem extensão). No Mac e no Linux roda o sh; no Windows ele acha o
scripts/iniciar.cmd ao lado. O .cmd precisa de CRLF, e o stdout dele é só do protocolo MCP: eco solto quebra a subida.
Uso: uv run --frozen python server/teste_lancadores.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def modo_no_git(caminho: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(RAIZ), "ls-files", "-s", "--", caminho],
                           capture_output=True, text=True, timeout=15)
    except OSError:
        return None
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None


def main() -> int:
    erros = []
    srv = json.loads((RAIZ / ".codex-mcp.json").read_text())["mcpServers"]["coletum"]
    if srv.get("command") != "./scripts/iniciar" or srv.get("cwd") != ".":
        erros.append(f".codex-mcp.json não aponta para ./scripts/iniciar com cwd '.': {srv}")

    sh = RAIZ / "scripts/iniciar"
    if not sh.is_file():
        erros.append("falta scripts/iniciar")
    else:
        b = sh.read_bytes()
        if not b.startswith(b"#!/bin/sh\n") or b"\r" in b:
            erros.append("scripts/iniciar tem de começar com #!/bin/sh e ter só LF")
        if not (os.access(sh, os.X_OK) or modo_no_git("scripts/iniciar") == "100755"):
            erros.append("scripts/iniciar sem bit executável (nem no disco nem no índice do git)")

    cmd = RAIZ / "scripts/iniciar.cmd"
    if not cmd.is_file():
        erros.append("falta scripts/iniciar.cmd")
    else:
        b = cmd.read_bytes()
        if b.count(b"\n") != b.count(b"\r\n"):
            erros.append("scripts/iniciar.cmd não está todo em CRLF")
        linhas = b.decode("ascii").split("\r\n")  # só ASCII: o cmd lê na página de código do console
        if linhas[0].strip().lower() != "@echo off":
            erros.append("scripts/iniciar.cmd não começa com @echo off")
        if not any(re.fullmatch(r'set "COLETUM_UV_SHA256=[0-9a-f]{64}"', x.strip(), re.I) for x in linhas):
            erros.append("scripts/iniciar.cmd sem o SHA-256 fixo de 64 hex")
        # App da Store (MSIX) desvia escritas em AppData: Python e cache do uv vão para %DADOS% antes da 1a menção
        # a "rodar" (goto ou rótulo), para valer em todo caminho até a subida.
        antes = [x.strip().lower() for x in linhas[:next((i for i, x in enumerate(linhas) if "rodar" in x.lower()), 0)]]
        for var, sub in (("uv_python_install_dir", "python"), ("uv_cache_dir", "cache")):
            if f'set "{var}=%dados%\\{sub}"' not in antes:
                erros.append(f"scripts/iniciar.cmd não define {var.upper()}=%DADOS%\\{sub} antes do primeiro goto rodar ou :rodar")
        for n, linha in enumerate(linhas, 1):
            t = linha.strip().lower()
            if not t or t.startswith(("rem ", "::")) or t == "@echo off":
                continue
            if re.search(r"\becho\b", t) and not re.search(r"1?>&2|>\s*nul", t):
                erros.append(f"scripts/iniciar.cmd linha {n} ecoa para o stdout: {linha.strip()}")

    for e in erros:
        print("ERRO:", e)
    print("ok" if not erros else "FALHOU")
    return 0 if not erros else 1


if __name__ == "__main__":
    raise SystemExit(main())
