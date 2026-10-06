// coletum_estilo.typ: o visual do PDF da exportação do Coletum, comum aos modelos embutidos
// (coletum_exportacao, coletum_colunas, coletum_fotografico). O conector copia para a pasta do trabalho.
// No template:
//   #import "/coletum_estilo.typ": *
//   #show: estilo_coletum
// Lê a aparência pedida na conversa (documento.aparencia, ver CONTRATO_DADOS.md). Sem aparência, sai
// exatamente o visual da exportação.
#import "/coletum.typ": *

#let doc = dados.documento
#let form = dados.formulario

// ---- aparência --------------------------------------------------------------------------------
// Escala do texto: fonte.tamanho é o tamanho do corpo (10 pt na exportação); o resto cresce junto.
#let s = ajuste("fonte", "tamanho", 10) / 10
#let paisagem = ajuste("pagina", "orientacao", "retrato") == "paisagem"
// Largura útil da página (margens de 25 mm dos dois lados).
#let largura_util = if paisagem { 297mm - 50mm } else { 210mm - 50mm }

#let _destaque = ajuste("cores", "destaque", none)
#let cor_rotulo = rgb("#3C556E")
#let cor_linha = rgb("#D2D7DE")
#let cor_grupo = if _destaque == none { rgb("#0064B4") } else { rgb(_destaque) }
#let cor_barra = if _destaque == none { rgb("#6496D2") } else { rgb(_destaque).lighten(40%) }
#let cor_fundo_rotulo = if _destaque == none { rgb("#EEF2F7") } else { rgb(_destaque).lighten(92%) }
#let cor_vazio = rgb("#969696")
#let cor_rodape = rgb("#646464")
#let cor_ajuda = rgb("#828C96")
#let cor_id = rgb("#646464")
// Noto Sans, como o produto; vem com o conector (modelos/_fontes). Glifo que ela não tem (★) cai nas fontes do
// próprio Typst, como no produto: por isso a lista não tem reserva do sistema.
#let fontes = ("Noto Sans",)

#let vazio = text(style: "italic", fill: cor_vazio, nao_informado)

// Marca o começo de um preenchimento: numeração da página volta a 1 e o cabeçalho das páginas seguintes
// mostra o id dele.
#let inicio_preenchimento(p) = {
  counter(page).update(1)
  [#metadata(p.id) <preenchimento_inicio>]
}

