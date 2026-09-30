---
name: planilha
description: Exporta preenchimentos de um formulário do Coletum para Excel ou CSV no padrão da exportação do sistema, ou num formato pedido pelo cliente. Use quando o cliente pedir planilha, Excel, CSV, exportar os dados ou levar os dados para Power BI, R ou outro sistema.
---

# Planilha (Excel e CSV)

Quem segue é o Claude do cliente, com o conector do Coletum ligado. A ferramenta `exportar_preenchimentos` grava o arquivo em
disco e devolve só o caminho e as contagens: os dados **não passam pela conversa**.

**Primeiro:** `ler_preferencias` (não chama a API); use o que estiver lá e não pergunte de novo. Vazio na primeira
tarefa de documento: faça as perguntas essenciais da skill **pdf-no-modelo** (seção "Conhecer o cliente").

## Quando usar

- O cliente quer os preenchimentos de um formulário numa planilha, para abrir, filtrar, somar ou
  mandar a alguém.
- O cliente quer alimentar outro sistema (Power BI, R, Python, banco) com um arquivo.

Não use para: um documento de um preenchimento (skill **pdf**). A planilha traz só os links das fotos.

## O que perguntar ao cliente

Pergunte só o que ele ainda não disse, em uma mensagem, em lista numerada:

1. **Qual formulário.** Se ele não souber o nome exato, liste e ofereça as opções.
2. **Qual período.** Um mês, um intervalo, "tudo". "Tudo" num formulário grande custa mais chamadas:
   conte antes (passo 2) e mostre o custo.
3. **Filtros extras**, se fizerem sentido: origem (aplicativo, sistema com login, link público) e quem
   preencheu.
4. **Excel ou CSV** (ver a tabela abaixo). Se ele não tiver preferência, use Excel.

Não pergunte do formato: **o padrão é o da exportação do Coletum**, o cliente reconhece o arquivo. Só mude se
ele pedir (tabela "Pedido do cliente e ajustes").

### Excel ou CSV

| | Excel (`xlsx`) | CSV (`csv`) |
|---|---|---|
| O que sai | **um arquivo**: LEIA-ME, aba do formulário e uma aba por grupo repetível ou campo com várias respostas | **uma pasta**: um arquivo por tabela e `LEIA-ME.txt` |
| Bom para | abrir e ler; mandar a alguém; navegar pelos links entre abas | Power BI, R, Python, importar em outro sistema; volumes grandes |
| Cuidados | limite do Excel de cerca de 1 milhão de linhas por aba (a aba de fotos é a que cresce) | ponto e vírgula, vírgula decimal e UTF-8 com BOM: abre certo no Excel em português; para ferramenta que espera vírgula e ponto, use o ajuste de CSV |

## Passos

| # | Ferramenta do conector | Para quê | Chamadas |
|---|---|---|---|
| 1 | `listar_formularios` com `nome` (parte do nome) e `tamanho_pagina` 500 | achar o `id_formulario` | 1 |
| 2 | `contar_preenchimentos` com os filtros | saber o total e o custo (`chamadas_para_exportar_tudo` e `cota_para_exportar_tudo`) | 1 |
| 3 | decidir com o cliente, se o custo for alto | estreitar o período ou aceitar o custo | 0 |
| 4 | `exportar_preenchimentos` com `formato`, os mesmos filtros, `max_paginas` igual ou maior que `chamadas_para_exportar_tudo` e, se ele pediu, `ajustes` e `gerado_por` | gravar o arquivo | 1 por página de 500, mais 1 pela estrutura na 1ª vez |
| 5 | responder ao cliente | caminho, linhas por aba, se ficou completo | 0 |

Detalhes que importam:

- **Sempre contar antes.** O `contar_preenchimentos` custa 1 chamada e evita surpresa. Se
  `chamadas_para_exportar_tudo` passar de 5, avise o cliente do custo (chamadas e cota) antes de exportar.
