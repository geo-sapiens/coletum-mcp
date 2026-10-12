"""Teste dos lançadores: sem API e sem rede.

O Codex chama ./scripts/iniciar (sem extensão). No Mac e no Linux roda o sh; no Windows ele acha o
scripts/iniciar.cmd ao lado. O .cmd precisa de CRLF, e o stdout dele é só do protocolo MCP: eco solto quebra a subida.
O Claude Code sobe pelo .mcp.json, que chama o iniciar.sh por um alias do git (o mesmo comando no Mac e no Windows).
Fora do Windows, o teste sobe o conector por esse comando, com o plugin numa pasta com espaço no nome e a pasta
atual num subdiretório de um repositório git, e manda um initialize do MCP. O uv roda offline (UV_OFFLINE=1): as
dependências têm de estar no cache do uv.
Uso: uv run --frozen python server/teste_lancadores.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def modo_no_git(caminho: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(RAIZ), "ls-files", "-s", "--", caminho],
                           capture_output=True, text=True, timeout=15)
    except OSError:
        return None
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None


ARGS_GIT = ["-c", 'alias.coletum=!sh "${CLAUDE_PLUGIN_ROOT}/scripts/iniciar.sh"', "coletum"]


def subida_pelo_git(erros: list[str]) -> None:
    """Sobe pelo comando do .mcp.json: plugin em pasta com espaço, pasta atual em subdiretório de um repo git."""
    with tempfile.TemporaryDirectory(prefix="coletum teste ") as tmp:
        tmp = Path(tmp).resolve()
        plugin = tmp / "plugin com espaço"
        shutil.copytree(RAIZ, plugin, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".env"))
        args = [a.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin)) for a in ARGS_GIT]
        sub = tmp / "projeto" / "sub pasta"
        sub.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(sub.parent)], check=True)
        base = {**os.environ, "COLETUM_DADOS": str(tmp / "dados"), "COLETUM_PASTA": str(tmp / "saidas"),
                "COLETUM_TOKEN": ""}
        base.pop("VIRTUAL_ENV", None)

        # 1) pasta atual: um uv falso imprime onde o servidor subiria
        falso = tmp / "bin"
        falso.mkdir()
        (falso / "uv").write_text("#!/bin/sh\npwd -P\n")
        (falso / "uv").chmod(0o755)
        r = subprocess.run(["git", *args], cwd=sub, capture_output=True, text=True, timeout=30,
                           env={**base, "PATH": f"{falso}{os.pathsep}{base['PATH']}"})
        if r.stdout.strip() != str(sub):
            erros.append(f"pelo git, o servidor subiria em {r.stdout.strip()!r}, e não na pasta de quem chamou "
                         f"{str(sub)!r} (stderr: {r.stderr.strip()})")

        # 2) servidor de verdade: initialize pelo stdin, resposta pelo stdout
        p = subprocess.Popen(["git", *args], cwd=sub, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env={**base, "UV_OFFLINE": "1"})
        pedido = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "teste_lancadores", "version": "0"}}}
        try:
            saida, err = p.communicate(json.dumps(pedido) + "\n", timeout=180)
        except subprocess.TimeoutExpired:
            p.kill()
            saida, err = p.communicate()
        try:
            resposta = json.loads(saida.splitlines()[0])
            nome = resposta["result"]["serverInfo"]["name"]
            print(f"subida pelo git: initialize respondeu, serverInfo.name = {nome!r}")
        except (IndexError, KeyError, ValueError):
            erros.append(f"pelo git, o conector não respondeu ao initialize. stdout: {saida[:300]!r} "
                         f"stderr: {err[-800:]!r}")


def main() -> int:
    erros = []
    mcp = json.loads((RAIZ / ".mcp.json").read_text())["mcpServers"]["coletum"]
    if mcp.get("command") != "git" or mcp.get("args") != ARGS_GIT:
        erros.append(f".mcp.json não sobe o iniciar.sh pelo alias do git: {mcp}")
    if set(mcp.get("env", {})) != {"COLETUM_TOKEN", "COLETUM_PASTA", "COLETUM_DADOS"}:
        erros.append(f".mcp.json com env diferente do esperado: {mcp.get('env')}")
    if os.name != "nt" and shutil.which("git") and not erros:
        subida_pelo_git(erros)
    else:
        print("subida pelo git: pulada (Windows, sem git ou .mcp.json errado)")

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
