---
name: migrar-v1
description: Converte código que chama a API V1 do Coletum (GraphQL em /api/graphql, desligada em 01/11/2026) para a V2 (REST em /api/webservice/v2), mantendo o mesmo resultado para o código que consome os dados. Use quando o usuário colar ou apontar um script, consulta do Power BI, código R, Python, JavaScript ou URL que chama /api/graphql.
---

# Migrar da API V1 para a V2 do Coletum

A V1 (GraphQL) sai do ar em **01/11/2026**. A V2 (REST) faz a mesma leitura com outro formato. O objetivo é que o
código do usuário continue entregando **exatamente o mesmo resultado** depois da troca.

## Como trabalhar

1. **Ache cada chamada à V1:** URL com `/api/graphql`, parâmetro `query=` (GET) ou corpo com `query` (POST). Liste,
   para cada uma, a raiz (`form`, `form_structure` ou `answer`), o `formId`, os filtros e os campos pedidos.
2. **Descubra as chaves da V2 pela estrutura, nunca por adivinhação:** `estrutura_formulario` (ou `GET /forms/{id}`).
   A chave de um campo na V1 é o rótulo em camelCase mais o id (`nomeCompleto123`); na V2, o rótulo em
   snake_case mais o **mesmo id** (`nome_completo123`). Case pelo **id numérico**, que não muda. **A chave da V1 não se
   recupera a partir da chave da V2** (a V2 perde a diferença entre espaço, hífen e símbolo: "A – CPF" vira `a___cpf`):
   se o código traz as chaves fixas, use-as (tabela por id); se elas vêm da estrutura em tempo de execução, **monte a
   chave da V1 a partir do rótulo** (`label`) mais o id, do jeito que a V1 monta.
3. **Troque a chamada e ponha um adaptador na fronteira:** a função que buscava os dados passa a chamar a V2 e devolve
   os dados **no formato que a V1 devolvia**. O resto do código não muda. Mudança mínima, revisão fácil.
4. **Compare:** rode a versão antiga e a nova sobre os mesmos dados e confira que a saída é a mesma. Se não der para
   rodar as duas, diga o que não foi conferido.
5. **Leia os arquivos inteiros, inclusive código morto.** Token escrito no código é comum em integração antiga: se
   achar, não o copie para lugar nenhum e recomende revogar e gerar outro (ele continua no histórico do git).
6. **Se achar defeito no código antigo, preserve o comportamento e aponte à parte.** Corrigir junto muda o resultado e
   esconde se a migração está certa. Proponha a correção como passo separado.

## Quando o código usa uma biblioteca cliente (ex.: pacote R `RColetum`)

- O que o código consome é o formato **da biblioteca**, não o JSON da API: no `RColetum` 0.2.x, um data.frame principal
  mais data.frames filhos para cada campo multivalorado, com ids sequenciais e a coluna do pai. Compare os
  **data.frames** (ou o arquivo final), não só o JSON.
- Duas saídas: atualizar a biblioteca (o `RColetum` 1.1.0, no CRAN, já fala com a V2; ajuste o processamento ao formato
  novo) ou trocar as chamadas por HTTP direto à V2 com um adaptador que devolve o formato antigo da biblioteca.
- **A biblioteca tem o endereço da produção fixo** (`RColetum` 0.2.2 e 1.1.0). Para testar fora da produção,
  redirecione a função de requisição dela antes de qualquer chamada.

## Chamadas

| V1 | V2 |
|---|---|
| `GET {base}/api/graphql?query=...&token=...` | `GET {base}/api/webservice/v2/...` com cabeçalho `Token: <token>` (não ponha o token na URL nem no código) |
| `{form{...}}` | `GET /forms` (filtros `name`, `status`) |
| `{form_structure(formId:N){...}}` | `GET /forms/N` |
| `{answer(formId:N){...}}` | `GET /forms/N/answers` |

Acrescente `source=<nome-da-integracao>` na URL da V2 para identificar o uso.

## Paginação e ordem

- A V1 devolve **tudo de uma vez** quando não há `limit`; com `limit`/`offset` pagina sem ordem definida.
- A V2 pagina sempre: `page` (a partir de 1) e `page_size` (máximo 500). Leia `pagination.has_next` e repita até
  `false`. Padrão: mais recente primeiro (`sort=-created_at`; `sort=created_at` inverte).
- **Se o código depende da ordem** (ordena com empate, pega o primeiro, compara listas), confira a ordem na comparação:
  a V1 não garante ordem e a V2 vem da mais recente para a mais antiga.
