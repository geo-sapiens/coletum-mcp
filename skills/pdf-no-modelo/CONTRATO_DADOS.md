# Contrato de dados dos modelos de PDF (versão 1)

O que o template Typst recebe em `/dados.json` quando o conector roda `gerar_pdf_modelo`. É estável: um
template escrito contra esta versão continua funcionando. Mudança que quebre template vira versão 2
(`documento.versao_contrato`).

## Como o template lê

```typst
#import "/coletum.typ": *        // dados, campo, valor, mapeado, valor_mapeado, anexos, fotos, foto, ajuste
#for p in dados.preenchimentos [ ... ]
```

A pasta do trabalho é a raiz: `/dados.json`, `/coletum.typ`, `/coletum_estilo.typ` (o visual da
exportação, que os modelos embutidos usam: `#import "/coletum_estilo.typ": *` e `#show: estilo_coletum`),
`/fotos/...` (anexos baixados) e
`/arquivos/...` (logo e arquivos do modelo). O template não lê nada fora dela e não importa pacotes
(`@preview/...` é recusado). Com `modo` `um_por_preenchimento`, cada compilação recebe um
`dados.json` com um preenchimento só.

## Estrutura

| Caminho | O que é |
|---|---|
| `documento.versao_contrato` | `1` |
| `documento.gerado_em` / `gerado_em_iso` | `27/09/2026 14:03` e ISO com fuso |
| `documento.gerado_por` | `Coletum via MCP` |
| `documento.fuso` | fuso das datas (`COLETUM_FUSO`, padrão `America/Sao_Paulo`) |
| `documento.empresa` | texto de `empresa` na chamada (ou `ajustes.empresa.nome`), ou `none`: a API não traz o nome da conta |
| `documento.logo` | `/arquivos/logo.png` (ou .jpg, .svg) quando há logo, ou `none` |
| `documento.variaveis` | textos livres: os do modelo salvo, trocados pelos da chamada |
| `documento.aparencia` | ajustes de aparência pedidos (ver "Aparência"); `{}` quando nada foi pedido |
| `documento.qtd_preenchimentos` | quantos preenchimentos neste arquivo |
| `formulario.id`, `.nome`, `.versao`, `.categoria` | do formulário |
| `preenchimentos[]` | um por preenchimento, na ordem pedida |

### Cada preenchimento

| Caminho | O que é |
|---|---|
| `id` | `1024.3` |
| `metadados.criado_por.id` / `.nome` | autor |
| `metadados.criado_em` / `criado_em_iso` | recebimento no servidor, `dd/mm/aaaa hh:mm` e ISO |
| `metadados.horario_dispositivo` / `_iso` | horário do aparelho no preenchimento |
| `metadados.plataforma` / `plataforma_texto` | `mobile`, `web_private`, `web_public` e `Aplicativo`, `Sistema web`, `Link público` |
| `metadados.coordenada` | onde o aparelho estava: `lat`, `long`, `precisao_m`, `altitude_m`, `texto`; ou `none` |
| `metadados.edicao` | `none` ou `por` (id, nome), `em`, `em_iso`, `plataforma`, `plataforma_texto` |
| `metadados.tamanho_anexos_bytes` | soma dos anexos |
| `campos[]` | campos do 1º nível, na ordem da estrutura |
| `indice` | chave técnica ou rótulo para a posição em `campos` (use `campo(p, "KM")`) |
| `mapeados` | rótulo do modelo do cliente para o campo (ver "Mapeamento") |
| `anexos_todos[]` | todos os anexos, em ordem, com `campo`, `chave_campo`, `tipo_campo`, `id_item` |

### Cada campo

| Chave | O que é |
|---|---|
| `chave`, `rotulo`, `tipo` | chave técnica, rótulo legível, tipo da API (`text`, `float`, `select`, `coordinate`, `gallery`, `signature`...) |
| `classe` | `texto`, `numero`, `estrela`, `data`, `hora`, `booleano`, `escolha`, `coordenada`, `relacional`, `anexo`, `grupo` (`estrela` = campo `rating`: `valor` é a nota de 1 a 5, sempre de 5 estrelas; os modelos do Coletum desenham as estrelas, `valor_formatado` traz o número) |
| `ajuda` | texto de ajuda do campo, ou `none` |
| `multiplo` | aceita mais de um valor |
| `vazio` | sem resposta (o template decide o que mostrar; o da exportação põe "Não informado") |
| `valor` | valor bruto da API; na coordenada, com lat e long já em até 5 casas decimais, como a tela do Coletum |
| `valor_formatado` | texto pronto: data `dd/mm/aaaa`, número com vírgula, `Sim`/`Não`, escolhas separadas por vírgula, coordenada `Latitude: -15,79422 / Longitude: -47,88281`, anexo `2 arquivos`; `none` se vazio |
| `valores` | só em campo múltiplo: a lista já formatada (para listar com marcador) |
| `coordenada` | só em coordenada: `lat`, `long`, `texto` (até 5 casas decimais, sem zeros à direita, como toda coordenada do contrato) |
| `relacionado` | só em relacional: `id` e `rotulo` do preenchimento ligado |
| `anexos[]` | só em anexo: `arquivo` (`/fotos/<nome>` ou `none`), `nome` legível, `situacao` (`baixado` ou `indisponível: <motivo>`; `simulada` só em teste com `COLETUM_FOTOS_TESTE`), `imagem`, `largura_px`, `altura_px`, `legenda` |
| `repetivel`, `itens[]`, `qtd_itens` | só em grupo. Grupo não repetível tem 1 item. Cada item: `id_item`, o código da planilha, a partir de 0 (`1024.3.0` é o 1º item; `none` em grupo não repetível), `numero` (ordem de leitura, 1 = o primeiro), `campos[]`, `indice` |

