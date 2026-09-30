---
name: pdf-no-modelo
description: Gera o PDF dos preenchimentos do Coletum no layout que o cliente já usa (documento da empresa, laudo, relatório de vistoria), a partir de um PDF ou foto do modelo dele. Use quando o cliente disser que quer no modelo dele, igual ao documento que a empresa usa ou no layout de um arquivo que ele mandar.
---

# PDF no modelo do cliente

Quem segue é o Claude do cliente, com o conector do Coletum ligado. O conector monta os dados (contrato em `CONTRATO_DADOS.md`, nesta pasta), baixa as
fotos e compila o template com o Typst: o conteúdo dos preenchimentos e as fotos **não passam pela
conversa**, só o caminho do PDF, as contagens e as imagens de comparação.

**Primeiro:** `ler_preferencias`. Se estiver vazio, faça antes a seção "Conhecer o cliente" abaixo.

## Quando usar

- **Pedido simples de PDF, ou com ajustes de aparência** (logo, nome da empresa, tirar ou ordenar campos, fotos
  por linha, letra, cor de destaque, página deitada), **em colunas** ou **relatório fotográfico**: não é esta skill. É a skill **pdf** (`gerar_pdf_preenchimento`), que aplica tudo isso no próprio padrão do
  Coletum (`coletum_exportacao`) ou nos alternativos embutidos (`coletum_colunas`, `coletum_fotografico`), sem
  escrever template.
- O cliente tem um documento de referência e quer os preenchimentos nele: layout exato, com as
  seções, a ordem e a identidade dele.
- O cliente quer a exportação do Coletum com algum ajuste que os três embutidos não fazem: parta do
  `coletum_exportacao` (`listar_modelos` com `mostrar_template` traz o texto dele; ele importa
  `/coletum_estilo.typ`, que vem em toda pasta de trabalho, e lê `documento.aparencia`).

Se ele disser "gera no modelo X" e o modelo já existe (`listar_modelos`), pule direto para o passo 8.

## Conhecer o cliente (só na primeira vez, se `ler_preferencias` vier vazio)

Uma mensagem só, em lista numerada; ele pode pular qualquer pergunta:

1. **Quem lê** o documento e **para quê** (equipe, gestor, cliente final, órgão fiscalizador; comprovar, anexar a
   processo, prestar contas).
2. **O que já usam hoje** para isso. Se tiver um exemplo (PDF, Word salvo como PDF ou foto do papel), é o modelo
   desta skill.
3. **Identidade:** nome da empresa como deve aparecer, logo (o arquivo) e cores.
4. **O que nunca pode aparecer** (observações internas, coordenada, algum campo) e se prefere um arquivo com
   todos ou um por preenchimento.

Guarde as respostas com `salvar_preferencias` (markdown curto: quem lê e para quê, hoje usam, identidade, nunca
mostrar, formato). "Nunca mostrar" vira `campos.ocultar` no PDF padrão ou fica fora do template; identidade vai
para `empresa` e `logo`. Quando ele corrigir algo que vale para as próximas vezes, acrescente com
`salvar_preferencias` modo `acrescentar`. Não pergunte de novo o que já está lá e não guarde dado de
preenchimento.

## O que perguntar ao cliente

Pergunte só o que ainda não sabe (olhe as preferências), numa mensagem, em lista numerada:

1. **O modelo:** o arquivo (PDF, Word salvo como PDF ou foto do papel). Um preenchido é melhor que um em
   branco: mostra como fica o texto real.
2. **Qual formulário** do Coletum alimenta esse documento.
3. **Um documento por preenchimento ou vários num arquivo.**
4. **Nome do modelo** para reusar ("obra", "laudo_mensal"). Pode ficar para o fim.

## Passos

