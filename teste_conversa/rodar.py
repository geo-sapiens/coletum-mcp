"""Teste de conversa: 10 pedidos em português, cada um num `claude -p` com este plugin, contra o Coletum LOCAL.

Confere a ferramenta do conector que o Claude chamou e os parâmetros-chave (casos.json), nunca o texto da resposta.
Um caso passa se, em algum momento da conversa, a ferramenta esperada foi chamada com os parâmetros esperados.

Uso (da raiz do repo; o claude precisa estar logado no terminal):

    COLETUM_TOKEN=<token do Coletum local> python3 teste_conversa/rodar.py [--modelo sonnet] [01 05 ...]
    python3 teste_conversa/rodar.py --teste      # confere só a comparação, sem rede

COLETUM_BASE_URL padrão https://localhost/api/webservice/v2; host fora de localhost, 127.0.0.1, ::1, *.localhost
ou *.test é recusado (nunca roda contra a produção). Tudo acontece numa pasta temporária fora do repo, apagada no fim.
O token vai num .env dessa pasta (só o dono lê): com --plugin-dir, o .mcp.json passa COLETUM_TOKEN e COLETUM_PASTA
vazios ao conector, que então lê o .env da pasta atual. O Claude testado só tem as ferramentas do conector (menos
configurar_token, que gravaria no cofre do sistema), Skill e ToolSearch: sem Bash, Read nem Write.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import base64
from pathlib import Path
from urllib.parse import urlparse

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
PREFIXO = "mcp__plugin_coletum_coletum__"
BASE_LOCAL = "https://localhost/api/webservice/v2"
MAX_TURNOS, MAX_USD, TEMPO_S = "15", "1.00", 600
FALTA = object()
LOGO_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PREFERENCIAS = ("# Preferências\n- Quem lê: equipe interna, para acompanhar o trabalho.\n- Hoje usam: a exportação do Coletum.\n"
                "- Identidade: GS - Gestão Serviços.\n- Nunca mostrar: nada em especial.\n- Formato: um arquivo com todos.\n")


def valor(entrada, caminho: str):
    """Valor de um caminho com pontos (ajustes.campos.ocultar); FALTA se não existir. Aceita JSON vindo como texto."""
    atual = entrada
    for parte in caminho.split("."):
        if isinstance(atual, str):
            try:
                atual = json.loads(atual)
            except ValueError:
                return FALTA
        if not isinstance(atual, dict) or parte not in atual:
            return FALTA
        atual = atual[parte]
    return atual


def bate(atual, esperado) -> bool:
    """Lista esperada = alternativas; null = ausente; texto = contém (sem diferenciar maiúsculas); lista recebida =
    basta um item bater; número = igual."""
    if isinstance(esperado, list):
        return any(bate(atual, e) for e in esperado)
    if esperado is None:
        return atual is FALTA or atual is None
    if atual is FALTA or atual is None:
        return False
    if isinstance(atual, list):
        return any(bate(a, esperado) for a in atual)
    if isinstance(esperado, str):
        return esperado.lower() in str(atual).lower()
    return str(atual) == str(esperado)


def conferir(caso: dict, chamadas: list[tuple[str, dict]]) -> tuple[bool, str]:
    da_ferramenta = [ent for nome, ent in chamadas if nome == PREFIXO + caso["ferramenta"]]
    if any(all(bate(valor(ent, k), v) for k, v in caso["parametros"].items()) for ent in da_ferramenta):
        return True, ""
    feitas = ", ".join(f"{n.removeprefix(PREFIXO)}({json.dumps(e, ensure_ascii=False)[:160]})" for n, e in chamadas
                       if n.startswith(PREFIXO)) or "nenhuma ferramenta do conector"
    falta = "não chamou" if not da_ferramenta else f"parâmetros esperados {json.dumps(caso['parametros'], ensure_ascii=False)}"
    return False, f"{caso['ferramenta']}: {falta}. Chamadas: {feitas}"


def rodar_caso(caso: dict, pasta: Path, env: dict, modelo: str) -> tuple[bool, str, float]:
    cmd = ["claude", "-p", caso["pedido"].replace("{pasta}", str(pasta)),
           "--plugin-dir", str(REPO), "--setting-sources", "project,local",
           "--tools", "Skill,ToolSearch", "--allowedTools", "mcp__plugin_coletum_coletum", "Skill", "ToolSearch",
           "--disallowedTools", PREFIXO + "configurar_token", "--permission-mode", "dontAsk",
           "--output-format", "stream-json", "--verbose",
           "--max-turns", MAX_TURNOS, "--max-budget-usd", MAX_USD, "--model", modelo]
    try:
        r = subprocess.run(cmd, cwd=pasta, env=env, capture_output=True, text=True, timeout=TEMPO_S)
    except subprocess.TimeoutExpired:
        return False, f"passou de {TEMPO_S} s", 0.0
    chamadas, custo, fim = [], 0.0, ""
    for linha in r.stdout.splitlines():
        try:
            ev = json.loads(linha)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            chamadas += [(c["name"], c.get("input") or {}) for c in ev["message"].get("content", [])
                         if c.get("type") == "tool_use"]
        elif ev.get("type") == "result":
            custo = ev.get("total_cost_usd") or 0.0
            fim = "" if ev.get("subtype") == "success" and not ev.get("is_error") else f" [fim: {ev.get('subtype')} {str(ev.get('result'))[:120]}]"
    ok, motivo = conferir(caso, chamadas)
    if not chamadas and not fim:
        motivo += f" [claude saiu com {r.returncode}: {r.stderr.strip()[:200]}]"
    return ok, motivo + ("" if ok else fim), custo


def main(args: list[str]) -> int:
    modelo = "sonnet"
    if "--modelo" in args:
        i = args.index("--modelo")
        modelo, args = args[i + 1], args[:i] + args[i + 2:]
    base = os.environ.get("COLETUM_BASE_URL") or BASE_LOCAL
    host = urlparse(base).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1") and not host.endswith((".localhost", ".test")):
        sys.exit(f"Recusado: COLETUM_BASE_URL aponta para {host!r}. Este teste só roda contra o Coletum local.")
    token = os.environ.get("COLETUM_TOKEN")
    if not token:
        sys.exit("Falta COLETUM_TOKEN (token do Webservice V2 do Coletum local).")
    casos = [c for c in json.loads((AQUI / "casos.json").read_text(encoding="utf-8")) if not args or c["id"] in args]

    pasta = Path(tempfile.mkdtemp(prefix="coletum-conversa-"))
    try:
        (pasta / "Coletum" / "modelos").mkdir(parents=True)
        (pasta / "Coletum" / "modelos" / "preferencias.md").write_text(PREFERENCIAS, encoding="utf-8")
        (pasta / "logo.png").write_bytes(LOGO_PNG)
        env_arq = pasta / ".env"
        env_arq.touch(mode=0o600)
        env_arq.write_text(f"COLETUM_TOKEN={token}\nCOLETUM_BASE_URL={base}\nCOLETUM_PASTA={pasta / 'Coletum'}\n")
        # Variáveis de sessão do Claude Code que chama este script atrapalham o login do claude filho.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_AGENT_SDK")) and k != "COLETUM_TOKEN"}
        env.update(COLETUM_BASE_URL=base, COLETUM_ABRIR_TESTE="1")

        print(f"Coletum: {base} · modelo: {modelo} · pasta: {pasta}\n")
        passou, total_usd = 0, 0.0
        for caso in casos:
            ok, motivo, custo = rodar_caso(caso, pasta, env, modelo)
            passou += ok
            total_usd += custo
            print(f"[{'passou' if ok else 'FALHOU'}] {caso['id']} {caso['nome']} (US$ {custo:.2f})"
                  + ("" if ok else f"\n    {motivo}"), flush=True)
        print(f"\nTotal: {passou} de {len(casos)} · custo US$ {total_usd:.2f}")
        return 0 if passou == len(casos) else 1
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste() -> None:
    caso = {"ferramenta": "exportar_preenchimentos",
            "parametros": {"id_formulario": 33759, "formato": [None, "xlsx"], "ajustes.campos.mostrar": "ativid",
                           "criado_depois_de": ["2026-08-31", "2026-09-01"]}}
    boa = (PREFIXO + "exportar_preenchimentos", {"id_formulario": "33759", "criado_depois_de": "2026-08-31T23:59:59-03:00",
                                                 "ajustes": '{"campos": {"mostrar": ["Data", "Atividades"]}}'})
    assert conferir(caso, [boa])[0]
    assert not conferir(caso, [(boa[0], {**boa[1], "formato": "csv"})])[0]
    assert not conferir(caso, [(PREFIXO + "contar_preenchimentos", boa[1])])[0]
    assert not conferir(caso, [(boa[0], {**boa[1], "ajustes": {"campos": {"ocultar": ["Atividades"]}}})])[0]
    assert conferir({"ferramenta": "listar_formularios", "parametros": {}}, [(PREFIXO + "listar_formularios", {})])[0]
    print("ok")


if __name__ == "__main__":
    if "--teste" in sys.argv:
        teste()
    else:
        sys.exit(main(sys.argv[1:]))
