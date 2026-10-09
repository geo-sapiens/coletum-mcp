#!/bin/sh
# Sobe o conector do Coletum. Se o uv não estiver instalado, instala uma vez, com o instalador oficial
# (astral.sh), dentro da pasta de dados do plugin: sem senha de administrador e sem mexer no PATH do sistema.
# Tudo que não é o protocolo MCP vai para o stderr: o stdout é só do conector.
set -e
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
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