| # | Ferramenta | Para quê | Acessos |
|---|---|---|---|
| 1 | `ler_preferencias` e `listar_modelos` | não perguntar de novo; ver se o modelo já existe | 0 |
| 2 | `analisar_pdf_modelo` com o caminho do arquivo | ver as páginas (vêm como imagem) e medir: margens, fontes, tamanhos, cores, posição de cada texto, logo salvo em disco | 0 |
| 3 | `listar_formularios` e `estrutura_formulario` | rótulos e chaves dos campos para o de-para | 1 a 2 |
| 4 | montar o de-para (ver abaixo) e confirmar com o cliente **só os rótulos que não casam** | mapeamento | 0 |
| 5 | `buscar_preenchimentos` | escolher 1 preenchimento representativo para a amostra | 1 |
| 6 | escrever o template e `gerar_pdf_modelo` com `template_typst`, `mapeamento`, `logo` (o arquivo que o passo 2 salvou), 1 preenchimento e `comparar_com` o modelo | amostra e imagem lado a lado | 1 a 2 |
| 7 | comparar a imagem, corrigir e gerar de novo (repita; `pagina_comparada` para as outras páginas); mostrar ao cliente | chegar no layout | 1 por rodada |
| 8 | `salvar_modelo` com nome, template, mapeamento, logo, `formularios` e `variaveis` | reusar | 0 |
| 9 | `gerar_pdf_modelo` com `modelo` = nome e os preenchimentos pedidos | o documento de verdade | 1 por busca |

"Os 5 últimos": só filtro e `max_preenchimentos` 5, porque a API devolve do mais recente para o mais antigo.

### De-para: rótulo do modelo para campo do formulário

Liste os rótulos que aparecem no modelo (o passo 2 traz o texto de cada linha) e case cada um com um
campo da estrutura. Monte a tabela para o cliente ver:

| No modelo | Campo do Coletum | Situação |
|---|---|---|
| Data da vistoria | `meta:criado_em` | casa |
| Km | `CADASTRO/KM` | casa |
| Contratante | nenhum | **não casa**: texto fixo? |

- Metadados também servem: `meta:criado_por`, `meta:criado_em`, `meta:horario_dispositivo`,
  `meta:plataforma`, `meta:coordenada`, `meta:id`.
- Campo dentro de grupo: `GRUPO/CAMPO` pega o 1º item; `GRUPO[2]/CAMPO`, o 2º.
- Duas fontes possíveis: lista de alternativas, `["Localização", "CADASTRO/LOCALIZAÇÃO"]`.
- **Não casa:** pergunte ao cliente se é texto fixo da empresa (vai para `variaveis` do modelo, como
  obra e contratante), se sai em branco (`""`) ou se sai do documento. Não invente campo.

### Como escrever o template

Parta deste esqueleto e replique o que o passo 2 mediu (tamanho da página, margens em mm, fontes e
tamanhos em pt, cores em hexadecimal, posição dos blocos):

```typst
#import "/coletum.typ": *
#set page(paper: "a4", margin: (x: 15mm, top: 40mm, bottom: 20mm),
  footer: context [Página #counter(page).display() de #counter(page).final().first()])
#set text(font: ("Noto Sans",), size: 9.5pt, lang: "pt")
#for (i, p) in dados.preenchimentos.enumerate() {
  if i > 0 { pagebreak() }
  counter(page).update(1)
  table(columns: (50mm, 1fr),
    [Obra], dados.documento.variaveis.at("obra", default: nao_informado),
    [Data], valor_mapeado(p, "Data da vistoria"))
  grid(columns: (1fr, 1fr), gutter: 8mm, ..fotos(p).map(a => foto(a, width: 100%, height: 60mm, fit: "cover")))
}
```

- **Layout de faixa ou fundo:** `set page(background: ...)` com `place(top + left, dx: .., dy: .., ...)`.
- **Tabela de identificação:** `table(columns: (50mm, 1fr), fill: (x, _) => if x == 0 { rgb("#EEF1F4") })`.
- **Campos em duas colunas:** `grid(columns: (1fr, 1fr), column-gutter: 6mm, ...)`.
- **Todos os campos em ordem** (quando o modelo é genérico): percorra `p.campos`, tratando `classe`
  `grupo` (itens), `anexo` (`foto`) e o resto por `valor_formatado`. O `modelo.typ` do embutido
  `coletum_exportacao` faz isso e serve de referência.
- **Logo:** passe `logo` na chamada (ou em `salvar_modelo`); no template, `image("/arquivos/logo.png")`
  ou `dados.documento.logo`.
