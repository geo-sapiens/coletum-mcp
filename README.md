# Coletum para o Claude

Plugin do Claude Code que liga o Claude aos dados dos seus formulários do Coletum. Você pede em português, o Claude lê os dados e entrega o arquivo pronto: planilha ou PDF. O conector **só lê** os dados (nunca altera nada no Coletum).

## O que ele faz

O conector oferece 13 ferramentas ao Claude, que você usa conversando:

- **Ler formulários e preenchimentos:** listar seus formulários, ver a estrutura de cada um, contar e buscar preenchimentos por período, origem (aplicativo, sistema ou link público) ou autor.
- **Excel e CSV:** exportar os preenchimentos no mesmo padrão da exportação do Coletum, com ajustes pedidos na conversa (só alguns campos, tudo numa aba, CSV com vírgula).
- **PDF no padrão do Coletum:** o PDF igual ao da exportação, com ajustes (seu logo, tirar campos, fotos por linha, cor, página deitada), ou em colunas, ou relatório fotográfico.
- **PDF no seu modelo:** você mostra o documento que a sua empresa já usa (um PDF, um Word salvo em PDF ou uma foto do papel) e o Claude gera os preenchimentos nesse layout, compara com o original, ajusta e guarda o modelo para reusar.
- **Arquivos e preferências:** o conector guarda o que você prefere (logo, nome da empresa) e mostra onde cada arquivo foi gravado.

Três roteiros prontos (skills) guiam o Claude em cada tarefa: `/coletum:planilha`, `/coletum:pdf` e `/coletum:pdf-no-modelo`.

## Instalação

Funciona no **Claude Code**, inclusive dentro do **Claude Desktop** (aba Code).

1. **Gere o token** do Webservice V2 na sua conta do Coletum.
2. **Adicione o marketplace e instale o plugin:**
   - **Claude Desktop, aba Code:** no botão **+** ao lado da caixa de mensagem, abra **Plugins**, depois **Add plugin**, adicione o marketplace `geo-sapiens/coletum-mcp` e instale o plugin **coletum**.
   - **Claude Code no terminal:**
     ```
     /plugin marketplace add geo-sapiens/coletum-mcp
     /plugin install coletum@coletum-mcp
     ```
3. O Claude pede o **token** (fica guardado no cofre de credenciais do seu sistema) e a **pasta dos arquivos** (opcional: onde ficam planilhas, PDFs e modelos; vazio = `Documentos/Coletum`).
4. Abra uma conversa e peça, por exemplo: "liste meus formulários do Coletum" ou "exporte em Excel os preenchimentos de setembro da vistoria".

**Na primeira vez**, o conector prepara o que precisa para rodar e leva alguns instantes a mais. Ele usa o `uv` (gerenciador de Python da Astral): se o `uv` não estiver instalado, o conector baixa o **instalador oficial** (`astral.sh/uv/install.sh`) e instala o `uv` só dentro da pasta de dados do plugin, sem senha de administrador e sem alterar o sistema. Depois, o `uv` baixa o Python e as bibliotecas do conector (uns 60 MB, uma vez).

**Windows:** ainda não testado. O conector sobe por um script `sh`; se no seu Windows ele não subir, instale o `uv` uma vez no PowerShell (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`) e avise pelo suporte do Coletum.

## Como atualizar

Marketplace de terceiros vem com a atualização automática desligada. Para pegar a versão nova, rode no Claude Code:

```
/plugin marketplace update coletum-mcp
```

ou, em `/plugin`, abra **Marketplaces**, escolha `coletum-mcp` e ative **Enable auto-update**. As mudanças de cada versão estão no [CHANGELOG](CHANGELOG.md).

## Uso em outras IAs

O conector é um servidor MCP comum (stdio) e funciona em qualquer cliente MCP. Com o `uv` instalado e este repositório baixado, o comando é:

```
uv run --project /caminho/para/coletum-mcp python /caminho/para/coletum-mcp/server/server.py
```

com estas variáveis de ambiente:

| Variável | Para quê |
|---|---|
| `COLETUM_TOKEN` | token do Webservice V2 (obrigatória) |
| `COLETUM_PASTA` | pasta dos arquivos: saídas em `<pasta>/saidas` e modelos em `<pasta>/modelos` (opcional; vazio = `Documentos/Coletum`) |
| `COLETUM_PASTA_SAIDA`, `COLETUM_PASTA_MODELOS` | pastas separadas, se preferir (valem por cima de `COLETUM_PASTA`) |

Os roteiros da pasta `skills/` também chegam a esses clientes como prompts do servidor (`coletum-planilha`, `coletum-pdf`, `coletum-pdf-no-modelo`).

## Cota da API

Cada chamada à API do Coletum gasta **1 acesso** da cota mensal da conta (cada página lida conta; erro não conta). Toda ferramenta informa quantos acessos gastou, e o Claude conta os preenchimentos antes de exportar para avisar o custo. Baixar as fotos dos anexos não gasta cota.

## Privacidade

- O conector **roda no seu computador** e fala direto com a API do Coletum. Nada passa por servidor nosso.
- Ele **só lê** os dados. Só grava arquivos na pasta que você escolheu.
- O token fica no cofre de credenciais do sistema (cofre de credenciais do Mac, do Windows ou do Linux) e nunca é impresso.
- Planilhas e PDFs são gerados pelo conector: o conteúdo dos preenchimentos e as fotos não passam pela conversa, só o caminho do arquivo e as contagens.

## Desenvolvimento

Os testes rodam sem API e sem rede:

```
uv run python server/teste_pastas.py
uv run python server/teste_subida.py
```

## Licença

Código sob a licença [MIT](LICENSE), © GeoSapiens. A fonte Noto Sans, que vai junto nos modelos, segue a licença dela (SIL Open Font License, em `server/modelos/_fontes/OFL.txt`). "Coletum" é marca da GeoSapiens; a licença do código não cede a marca.
