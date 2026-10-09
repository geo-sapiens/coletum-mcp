# Coletum para o Claude

Plugin do Claude Code que liga o Claude aos dados dos seus formulários do Coletum. Você pede em português, o Claude lê os dados e entrega o arquivo pronto: planilha ou PDF. O conector **só lê** os dados (nunca altera nada no Coletum).

## O que ele faz

O conector oferece 14 ferramentas ao Claude, que você usa conversando:

- **Ler formulários e preenchimentos:** listar seus formulários, ver a estrutura de cada um, contar e buscar preenchimentos por período, origem (aplicativo, sistema ou link público) ou autor.
- **Excel e CSV:** exportar os preenchimentos no mesmo padrão da exportação do Coletum, com ajustes pedidos na conversa (só alguns campos, tudo numa aba, CSV com vírgula).
- **PDF no padrão do Coletum:** o PDF igual ao da exportação, com ajustes (seu logo, tirar campos, fotos por linha, cor, página deitada), ou em colunas, ou relatório fotográfico. Sem logo no pedido, sai o logo do Coletum no topo; com o seu logo, o seu substitui.
- **PDF no seu modelo:** você mostra o documento que a sua empresa já usa (um PDF, um Word salvo em PDF ou uma foto do papel) e o Claude gera os preenchimentos nesse layout, compara com o original, ajusta e guarda o modelo para reusar.
- **Arquivos e preferências:** o conector guarda o que você prefere (logo, nome da empresa) e mostra onde cada arquivo foi gravado.

Quatro roteiros prontos (skills) guiam o Claude em cada tarefa: `/coletum:planilha`, `/coletum:pdf`, `/coletum:pdf-no-modelo` e
`/coletum:migrar-v1`, que converte para a API V2 um script, consulta do Power BI ou código que ainda usa a API V1 (GraphQL),
que sai do ar em 01/11/2026, mantendo o mesmo resultado.

## Instalação

Funciona no **Claude Code**: na aba **Code** do Claude Desktop (Mac ou Windows) e no terminal. No Chat comum e no
Cowork o conector ainda não roda (eles não executam conector local de plugin).

**Precisa de:** o Claude num plano pago e acesso de administrador no Coletum.

### 1. Gere o token no Coletum

1. Entre no Coletum com uma conta de administrador.
2. Vá em **Menu principal > Web Service**.
3. Clique em **Adicionar Token**, dê um nome (por exemplo, "Claude") e salve.
4. Copie o token. Ele não aparece de novo.

### 2. Instale o plugin

**Claude Desktop, aba Code** (sem terminal):

1. Abra a aba **Code** e comece uma sessão escolhendo uma pasta de trabalho (pode ser a de Documentos).
2. Clique no **+** ao lado da caixa de mensagem, depois em **Plugins** e em **Add plugin**.
3. Adicione o marketplace `geo-sapiens/coletum-mcp` e instale o plugin **Coletum**.

Use a aba Code. A tela de plugins das Configurações do app instala o plugin na sua conta, mas no Chat e no Cowork o
conector não roda.

**Claude Code no terminal:**

```
/plugin marketplace add geo-sapiens/coletum-mcp
/plugin install coletum@coletum-mcp
```

### 3. Primeira conversa

1. Abra uma conversa nova e peça: **"liste meus formulários do Coletum"**.
2. **Token:** pelo terminal, a instalação já pediu o token. Pela aba Code do Desktop, o Claude avisa que falta o token:
   cole o token na conversa, o conector testa com 1 chamada e guarda no cofre do sistema (Keychain no Mac, Credential
   Manager no Windows). Nas próximas conversas não pede mais. O token fica escrito no histórico daquela conversa: ele é
   só de leitura, e você pode desativar e gerar outro no Coletum quando quiser.
3. Aparece a lista dos formulários da conta.

### 4. Use

Peça em português, por exemplo:

- "Exporta para Excel os preenchimentos desta semana do formulário NOME DO FORMULÁRIO"
- "Só os campos X e Y", "tudo numa aba só", "em CSV", "dos últimos 7 dias"
- "Gera o PDF dos 3 mais recentes", "põe meu logo e tira o campo Observações", "relatório fotográfico"

Os arquivos ficam em `Documentos/Coletum` (planilhas e PDFs em `saidas/`, modelos em `modelos/`), e o Claude mostra o
caminho completo. Para outra pasta, diga no pedido ("salva na pasta X"). Para abrir, peça "abre o arquivo".

### Primeira vez e Windows

**Na primeira vez**, o conector prepara o que precisa para rodar e leva alguns instantes a mais. Ele usa o `uv`
(gerenciador de Python da Astral): se o `uv` não estiver instalado, o conector baixa o **instalador oficial**
(`astral.sh/uv/install.sh`) e instala o `uv` só dentro da pasta de dados do plugin, sem senha de administrador e sem
alterar o sistema. Depois, o `uv` baixa o Python e as bibliotecas do conector (uns 60 MB, uma vez).

**Windows:** ainda em teste. O conector sobe por um script `sh`. Se ele não subir, instale o `uv` uma vez no
PowerShell (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`), reinicie o Claude e
avise pelo suporte do Coletum, com um print da resposta do Claude.

### No ChatGPT (chat, work e Codex)

1. No app do ChatGPT, vá em **Plugins > Add > Add a marketplace** e informe `geo-sapiens/coletum-mcp`, ref `main`.
2. Ative o plugin **coletum**.
3. Na primeira conversa, peça: **"configure meu token do Coletum"** e cole o token gerado no passo 1. O conector testa
   e guarda no cofre do sistema, como no Claude.

No Windows ainda não funciona (em teste).

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
| `COLETUM_INTERVALO_S` | intervalo mínimo, em segundos, entre o início de duas requisições (opcional; padrão 0,5) |
| `COLETUM_MAX_CHAMADAS_HORA` | teto de chamadas por hora, janela móvel (opcional; padrão 300) |

Os roteiros da pasta `skills/` também chegam a esses clientes como prompts do servidor (`coletum-planilha`, `coletum-pdf`, `coletum-pdf-no-modelo`, `coletum-migrar-v1`).

## Cota da API

Hoje, enquanto a API v1 existir, cada chamada à API v2 do Coletum consome **0,2** da cota mensal da conta (5 chamadas = 1 unidade da cota); essa regra pode mudar quando a v1 sair. Cada página lida conta; chamada com erro não conta. Toda ferramenta informa `chamadas_api` e `cota_consumida` (calculada com o peso atual), e o Claude conta os preenchimentos antes de exportar para avisar o custo. Baixar as fotos dos anexos não gasta cota.

Para proteger a cota contra rajadas, o conector:

- espera **0,5 s** entre o início de duas chamadas (`COLETUM_INTERVALO_S` muda o intervalo);
- recusa, antes de chamar, passar de **300 chamadas por hora** (janela móvel, somando todas as conversas; `COLETUM_MAX_CHAMADAS_HORA` muda o teto). Os horários ficam num arquivo pequeno, `.uso_api.json`, na pasta dos arquivos;
- identifica o uso com `source=mcp` em toda requisição.

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
uv run python server/teste_limites.py
uv run python server/teste_token.py
uv run python server/teste_estrela_data.py
uv run python server/teste_versoes.py
```

## Licença

Código sob a licença [MIT](LICENSE), © GeoSapiens. A fonte Noto Sans, que vai junto nos modelos, segue a licença dela (SIL Open Font License, em `server/modelos/_fontes/OFL.txt`). "Coletum" é marca da GeoSapiens; a licença do código não cede a marca.