Os anexos já estão baixados e reduzidos (até 1.600 px; PNG quando têm transparência, como assinatura).
Falha de download deixa `arquivo` nulo e o motivo em `situacao`; `foto(a)` desenha o quadro "Foto
indisponível". O link original não vai para o contrato.

## Aparência

Os ajustes pedidos na conversa chegam em `documento.aparencia`, só com as chaves pedidas e já validadas: o que
falta é o padrão de cada modelo. Vêm de `ajustes` em `gerar_pdf_preenchimento`, de `aparencia` em
`gerar_pdf_modelo` e do `aparencia` do `modelo.json` (a chamada vale por cima, grupo a grupo). Nome da empresa e
logo continuam em `documento.empresa` e `documento.logo`. Adicionar a chave não quebra template: quem não a lê
sai como antes.

| Chave | Valores | Quem aplica |
|---|---|---|
| `campos.ocultar` | rótulos ou chaves, em qualquer nível | o conector, antes do template: o campo some de `campos`, `indice` e `anexos_todos` |
| `campos.ordem` | rótulos ou chaves; os citados vêm primeiro, em cada nível | o conector, antes do template |
| `campos.mostrar_vazios` | `false` tira os campos sem resposta (padrão: aparecem como "Não informado") | o conector, antes do template |
| `fotos.por_linha` | 1 a 4 | o template (`ajuste("fotos", "por_linha", 3)`) |
| `fonte.tamanho` | 6 a 16 pt, o corpo do texto; o resto cresce na mesma proporção | o template |
| `cores.destaque` | `#RRGGBB`: títulos de grupo e barras (padrão, o azul da exportação) | o template |
| `pagina.orientacao` | `retrato` ou `paisagem` | o template |

No template: `ajuste("fotos", "por_linha", 3)` devolve o pedido ou o padrão. Nome pedido em `ocultar` ou
`ordem` que não existe no formulário volta na resposta em `aparencia_sem_campo`.

## Mapeamento

No `modelo.json` (ou em `mapeamento` na chamada), cada rótulo do modelo do cliente aponta para um campo:

| Forma | Exemplo |
|---|---|
| chave ou rótulo | `"Obra": "RODOVIA"` |
| campo dentro de grupo (1º item) | `"Km": "CADASTRO/KM"` |
| item escolhido (pela ordem, 1 = o primeiro) | `"Km do 2º ponto": "CADASTRO[2]/KM"` |
| metadado | `"Responsável": "meta:criado_por"` (`id`, `criado_por`, `criado_em`, `horario_dispositivo`, `plataforma`, `coordenada`, `editado_por`, `editado_em`) |
| alternativas | `"Coordenadas": ["Localização", "CADASTRO/LOCALIZAÇÃO"]` (vale a primeira preenchida) |
| sem campo | `"Equipe": ""` (sai vazio e o conector avisa) |

No template: `valor_mapeado(p, "Obra")` (texto ou "Não informado") ou `mapeado(p, "Obra")` (o campo inteiro).

## Exemplo (inventado)

```json
{
  "documento": {"versao_contrato": 1, "gerado_em": "27/09/2026 14:03", "gerado_por": "Coletum via MCP",
                "fuso": "America/Sao_Paulo", "empresa": "Empresa Exemplo", "logo": "/arquivos/logo.png",
                "variaveis": {"obra": "Obra Exemplo"}, "aparencia": {"fotos": {"por_linha": 2}},
                "qtd_preenchimentos": 1},
  "formulario": {"id": 900001, "nome": "Inspeção de Rede Exemplo", "versao": "1.0", "categoria": "Exemplo"},
  "preenchimentos": [{
    "id": "7001.42",
    "metadados": {"criado_por": {"id": 1, "nome": "Usuário Exemplo"}, "criado_em": "23/09/2026 08:52",
                  "horario_dispositivo": "23/09/2026 08:51", "plataforma": "web_private",
                  "plataforma_texto": "Sistema web", "coordenada": null, "edicao": null},
    "campos": [
      {"chave": "tipo3", "rotulo": "Tipo de inspeção", "tipo": "select", "classe": "escolha", "ajuda": null,
       "multiplo": false, "vazio": false, "valor": "Recebimento", "valor_formatado": "Recebimento"},
      {"chave": "pontos4", "rotulo": "Pontos inspecionados", "tipo": "group", "classe": "grupo", "repetivel": true,
       "qtd_itens": 1, "vazio": false, "valor": null, "valor_formatado": null,
       "itens": [{"id_item": "7001.42.0", "numero": 1, "indice": {"local6": 0, "Localização": 0}, "campos": [
         {"chave": "local6", "rotulo": "Localização", "tipo": "coordinate", "classe": "coordenada", "vazio": false,
          "valor": {"coordinates": [-47.88281, -15.79422]},
          "valor_formatado": "Latitude: -15,79422 / Longitude: -47,88281",
          "coordenada": {"lat": -15.79422, "long": -47.88281, "texto": "Latitude: -15,79422 / Longitude: -47,88281"}}]}]}
    ],
    "indice": {"tipo3": 0, "Tipo de inspeção": 0, "pontos4": 1, "Pontos inspecionados": 1},
    "mapeados": {"Obra": {"chave": null, "rotulo": "Obra", "classe": "sem_campo", "vazio": true, "valor_formatado": null}},
    "anexos_todos": []
  }]
}
```

Para ver os dados reais de um formulário, gere um PDF: o `dados.json` fica na pasta do trabalho que a ferramenta informa.
