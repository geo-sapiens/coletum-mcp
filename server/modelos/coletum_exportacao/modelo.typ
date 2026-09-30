// Modelo embutido "coletum_exportacao": replica o PDF da exportação do Coletum (motor Typst do produto).
// Só estrutura: nenhum dado de conta mora aqui; tudo vem do dados.json (contrato versão 1).
// Página, cabeçalho, cores e aparência pedida (documento.aparencia) vêm de /coletum_estilo.typ.
#import "/coletum.typ": *
#import "/coletum_estilo.typ": *

#show: estilo_coletum

#let rotulo(c, acima: 17.15pt) = {
  block(above: acima, below: 7.15pt * s, sticky: true, {
    text(weight: "bold", fill: cor_rotulo, c.rotulo)
    h(4pt * s)
    box(width: 1fr, line(length: 100%, stroke: 0.4pt + cor_linha))
  })
  if c.ajuda != none {
    block(above: 4pt * s, below: 4pt * s, sticky: true, text(size: 8pt * s, style: "italic", fill: cor_ajuda, c.ajuda))
  }
}

// Campos em ordem; grupo vira bloco com barra à esquerda (recursivo: grupo dentro de grupo).
#let campos(lista, primeiro_acima: 17.15pt) = {
  for (i, c) in lista.enumerate() {
    if c.classe == "grupo" {
      let conteudo = {
        block(above: 0pt, below: 0pt, text(size: 11pt * s, weight: "bold", fill: cor_grupo, c.rotulo))
        if c.repetivel and c.itens.len() == 0 { block(above: 6pt * s, vazio) }
        for (n, item) in c.itens.enumerate() {
          campos(item.campos, primeiro_acima: if n == 0 { 13.15pt * s } else { 17.15pt * s })
          if c.repetivel and n + 1 < c.itens.len() {
            block(above: 12pt * s, below: 12pt * s, line(length: 100%, stroke: 0.4pt + cor_linha))
          }
        }
      }
      block(above: 19pt * s, below: 6pt * s, inset: (left: 5mm, top: 2pt * s, bottom: 4pt * s),
        stroke: (left: 1pt + cor_barra), breakable: true, width: 100%, conteudo)
    } else {
      rotulo(c, acima: if i == 0 { primeiro_acima } else { 17.15pt * s })
      block(above: 7.15pt * s, below: 0pt, if c.classe == "anexo" { bloco_anexos(c) } else { valor_simples(c) })
    }
  }
}

#for (i, p) in dados.preenchimentos.enumerate() {
  if i > 0 { pagebreak() }
  inicio_preenchimento(p)
  cabecalho(p)
  campos(p.campos, primeiro_acima: 13.15pt * s)
}