- Substitua "uma chamada que traz tudo" por um laço de páginas de 500. Cada página consome 0,2 da cota mensal, e a
  conta tem limite de 300 chamadas por minuto (resposta 429 com `Retry-After`: espere e tente de novo; não recomece o
  laço do zero).

## Filtros de `answer`

| V1 | V2 | Atenção |
|---|---|---|
| `createdAfter`, `createdBefore` | `created_after`, `created_before` | data **só com dia**: a V1 entende o **fim** do dia (`T23:59:59+00:00`), a V2 o **início**. Para manter o resultado, passe data e hora explícitas |
| `updatedAfter`, `updatedBefore` | `updated_after`, `updated_before` | só traz os editados nas duas |
| `createdAtSource` ou `source` | `created_at_source` | valores `mobile`, `web_private`, `web_public` |
| `limit`, `offset` | `page`, `page_size` | ver paginação |
| `createdDeviceAfter/Before`, `deletedAfter/Before`, `componentId` | **não existem** | não invente; avise o usuário |

## Campos de `metaData`

A V2 devolve o preenchimento inteiro (não há seleção de campos): filtre as colunas no adaptador.

| V1 (`metaData`) | V2 |
|---|---|
| `friendlyId` | `id` (no **topo** do item, fora de `meta_data`) |
| `userId`, `userName` | `meta_data.created_by_user_id`, `meta_data.created_by_user_name` |
| `createdAtSource` | `meta_data.created_at_source` |
| `createdAt`, `createdAtDevice`, `updatedAt` | `meta_data.created_at`, `meta_data.created_at_device`, `meta_data.updated_at` |
| `createdAtCoordinates`, `updatedAtCoordinates` | `meta_data.created_at_coordinates`, `meta_data.updated_at_coordinates` |
| `deletedAt` | **não existe** (a V2 não lista excluídos) |

## Formatos de valor

| Tipo | V1 | V2 | Para devolver como a V1 |
|---|---|---|---|
| data e hora do metadado | `2026-03-10T12:00:00+00:00` (UTC) | `2026-03-10T09:00:00-0300` (fuso sem dois-pontos) | mesmo instante. Para o **mesmo texto**: UTC, sem milissegundos, com `+00:00` (em JavaScript, `new Date(v).toISOString().replace('.000Z', '+00:00')`) |
| campo **data** | `2026-03-10` | `2026-03-10T00:00:00-03:00` | use os **10 primeiros caracteres** (`null` continua `null`). Ler o valor da V2 como data e hora desloca 3 horas e pode mudar o dia |
| coordenada | `{longitude, latitude}` | GeoJSON `{coordinates: [lng, lat], type, properties}` | `{longitude: c[0], latitude: c[1]}` |
| coordenada vazia | `{longitude: null, latitude: null}` | `null` | devolva o objeto com `null` |
| relacional | `{answerIdFromAnotherForm, answerFromAnotherForm}` | `{answer_id, label}` | renomeie |
| dinheiro | `{currency, value}` | como está no banco | confira com um preenchimento real |
| foto, galeria, arquivo, assinatura | link | link | igual |

## Estrutura do formulário (`form_structure` da V1 contra `GET /forms/{id}` da V2)

- `componentId` também muda de camelCase para snake_case, como nas respostas (mesma regra: monte a da V1 pelo rótulo).
- `type`: a V1 usa o nome do tipo com `field` no fim (`datefield`, `textareafield`, `checkboxfield`, `rangefield`); a V2,
  sem (`date`, `textarea`, `checkbox`, `range`). **Exceção:** `int` na V2 é `integerfield` na V1.
- **Multivalorado:** é o componente com `maximum` nulo ou diferente de 1 na estrutura. Vale para checkbox, grupo
  repetível **e campo de texto com várias respostas**.
- A V2 não traz `order` e traz propriedades a mais (`range_min`, `step`, `unit`). O `order` da V1 tem lacunas (itens
  excluídos), então a posição na lista não o reproduz; só importa se o código usa `order`.
- Componentes aninhados (grupos) e os demais tipos: confira com a estrutura real antes de afirmar.

## Erros da V2 (o código antigo costuma decidir pelo texto do erro)

401 token inválido · 404 "Entity not found" (formulário inexistente **ou** de outra conta, sem distinguir) · 429 cota
mensal esgotada ou limite por minuto (com `Retry-After`) · 423 conta com pagamento pendente. Se o código antigo testa textos da V1 ("Error 403", "Form not found"), traduza no adaptador e diga o que
não foi conferido.

## Antes de entregar

- Rodou a antiga e a nova e a saída bateu? Diga quantos registros e o que foi comparado.
- Token fora do código (variável de ambiente ou `.env`).
- Liste o que não tem equivalente na V2 e o que o usuário precisa decidir.
