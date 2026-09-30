# Changelog

## 1.0.0

Primeira versão pública do plugin.

- Conector MCP só de leitura com 13 ferramentas: formulários, estrutura, contagem e busca de preenchimentos, exportação em Excel e CSV, PDF no padrão do Coletum (com ajustes, em colunas e fotográfico), PDF no modelo do cliente, modelos e preferências salvos, abrir o arquivo gerado.
- Três skills: `planilha`, `pdf` e `pdf-no-modelo`.
- Na primeira vez, instala o `uv` sozinho (instalador oficial, dentro da pasta de dados do plugin) se ele não existir.
- Configuração pelo Claude Code: token (no cofre do sistema) e pasta dos arquivos (`COLETUM_PASTA`, padrão Documentos/Coletum).
