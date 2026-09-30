---
name: pdf
description: Gera PDF de preenchimentos de um formulário do Coletum, no padrão do PDF da exportação, com ajustes pedidos na conversa (logo, campos, fotos por linha, cor, página deitada) ou em colunas ou fotográfico. Use quando o cliente pedir PDF, ficha, laudo, relatório fotográfico ou documento para imprimir ou enviar a partir dos dados do Coletum.
---

# PDF de preenchimentos (padrão do Coletum, ajustes e modelos alternativos)

**Qual PDF gerar, antes de tudo.** Tudo sai de `gerar_pdf_preenchimento`:

| O cliente pede | Chamada |
|---|---|
| "PDF", "ficha", sem aparência específica | sem `ajustes`: o **padrão do Coletum** (`coletum_exportacao`), igual ao PDF da exportação |
| "põe meu logo", "tira o campo X", "uma foto por linha", letra, cor, página deitada | `ajustes` (tabela abaixo): valem **no próprio padrão**, o visual continua o do Coletum |
| "em colunas", "compacto", "pergunta de um lado, resposta do outro" | `modelo` `coletum_colunas` (os mesmos `ajustes` valem) |
| "relatório fotográfico", "só as fotos" | `modelo` `coletum_fotografico` (os mesmos `ajustes` valem) |
| título ou rodapé próprios, escolher metadados, 2 campos por linha, limite de fotos | os modelos do Coletum não fazem: a ferramenta **recusa** e lista os ajustes que não existem, sem gerar outro visual; avise o cliente e ofereça o modelo dele (skill **pdf-no-modelo**) |

O cliente quer o layout de um documento dele (laudo, relatório da empresa): skill **pdf-no-modelo**.

Quem segue é o Claude do cliente, com o conector do Coletum ligado. O PDF é montado pelo conector: o conteúdo dos preenchimentos e as fotos **não
passam pela conversa**, só o caminho do arquivo e as contagens.

