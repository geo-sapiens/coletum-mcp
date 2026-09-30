// Modelo embutido "coletum_colunas": o PDF do Coletum em colunas, pergunta à esquerda e resposta à direita.
// Mesmo cabeçalho, fonte e cores da exportação (/coletum_estilo.typ); campos em tabela, mais compacto.
// Grupo vira bloco com barra à esquerda; grupo repetível com poucos campos simples vira uma tabela, uma
// linha por item. Só estrutura: tudo vem do dados.json (contrato versão 1).
#import "/coletum.typ": *
#import "/coletum_estilo.typ": *

#show: estilo_coletum

// Até quantos campos um grupo repetível vira tabela (uma coluna por campo).
#let max_colunas_tabela = if paisagem { 8 } else { 5 }

#let celula_rotulo(c) = {
  text(weight: "bold", fill: cor_rotulo, c.rotulo)
  if c.ajuda != none { linebreak(); text(size: 7.5pt * s, style: "italic", fill: cor_ajuda, c.ajuda) }
}

#let celula_valor(c) = {
  if c.classe == "anexo" {
    layout(tam => bloco_anexos(c, largura: tam.width, por_linha: ajuste("fotos", "por_linha", 3)))
  } else { valor_simples(c) }
}

// Campos simples seguidos viram uma tabela de duas colunas.
#let tabela(lista) = {
  if lista.len() == 0 { return }
  block(above: 6pt * s, below: 6pt * s, table(
    columns: (34%, 66%),
    stroke: 0.4pt + cor_linha,
    inset: (x: 5pt * s, y: 4pt * s),
    fill: (x, _) => if x == 0 { cor_fundo_rotulo },
    ..lista.map(c => (celula_rotulo(c), celula_valor(c))).flatten(),
  ))
}

#let simples(c) = c.classe != "grupo" and c.classe != "anexo"

#let campos(lista) = {
  let fila = ()
  for c in lista {
    if c.classe != "grupo" { fila.push(c); continue }
    tabela(fila)
    fila = ()
    let conteudo = {
      block(above: 0pt, below: 4pt * s, text(size: 11pt * s, weight: "bold", fill: cor_grupo, c.rotulo))
      if c.repetivel and c.itens.len() == 0 { block(above: 4pt * s, vazio) }
      let subs = if c.itens.len() > 0 { c.itens.first().campos } else { () }
      let em_tabela = (c.repetivel and c.itens.len() > 0 and subs.len() > 0
        and subs.len() <= max_colunas_tabela and c.itens.all(it => it.campos.all(simples)))
      if em_tabela {
        let rotulos = subs.map(x => x.rotulo)
        table(
          columns: (auto,) + (1fr,) * rotulos.len(),
          stroke: 0.4pt + cor_linha,
          inset: (x: 4pt * s, y: 3.5pt * s),
          fill: (_, y) => if y == 0 { cor_fundo_rotulo },
          table.header(text(weight: "bold", fill: cor_rotulo)[Item],
            ..rotulos.map(r => text(weight: "bold", fill: cor_rotulo, r))),
          ..c.itens.map(it => {
            let linha = (str(it.numero),)
            for r in rotulos {
              let x = it.campos.find(y => y.rotulo == r)
              linha.push(if x == none { vazio } else { valor_simples(x) })
            }
            linha
          }).flatten(),
        )
      } else {
        for (n, item) in c.itens.enumerate() {
          if c.repetivel {
            block(above: 6pt * s, below: 2pt * s, sticky: true,
              text(size: 9pt * s, weight: "bold", fill: cor_rotulo)[Item #item.numero de #c.itens.len()])
          }
          campos(item.campos)
        }
      }
    }
    block(above: 12pt * s, below: 6pt * s, inset: (left: 4mm, top: 2pt * s, bottom: 3pt * s),
      stroke: (left: 1pt + cor_barra), breakable: true, width: 100%, conteudo)
  }
  tabela(fila)
}

#for (i, p) in dados.preenchimentos.enumerate() {
  if i > 0 { pagebreak() }
  inicio_preenchimento(p)
  cabecalho(p)
  set text(size: 9pt * s)
  campos(p.campos)
}