- **`max_paginas`** é o freio: o padrão é 5 (até 2.500 preenchimentos). Se o total for maior e você não
  aumentar, a exportação para no limite, sai incompleta, avisa quantos ficaram de fora e o LEIA-ME diz
  "Exportação incompleta". Nunca entregue um arquivo incompleto sem dizer isso ao cliente.
- **`tamanho_pagina`** fica em 500 (o que gasta menos chamadas). Só reduza em formulário muito pesado
  (muitas fotos e grupos grandes), se a exportação der erro de tempo.
- **`gerado_por`**: o nome que aparece em "Exportação realizada por" no LEIA-ME. Sem ele, "Coletum via MCP".
- **Período:** `criado_depois_de` e `criado_antes_de` são exclusivos. Para um mês inteiro, use data e
  hora com fuso: depois do último segundo do mês anterior e antes da meia-noite do 1º dia do mês
  seguinte (por exemplo, setembro de 2026: depois de 2026-08-31T23:59:59-03:00 e antes de
  2026-10-01T00:00:00-03:00).
- **Os mais recentes:** a API devolve do mais recente para o mais antigo. "Os 200 últimos" = `tamanho_pagina`
  200 e `max_paginas` 1 (1 chamada; o aviso de incompleto é esperado, diga ao cliente que são os 200 últimos).
- **Editados:** `editado_depois_de` traz **só os editados** no período, não os novos. Para "tudo o que
  mudou desde tal dia", são duas exportações: uma por criação e outra por edição.
- **Origem:** `mobile` (aplicativo), `web_private` (sistema, com login) ou `web_public` (link público).
  Filtro inválido é recusado antes de chamar a API.

## Pedido do cliente e ajustes

O cliente fala; você traduz em `ajustes`. Ele nunca edita JSON. Sem pedido, não passe `ajustes`.

| O cliente diz | `ajustes` |
|---|---|
| "só esses campos, nessa ordem" | `{"campos": {"mostrar": ["Local", "Data", "Situação"]}}` |
| "tira as observações" | `{"campos": {"ocultar": ["Observações"]}}` |
| "tudo numa aba só, uma linha por resposta" | `{"aba_unica": "linhas"}` |
| "tudo numa aba só, cada resposta numa coluna" | `{"aba_unica": "colunas"}` |
| "quem criou e quando no começo" | `{"metadados": "inicio"}` |
| "sem as colunas de quem criou, datas e localização" | `{"metadados": "fora"}` |
| "chama a coluna X de Y" | `{"rotulos": {"X": "Y"}}` |
| "CSV com vírgula e ponto decimal" (padrão americano, algumas ferramentas) | `{"csv": {"separador": ",", "decimal": "."}}` |
| "quero a precisão e a altitude da coordenada" / "de onde veio (aplicativo, sistema, link)" | `{"extras": ["precisao", "altitude", "origem"]}` |

- Os ajustes se combinam num objeto só. `mostrar` e `ocultar` aceitam o rótulo do campo, a chave técnica ou o
  cabeçalho da coluna (`ocultar` também tira uma coluna de metadado, como "Atualizado por"). Um grupo na
  lista vale para os campos dele. Nome que não existe no formulário é recusado antes de ler os preenchimentos.
- **Aba única** tira as abas filhas e as colunas de código de relacionamento; fica o código do preenchimento.
  - **Linhas:** a linha do preenchimento se repete, uma por resposta, com os campos simples repetidos. Cada
    item de grupo repetível ocupa as suas linhas, um embaixo do outro. Dois campos com várias respostas no
    mesmo nível ficam lado a lado por posição (1ª resposta de cada na 1ª linha), nunca em combinação: o
    número de linhas é o do maior. Para contar preenchimentos, conte códigos distintos, não linhas.
  - **Colunas:** uma linha por preenchimento; cada resposta a mais vira coluna numerada ("Defect type 1",
    "Defect type 2"); item de grupo repetível leva o número no grupo ("Achados 2 > Tipo"). O número de
    colunas é o maior encontrado nos preenchimentos exportados.
  - Serve para formulário simples (campos simples, poucas múltiplas escolhas ou um grupo repetível sem nada
    repetível dentro); fora disso a ferramenta devolve `aviso_aba_unica`: diga ao cliente que o padrão com
    abas lê melhor.