// ---- página ------------------------------------------------------------------------------------
#let estilo_coletum(corpo) = {
  set document(title: form.nome, author: doc.gerado_por)
  set text(font: fontes, size: 10pt * s, lang: "pt", region: "BR", fill: black)
  set par(leading: 0.42em, spacing: 0.42em)
  set page(
    paper: "a4",
    flipped: paisagem,
    margin: (left: 25mm, right: 25mm, top: 22mm, bottom: 22mm),
    header-ascent: 30%,
    footer-descent: 12.8pt * s,
    header: context {
      let inicios = query(<preenchimento_inicio>)
      let aqui = here().page()
      if inicios.any(m => m.location().page() == aqui) { return }
      let anteriores = inicios.filter(m => m.location().page() < aqui)
      if anteriores.len() == 0 { return }
      let pid = anteriores.last().value
      set text(size: 9pt * s, fill: cor_rodape)
      stack(spacing: 5.85pt * s,
        grid(columns: (1fr, auto), form.nome, [Preenchimento #text(font: "DejaVu Sans Mono", size: 7.2pt * s, pid)]),
        line(length: 100%, stroke: 0.4pt + cor_rodape))
    },
    footer: context {
      set text(size: 9pt * s, fill: cor_rodape)
      line(length: 100%, stroke: 0.4pt + cor_rodape)
      v(4pt * s)
      align(center)[Página #counter(page).display()]
    },
  )
  corpo
}

// ---- cabeçalho do preenchimento ------------------------------------------------------------------
// Linha do nome da conta (14 pt) só quando vem documento.empresa: a API não traz o nome da conta.
// Logo no topo à direita, 17 mm de altura, 5 mm para dentro da margem, sem empurrar o conteúdo (como a
// exportação); o texto ao lado dele não passa por baixo.
#let cabecalho(p) = {
  let m = p.metadados
  let texto = stack(spacing: 2.4mm * s,
    ..if doc.empresa != none { (text(size: 14pt * s, weight: "bold", doc.empresa),) } else { () },
    text(size: 11pt * s)[*#form.nome* #h(3pt * s) #text(size: 9pt * s, fill: cor_id)[\##form.id] #h(3pt * s) - #h(3pt * s) Preenchimento: *#p.id*])
  if doc.logo != none {
    context {
      let alto = image(doc.logo, height: 17mm)
      let img = if measure(alto).width > 60mm { image(doc.logo, width: 60mm) } else { alto }
      let w = measure(img).width
      place(top + right, dx: -5mm, img)
      block(width: 100% - w - 5mm - 8mm, texto)
    }
  } else {
    grid(columns: (1fr, auto), column-gutter: 8mm, align: (left + top, right + top), texto, none)
  }
  // 31,45 pt: medido contra o PDF da exportação, põe o "Criado por" na mesma altura
  v(31.45pt * s)
  set text(size: 9pt * s)
  set par(leading: 0.8em, spacing: 0.8em)
  let autor = m.criado_por.at("nome", default: none)
  [*Criado por* #if autor != none { autor } else { nao_informado } *em* #m.criado_em \ ]
  if m.horario_dispositivo != none [*Criado em (horário do dispositivo):* #m.horario_dispositivo \ ]
  if m.plataforma_texto != none [*Plataforma:* #m.plataforma_texto \ ]
  v(5.85pt * s)
  [Gerado por #doc.gerado_por em #doc.gerado_em]
  v(6.96pt * s)
  line(length: 100%, stroke: 0.5pt + cor_linha)
}

// ---- valores ------------------------------------------------------------------------------------
// Campo estrela (rating): 5 estrelas como a exportação, as da nota em amarelo e o resto em cinza. O tamanho é
// relativo ao texto (18 pt sobre o corpo de 10 pt na exportação). O ★ vem das fontes do próprio Typst. A linha usa
// ascendente e descendente da fonte: chega a menos de 1 pt do espaço acima das estrelas na exportação.
#let estrelas(c, tamanho: 1.8em) = {
  let n = calc.max(0, calc.min(5, int(c.valor)))
  text(size: tamanho, top-edge: "ascender", bottom-edge: "descender", text(fill: rgb("#F5B600"), "★" * n) + text(fill: rgb("#BEBEBE"), "★" * (5 - n)))
}

#let valor_simples(c) = {
  if c.vazio { return vazio }
  if c.classe == "estrela" { return estrelas(c) }
  if c.classe == "relacional" and c.at("relacionado", default: none) != none {
    return [#c.relacionado.id - #c.relacionado.rotulo]
  }
  let lista = c.at("valores", default: none)
  if lista != none and lista.len() > 0 {
    return stack(spacing: 5pt * s, ..lista.map(v => [#h(1pt * s)•#h(5pt * s)#v]))
  }
  c.valor_formatado
}

// Fotos e assinatura de um campo anexo em grade. largura: espaço disponível; por_linha: fotos por linha
// (padrão da exportação: 3 de 48 x 36 mm). A assinatura fica sempre 50 x 25 mm, 3 por linha.
#let bloco_anexos(c, largura: none, por_linha: none) = {
  if c.vazio { return vazio }
  let assinatura = lower(str(c.tipo)) == "signature"
  let n = if por_linha == none { ajuste("fotos", "por_linha", none) } else { por_linha }
  let espaco = if largura == none { largura_util - 10mm } else { largura }
  let (lf, af) = if n == none and largura == none and not paisagem { (48mm, 36mm) } else {
    let k = if n == none { 3 } else { n }
    let w = (espaco - 3mm * (k - 1)) / k
    (w, w * 0.75)
  }
  let colunas = if assinatura or n == none { 3 } else { n }
  // numa célula estreita (largura informada) a assinatura encolhe para caber 3 por linha
  let la = if largura == none { 50mm } else { calc.min(50mm, (espaco - 6mm) / 3) }
  let lw = if assinatura { la } else { lf }
  let lh = if assinatura { la / 2 } else { af }
  grid(columns: (lw,) * colunas, column-gutter: 3mm, row-gutter: 3mm,
    ..c.anexos.map(a => foto(a, width: lw, height: lh, fit: if assinatura { "contain" } else { "cover" })))
}
