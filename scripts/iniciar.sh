#!/bin/sh
# Sobe o conector do Coletum. Se o uv não estiver instalado, instala uma vez, com o instalador oficial
# (astral.sh), dentro da pasta de dados do plugin: sem senha de administrador e sem mexer no PATH do sistema.
# Tudo que não é o protocolo MCP vai para o stderr: o stdout é só do conector.
#
# No Claude Code, o .mcp.json sobe este script pelo git: `git -c alias.coletum=!sh ".../iniciar.sh" coletum`.
# O plugin declara um comando só para todo sistema, e no Windows ele tem de ser um executável de verdade: o sh
# não está no PATH, o git está quando o Git for Windows está instalado (pré-requisito do plugin no Windows), e alias
# com "!" roda pelo sh do próprio git.
# Efeito colateral: com a pasta atual dentro de um repositório, o git muda para a raiz dele antes de rodar o alias
# e deixa o subdiretório em GIT_PREFIX. Voltamos para ele, para o .env da pasta de quem chamou continuar valendo.
set -e
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "${GIT_PREFIX:-}" ]; then
  cd "$GIT_PREFIX"
fi
# Windows (sh do Git for Windows): quem sobe é o iniciar.cmd, o mesmo do ChatGPT. O "//c" vira "/c" para o
# cmd.exe: o MSYS converteria um "/c" solto em caminho (C:\). O cygpath passa o caminho para o formato do Windows.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) exec cmd.exe //c "$(cygpath -w "$RAIZ/scripts/iniciar.cmd")" ;;
esac
# Cliente que não expande ${CLAUDE_PLUGIN_DATA} (o ChatGPT, por exemplo) manda o texto literal: vale como vazio.
case "${COLETUM_DADOS:-}" in '${'*) COLETUM_DADOS= ;; esac
DADOS="${COLETUM_DADOS:-$HOME/.coletum-mcp}"
UV="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV" ] && [ -x "$DADOS/uv/uv" ]; then
  UV="$DADOS/uv/uv"
fi
if [ -z "$UV" ]; then
  echo "Coletum: instalando o uv em $DADOS/uv (só na primeira vez)..." >&2
  mkdir -p "$DADOS/uv"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$DADOS/uv" UV_NO_MODIFY_PATH=1 sh >&2
  UV="$DADOS/uv/uv"
fi
exec "$UV" run --frozen --quiet --project "$RAIZ" python "$RAIZ/server/server.py"