## Como ler o arquivo (padrão do Coletum)

Em resumo:

| Aba ou arquivo | Uma linha por | O que tem |
|---|---|---|
| **LEIA-ME** | | formulário, quem exportou, data e hora, total de respostas, filtros usados |
| **aba do formulário** | preenchimento | `Código (formulário)`, os campos (grupo não repetível com prefixo "Grupo > Campo"), uma coluna com a **quantidade** de cada grupo repetível e campo com várias respostas, e os metadados no fim: local da coleta e da edição, criado e atualizado por, criado em, horário do dispositivo, atualizado em |
| **uma aba por grupo repetível ou campo com várias respostas** | item ou resposta | dois códigos (do dono e o próprio, `1.2.0`, `1.2.0.1`) e os campos do item; foto e arquivo com nome original, link e nome do arquivo |

- **Como ligar as abas:** pelos códigos. No Excel, clicar na quantidade leva à 1ª linha da aba filha, e o
  código da coluna A da aba filha volta à linha do pai.
- **Coordenada** vem em duas colunas, latitude e longitude. O "Local da coleta" é onde o aparelho estava; a
  de um campo de localização é o ponto que a pessoa marcou. São coisas diferentes. Toda coordenada sai com
  até 5 casas decimais, como na tela do Coletum.
- **Datas** são datas do Excel (ordenam e filtram), no fuso local, em dia/mês/ano.
- **Campo vazio** pode ser "não respondido" ou "escondido por regra do formulário"; a planilha não
  distingue.

## Custo

| Etapa | Chamadas à API | Tokens na conversa |
|---|---|---|
| Achar o formulário | 1 | 2 a 7 mil |
| Contar | 1 | menos de 200 |
| Exportar | 1 por página de 500, mais 1 pela estrutura | 300 a 600 (só caminho e contagens) |
| **Um mês de um formulário típico** | **3 a 4** | **cerca de 3 a 8 mil** |

O tamanho do formulário não pesa na conversa, só no disco e no tempo: um mês de um formulário pesado
passou de 1,6 MB na API e continua custando só a resposta curta da ferramenta.

## O que dizer ao cliente

- **No fim, o caminho:** sempre mostre ao usuário o caminho completo de cada arquivo, como vem no começo da resposta da ferramenta (e em `mostrar_ao_usuario`), em bloco de código, para ele copiar, sem esperar que ele peça; se ele pedir para abrir, use `mostrar_arquivo`. Nunca diga só que gravou na pasta do projeto.
- Onde está o arquivo, quantas linhas tem cada aba e **se ficou completo**. Se não ficou, quantos
  preenchimentos faltaram e quanto custaria trazer o resto.
- Os links baixam a foto direto, mas baixar muitas gera tráfego.

## Cuidados

- **Só pelas ferramentas do conector.** Use sempre as ferramentas do conector; nunca escreva script ou comando que chame a API do Coletum por fora (curl, Python, R). O token não fica disponível para a IA, e o conector protege a cota da conta (intervalo entre chamadas e teto por hora).
- **Cota.** Hoje, enquanto a API v1 existir, cada chamada à API v2 consome 0,2 da cota mensal da conta (5 chamadas = 1 unidade); a regra pode mudar quando a v1 sair. Erro não conta. Toda ferramenta devolve `chamadas_api` e `cota_consumida`, calculada com o peso atual.
- Não abra a planilha para "resumir" lendo tudo na conversa: um mês de formulário pesado não cabe no
  contexto. Para olhar alguns, use `buscar_preenchimentos` com poucos por página.
- O conector **só lê** a API e **só grava** na pasta de saída (`pasta_saida` ou a padrão dele).