**A aparência é pela conversa.** O cliente diz o que quer ("tira as observações", "usa verde", "uma foto por
linha") e você traduz cada pedido num ajuste, gera de novo e mostra o resultado. O cliente nunca edita arquivo
de configuração.

**Primeiro:** `ler_preferencias` (0 acessos); use o que estiver lá e não pergunte de novo. Vazio na primeira
tarefa de documento: faça as perguntas essenciais da skill **pdf-no-modelo** (seção "Conhecer o cliente").

## Quando usar

- O cliente quer um documento com **um ou vários preenchimentos** (escolhidos por id ou por período e
  filtro) para imprimir, assinar, anexar a um processo ou mandar a alguém.
- Padrão: o PDF igual ao da exportação do Coletum, com os ajustes que o cliente pedir.
- Alternativos: em colunas (mais compacto) ou fotográfico (as fotos em destaque).

Não use para: tabela com muitos preenchimentos para analisar (skill **planilha**).

## O que perguntar ao cliente

Pergunte só o que ele ainda não disse, em uma mensagem, em lista numerada:

1. **Qual formulário.** Se ele não souber o nome exato, liste e ofereça as opções.
2. **Quais preenchimentos.** Ids, se ele tiver; senão, período, quem preencheu, origem (aplicativo,
   sistema ou link público) ou um valor de campo que você procura na lista.
3. **Um PDF com todos ou um por preenchimento.** O padrão é um arquivo com todos, cada preenchimento
   começando em página nova e um índice no início.
4. **Nome da conta ou da empresa** para o cabeçalho (vai em `ajustes.empresa.nome`; a API não traz o nome
   da conta, então sem ele a linha do nome não sai).

Aparência (logo, campos, cores, fonte, fotos) não se pergunta antes: gere o PDF padrão e ofereça os ajustes
depois de mostrar o resultado.

## Passos

| # | Ferramenta do conector | Para quê | Acessos |
|---|---|---|---|
| 1 | `listar_formularios` com `nome` (parte do nome) e `tamanho_pagina` 500 | achar o `id_formulario` | 1 |
| 2 | `contar_preenchimentos` com os filtros que o cliente deu | saber quantos entram; se forem muitos, combinar antes | 1 |
| 3 | `buscar_preenchimentos` com os mesmos filtros | mostrar id, data, autor e campos principais para o cliente escolher | 1 por página |
| 4 | `gerar_pdf_preenchimento` (ver "Como escolher os preenchimentos"), com `modelo` e `ajustes` só se o cliente já pediu | gerar o arquivo | 1 por busca |
| 5 | mostrar o resultado e oferecer ajustes | caminho, páginas, fotos, avisos | 0 |
| 6 | a cada pedido de ajuste, `gerar_pdf_preenchimento` com os `ajustes` atualizados | nova versão | 1 por busca |

Se o cliente já deu ids e datas (por exemplo, colados do sistema), pule os passos 2 e 3. Se ele pediu
um período e quer todos daquele período, pule o passo 3 e use o filtro direto no passo 4.
A API devolve do mais recente para o mais antigo: "os 5 últimos" é o filtro sem período e
`max_preenchimentos` 5 (1 acesso); para mostrar a lista antes, o passo 3 com `pagina` 1 e `tamanho_pagina` 5.

### Como escolher os preenchimentos

A API **não busca preenchimento pelo id**. Por isso a ferramenta aceita três formas:

| Forma | Parâmetros | Quando | Custo |
|---|---|---|---|
| Por id e data | `preenchimentos`: lista com `id` e `criado_em` de cada um, copiados do passo 3 | o cliente escolheu na lista | 1 acesso por grupo de datas próximas (ids do mesmo dia costumam dividir 1 busca) |
| Por id com período | `ids_preenchimentos` e `criado_depois_de`/`criado_antes_de` | o cliente sabe os ids e o período, mas não as horas | 1 acesso por página de 500 do período |
| Por filtro | período, `origem`, `criado_por` e `max_preenchimentos` (padrão 20, máximo 100) | "todos de setembro", "todos do fulano" | 1 acesso |

Com filtro, se vierem mais preenchimentos que `max_preenchimentos`, entram os mais recentes e a resposta
avisa: combine com o cliente antes de aumentar.

**Um PDF por preenchimento:** passe `modo` `um_por_preenchimento`. Sai um arquivo para cada, com o id
no nome. Diga ao cliente que é só pedir ("quero um arquivo para cada").

**Custo de nova versão:** cada ajuste gera de novo e busca de novo (1 acesso por busca; a estrutura
fica guardada). Junte os pedidos antes de gerar. Para o teste de uma aparência nova num lote grande,
gere primeiro com um preenchimento só e, aprovado, gere o lote.

### Do pedido do cliente para os ajustes

Você passa em `ajustes` só o que muda em relação ao padrão, e mantém os ajustes da conversa de uma
versão para a outra (cada nova chamada leva todos os ajustes combinados até ali).

**No padrão do Coletum e nos dois alternativos** (o visual continua o do Coletum):

| O cliente diz | Você muda |
|---|---|
| "põe o nome da empresa X" | `empresa.nome`: a linha em negrito acima do nome do formulário |
| "põe este logo" | `empresa.logo` com o caminho do arquivo (PNG, JPG, GIF, SVG): no topo à direita, sem empurrar o conteúdo |
| "tira o campo X, tira o Y" | acrescente os rótulos em `campos.ocultar` (vale em qualquer nível, inclusive dentro de grupo; tira também as fotos do campo) |
| "põe o campo X primeiro", "muda a ordem" | `campos.ordem` com os rótulos na ordem pedida; os demais seguem a do formulário |
| "tira os campos em branco" | `campos.mostrar_vazios` falso (no padrão eles saem como "Não informado") |
| "uma foto por linha, maior" / "4 fotos por linha" | `fotos.por_linha` (1 a 4; padrão 3, e 2 no fotográfico). Com 1, a foto ocupa a largura da página |
| "letra maior" / "letra menor" | `fonte.tamanho` (padrão 10; de 6 a 16). "Maior" = 11, "bem maior" = 13; o cabeçalho cresce junto |
| "usa verde", "a cor da minha marca é tal" | `cores.destaque` em `#RRGGBB`: títulos de grupo e barras |
| "página deitada" | `pagina.orientacao` `paisagem` |
| "em colunas", "compacto", "pergunta de um lado, resposta do outro" | `modelo` `coletum_colunas` |
| "relatório fotográfico", "só as fotos" | `modelo` `coletum_fotografico` (cabeçalho, os campos do 1º nível em letra pequena, grupo repetível só com a quantidade de itens, e as fotos grandes com legenda de campo, item e data) |

**O que os modelos do Coletum não fazem** (a ferramenta recusa e lista o que não existe; nada sai em outro visual):

| O cliente diz | Situação |
|---|---|
| "dois campos por linha", "o grupo em tabela", "uma ficha por item" | não existe; ofereça `modelo` `coletum_colunas` ou o modelo dele |
| "só quero os campos A, B e C" | use `campos.ocultar` com os outros |
| "sem fotos", "no máximo N fotos" | não existe |
| "tira o autor", "tira a localização", "muda o título ou o rodapé", "sem o índice" | não existe |

Se o cliente insistir, o caminho é o modelo dele (skill **pdf-no-modelo**).

Use os rótulos como aparecem no formulário (maiúsculas e acentos não
importam); nome que não existe volta em `avisos`. Se não souber o rótulo exato, `estrutura_formulario`
mostra todos (1 acesso na primeira vez).

**Reaproveitar entre conversas:** guarde os ajustes combinados nas preferências (`salvar_preferencias`) e
repita-os na próxima chamada. Isso é um recurso seu; não peça ao cliente para editar arquivo.

### O que dizer ao cliente depois de gerar

- **No fim, o caminho:** sempre mostre ao usuário o caminho completo de cada arquivo, como vem no começo da resposta da ferramenta (e em `mostrar_ao_usuario`), em bloco de código, para ele copiar, sem esperar que ele peça; se ele pedir para abrir, use `mostrar_arquivo`. Nunca diga só que gravou na pasta do projeto.
- Onde está o arquivo (ou os arquivos), quantos preenchimentos entraram, quantas páginas e quantas
  fotos.
- Se houve `fotos_indisponiveis`: quantas e o motivo (`motivos_de_falha`). O quadro "Foto
  indisponível" leva o nome legível do arquivo (data, id do preenchimento, campo, item e ordem).
- Se houve `fotos_fora_do_limite`: quantas ficaram de fora e que dá para aumentar o limite.
- Os avisos da resposta (ajuste que não foi entendido, filtro que trouxe mais preenchimentos que o
  pedido).
- Ofereça em uma linha os ajustes mais comuns: logo, tirar ou reordenar campos, fotos por linha, letra,
  cor, em colunas ou fotográfico.
- Se a ferramenta recusou ajustes: diga quais não existem e ofereça o modelo dele.

Não abra o PDF para conferir lendo o conteúdo na conversa: isso traz dado e imagem para o contexto sem
necessidade. Se o cliente pedir para conferir algo específico, abra só a página em questão.

## Custo

| Etapa | Acessos na cota | Tokens na conversa |
|---|---|---|
| Achar o formulário (lista com página de 500) | 1 | 2 a 7 mil |
| Contar | 1 | menos de 200 |
| Buscar 5 a 20 para escolher (a 1ª chamada também traz a estrutura) | 1, mais 1 na 1ª vez | cerca de 100 por preenchimento |
| Gerar o PDF | 1 por busca | 300 a 600 |
| Cada nova versão | 1 por busca | 300 a 600 |
| **Tarefa inteira, com uma rodada de ajuste** | **5 a 6** | **cerca de 5 a 10 mil** |

Medido com um formulário leve (1 foto) e um pesado (52 itens de grupo, 104 fotos).

**Fotos:** baixar não gasta cota, mas gera tráfego de saída para o Coletum. Cada foto
baixa inteira (mediana estimada de 1,4 MB num formulário leve e 4,7 MB num pesado), e o conector a
reduz para no máximo 1.600 pixels antes de pôr no PDF. Uma chamada baixa até 200 fotos (o mesmo link baixa
uma vez só); as demais saem no quadro "Foto indisponível" com o motivo. Num lote grande, gere por partes.

## Cuidados

- **Campo vazio:** no padrão do Coletum aparece como "Não informado"; `campos.mostrar_vazios` falso tira.
- **Fonte do PDF:** a Noto Sans, a mesma da exportação, vem com o conector.
- O conector **só lê** a API e **só grava** na pasta de saída (`pasta_saida` ou a padrão dele).

## Por que o PDF é uma ferramenta do conector, e não um script da skill

O conector já tem a API, o token, a estrutura guardada e a regra de nome dos anexos. Gerando lá: as
fotos vão do armazenamento direto para o arquivo, sem passar pelo contexto; a skill funciona também no
Claude Desktop sem ambiente para rodar código; e o cliente instala uma coisa só. A skill fica com o
que é dela: o que perguntar, a ordem das chamadas e a tradução dos pedidos em configuração.
