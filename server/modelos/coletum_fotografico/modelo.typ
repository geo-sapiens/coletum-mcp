// Modelo embutido "coletum_fotografico": relatório fotográfico com o cabeçalho do Coletum.
// Para cada preenchimento: cabeçalho, todos os campos que não são foto em letra pequena (resumo) e as fotos
// grandes em grade (2 por linha por padrão), cada uma com legenda: campo, item e data. Assinaturas no fim.
// Regra do resumo, por estrutura e não por palpite (a API não marca quais campos importam): todos os campos do
// 1º nível e dos grupos não repetíveis, em letra pequena; grupo repetível vira uma linha com a quantidade de itens,
// porque os dados de dezenas de itens empurrariam as fotos para longe (o número do item está na legenda de cada
// foto, e o PDF padrão traz tudo). Quem quer menos usa campos.ocultar. Só estrutura: tudo vem do dados.json.
#import "/coletum.typ": *
#import "/coletum_estilo.typ": *

#show: estilo_coletum

#let tam_resumo = 8pt * s

// "Rótulo: valor" de um campo simples.
#let par_resumo(c) = [#text(weight: "bold", fill: cor_rotulo, c.rotulo): #if c.vazio { vazio } else if c.classe == "estrela" { estrelas(c, tamanho: 1.2em) } else if c.classe == "relacional" and c.at("relacionado", default: none) != none [#c.relacionado.id - #c.relacionado.rotulo] else { c.valor_formatado }]

// Campos de um item de grupo numa linha só, separados por ponto e vírgula (subgrupo entre parênteses).
#let linha_item(lista) = {
  let partes = ()
  for c in lista {
    if c.classe == "anexo" { continue }
    if c.classe == "grupo" {
      for it in c.itens {
        let dentro = linha_item(it.campos)
        if dentro != none { partes.push([#text(weight: "bold", c.rotulo) (#dentro)]) }
      }
    } else { partes.push(par_resumo(c)) }
  }
  if partes.len() == 0 { none } else { partes.join([; ]) }
}

// Resumo dos campos que não são foto, em letra pequena: campos simples em duas colunas equilibradas (o columns
// do Typst enche a 1ª antes de passar à 2ª), grupo não repetível na largura toda, abaixo, e grupo repetível só
// com a quantidade de itens.
#let resumo(lista) = {
  let simples = ()
  let grupos = ()
  for c in lista {
    if c.classe == "anexo" { continue }
    if c.classe == "grupo" and c.repetivel {
      let n = c.itens.len()
      simples.push(block(above: 3pt * s, below: 0pt,
        [#text(weight: "bold", fill: cor_grupo, c.rotulo): #if n == 0 { vazio } else [#n #if n == 1 [item] else [itens]]]))
      continue
    }
    if c.classe == "grupo" {
      let linhas = ()
      for it in c.itens {
        let l = linha_item(it.campos)
        if l != none { linhas.push(if c.repetivel [#it.numero. #l] else { l }) }
      }
      if linhas.len() == 0 and c.repetivel { linhas.push(vazio) }
      if linhas.len() > 0 {
        grupos.push(block(above: 6pt * s, below: 2pt * s, breakable: true, {
          text(weight: "bold", fill: cor_grupo, c.rotulo)
          for l in linhas { block(above: 2.5pt * s, below: 0pt, l) }
        }))
      }
    } else {
      simples.push(block(above: 3pt * s, below: 0pt, par_resumo(c)))
    }
  }
  if simples.len() == 0 and grupos.len() == 0 { return }
  block(above: 8pt * s, below: 8pt * s, {
    set text(size: tam_resumo)
    set par(leading: 0.35em)
    if simples.len() > 0 {
      let meio = calc.ceil(simples.len() / 2)
      grid(columns: (1fr, 1fr), column-gutter: 6mm, simples.slice(0, meio).join(), simples.slice(meio).join())
    }
    grupos.join()
  })
}

#let legenda(a, p) = {
  set text(size: 7.5pt * s, fill: cor_rodape)
  set par(leading: 0.3em)
  block(above: 2pt * s, below: 0pt, [#a.legenda #h(1fr) #p.metadados.criado_em])
}

#let galeria(p) = {
  let todos = anexos(p)
  let fotos_do_p = todos.filter(a => lower(str(a.tipo_campo)) != "signature")
  let assinaturas = todos.filter(a => lower(str(a.tipo_campo)) == "signature")
  let n = ajuste("fotos", "por_linha", 2)
  let espaco = 4mm
  let w = (largura_util - espaco * (n - 1)) / n
  let h = w * 0.75
  block(above: 10pt * s, below: 6pt * s, sticky: true,
    text(size: 11pt * s, weight: "bold", fill: cor_grupo)[Fotos (#fotos_do_p.len())])
  if fotos_do_p.len() == 0 {
    block(vazio)
  } else {
    grid(columns: (w,) * n, column-gutter: espaco, row-gutter: 5mm,
      ..fotos_do_p.map(a => block(breakable: false, {
        box(fill: rgb("#F4F5F7"), foto(a, width: w, height: h, fit: "contain"))
        legenda(a, p)
      })))
  }
  if assinaturas.len() > 0 {
    block(above: 10pt * s, below: 6pt * s, sticky: true,
      text(size: 11pt * s, weight: "bold", fill: cor_grupo)[Assinatura])
    grid(columns: (50mm,) * 3, column-gutter: 3mm, row-gutter: 4mm,
      ..assinaturas.map(a => block(breakable: false, {
        foto(a, width: 50mm, height: 25mm, fit: "contain")
        legenda(a, p)
      })))
  }
}

#for (i, p) in dados.preenchimentos.enumerate() {
  if i > 0 { pagebreak() }
  inicio_preenchimento(p)
  cabecalho(p)
  resumo(p.campos)
  galeria(p)
}