- **Fonte:** a Noto Sans, a mesma do PDF da exportação, vem com o conector e entra em toda compilação: use
  `font: ("Noto Sans",)` quando o modelo do cliente tem letra sem serifa e ele não mandou a fonte. Com o
  arquivo da fonte dele (.ttf, .otf), passe em `salvar_modelo(fontes=...)` e ponha o nome dela antes na lista.
- **Vários preenchimentos num PDF com "Página X de Y" por documento:** marque início e fim de cada um com
  `metadata` e rótulo (um marcador no começo e outro no fim de cada preenchimento) e conte as páginas entre eles.

### Erros comuns do Typst e como corrigir

A resposta traz a mensagem do Typst com arquivo, linha e coluna (`modelo.typ:12:5`). Os mais comuns:

| Mensagem | Causa | Correção |
|---|---|---|
| `unknown variable: f` | função usada antes de ser definida, ou nome errado | defina antes de usar: o Typst não enxerga o que vem depois |
| `dictionary does not contain key "x"` | `p.x` numa chave que não existe | `p.at("x", default: none)`, ou confira no contrato |
| `cannot access fields on type none` | `campo(...)` ou `mapeado(...)` não achou e o template leu `.valor_formatado` | use `valor(...)` ou `valor_mapeado(...)`, que já trocam por "Não informado" |
| `file not found (searched at ...)` | caminho de imagem errado | fotos em `/fotos/`, arquivos do modelo em `/arquivos/`, sempre com `/` no começo |
| `path ... would escape the project root` | tentou ler fora da pasta do trabalho | passe o arquivo em `arquivos` ou `logo` |
| `unclosed delimiter` | parêntese ou colchete aberto | a coluna aponta o lugar |
| `cannot add string and integer` | somou texto com número | `str(n)` ou `[#n]` |
| aviso "Fontes não instaladas" (em `avisos_typst`) | a fonte do modelo não está nesta máquina | salve o arquivo da fonte com o modelo, ou use a Noto Sans, que vem com o conector |

## O que dizer ao cliente

- **No fim, o caminho:** sempre mostre ao usuário o caminho completo de cada arquivo, como vem no começo da resposta da ferramenta (e em `mostrar_ao_usuario`), em bloco de código, para ele copiar, sem esperar que ele peça; se ele pedir para abrir, use `mostrar_arquivo`. Nunca diga só que gravou na pasta do projeto.
- Mostre o lado a lado da amostra, diga o que ficou igual e o que ficou diferente (fonte substituta,
  campo sem correspondente) e pergunte o que ajustar.
- Depois de salvar: o nome do modelo e como pedir de novo ("é só pedir: gera no modelo obra os
  preenchimentos de ontem").
- Fotos indisponíveis: quantas e o motivo (`fotos.motivos_de_falha`).
- Rótulos sem campo (`mapeamento.sem_campo`): saem vazios; ofereça texto fixo em `variaveis`.

## Custo

| Etapa | Acessos | Tokens na conversa |
|---|---|---|
| Analisar o modelo (2 páginas) | 0 | 5 a 8 mil (JSON e imagens) |
| Formulários e estrutura | 1 a 2 | 3 a 10 mil |
| Buscar para escolher | 1 | cerca de 100 por preenchimento |
| Cada amostra com lado a lado | 1 (mais 1 pela estrutura na 1ª vez) | 1,5 a 2,5 mil (imagem e JSON) |
| Reusar pelo nome | 1 por busca | menos de 1 mil |

Compilar leva menos de 0,1 s por
documento (20 preenchimentos pesados, 1.160 páginas, em 0,44 s); o tempo da chamada é a busca na API e
o download das fotos.

## Cuidados

- O template roda numa pasta isolada: não lê arquivo do computador nem baixa pacote da internet.
- Os modelos ficam na máquina do cliente (`COLETUM_PASTA_MODELOS`). `salvar_modelo` não sobrescreve sem
  `substituir=true`: confirme com o cliente antes.
- O embutido `coletum_exportacao` não pode ser trocado; para mudar, pegue o texto com
  `listar_modelos(mostrar_template="coletum_exportacao")`, ajuste e salve com outro nome.
