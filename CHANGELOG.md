# Changelog

## 1.1.0

- Skill nova `migrar-v1`: converte para a API V2 o código que ainda chama a API V1 (GraphQL), desligada em 01/11/2026, com um adaptador que mantém o mesmo resultado para quem consome os dados. Testada em dois projetos reais (Node.js chamando a V1 direto e R com o pacote RColetum): saída idêntica à da V1 nos dois.

## 1.0.3

- Token pela conversa: quando a instalação não pede o token (tela de plugins do Claude Desktop), o Claude pede na primeira conversa, o conector testa e guarda no cofre do sistema. Ferramenta nova: `configurar_token`.
- Token e pasta com valor padrão vazio no manifesto, para o conector carregar também onde a instalação não pede valores.

## 1.0.2

- Instalação pela tela de plugins do Claude Desktop (Configurações, Plugins): o script de partida saiu da pasta `bin/`, que essa tela não aceita.
- A pasta dos arquivos é opcional e não é perguntada na instalação: sem valor, o conector usa `Documentos/Coletum`, mesmo quando o Claude repassa a opção vazia sem substituir.
- O conector sobe com as versões exatas das bibliotecas registradas no repositório.

## 1.0.1

- **Cota da API mais clara.** As respostas agora trazem `chamadas_api` e `cota_consumida` (no lugar de `acessos_gastos`). Hoje, enquanto a API v1 existir, cada chamada à API v2 consome 0,2 da cota mensal (5 chamadas = 1 unidade), e o Claude passa a avisar o custo nesses termos. A contagem antes de exportar mostra as chamadas e a cota.
- **Proteção contra rajadas.** O conector espera 0,5 s entre duas chamadas e recusa passar de 300 chamadas por hora, somando todas as conversas, com aviso de quando libera. Os dois limites podem ser mudados por `COLETUM_INTERVALO_S` e `COLETUM_MAX_CHAMADAS_HORA`.
- **Uso identificado.** Toda requisição leva `source=mcp`, para o Coletum saber de onde vem o uso.
- **Logo do Coletum no PDF.** Nos três modelos do Coletum, quando o pedido não traz logo, sai o logo do Coletum no topo; o seu logo, se você informar, substitui. Modelos salvos por você não mudam.
- As instruções do Claude (skills) reforçam: usar sempre as ferramentas do conector e nunca um script que chame a API por fora.

## 1.0.0

Primeira versão pública do plugin.

- Conector MCP só de leitura com 13 ferramentas: formulários, estrutura, contagem e busca de preenchimentos, exportação em Excel e CSV, PDF no padrão do Coletum (com ajustes, em colunas e fotográfico), PDF no modelo do cliente, modelos e preferências salvos, abrir o arquivo gerado.
- Três skills: `planilha`, `pdf` e `pdf-no-modelo`.
- Na primeira vez, instala o `uv` sozinho (instalador oficial, dentro da pasta de dados do plugin) se ele não existir.
- Configuração pelo Claude Code: token (no cofre do sistema) e pasta dos arquivos (`COLETUM_PASTA`, padrão Documentos/Coletum).
