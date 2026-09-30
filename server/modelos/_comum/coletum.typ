// coletum.typ: apoio para modelos de PDF do Coletum (contrato de dados versão 1).
// O conector copia este arquivo para a pasta do trabalho. No template:
//   #import "/coletum.typ": *
// Contrato completo: skills/pdf-no-modelo/CONTRATO_DADOS.md

// Os dados do trabalho (documento, formulario, preenchimentos).
#let dados = json(sys.inputs.at("dados", default: "/dados.json"))

#let nao_informado = "Não informado"

// Aparência pedida na conversa (documento.aparencia): só as chaves pedidas; o que faltar é o padrão do modelo.
#let aparencia = dados.documento.at("aparencia", default: (:))

// Um ajuste de aparência, ex.: ajuste("fotos", "por_linha", 3). Devolve o padrão quando não foi pedido.
#let ajuste(grupo, chave, padrao) = {
  let g = aparencia.at(grupo, default: none)
  if type(g) != dictionary { padrao } else {
    let v = g.at(chave, default: none)
    if v == none { padrao } else { v }
  }
}

// Campo de um preenchimento (ou de um item de grupo) pela chave técnica ou pelo rótulo exato.
// Devolve none se não existir.
#let campo(obj, nome) = {
  let i = obj.indice.at(nome, default: none)
  if i == none { none } else { obj.campos.at(i) }
}

// Texto pronto de um campo, ou o padrão quando vazio ou inexistente.
#let valor(obj, nome, padrao: nao_informado) = {
  let c = campo(obj, nome)
  if c == none or c.valor_formatado == none { padrao } else { c.valor_formatado }
}

// Campo pelo rótulo do modelo do cliente (mapeamento do modelo.json). Devolve none se não houver.
#let mapeado(p, rotulo) = p.at("mapeados", default: (:)).at(rotulo, default: none)

// Texto pronto de um campo mapeado, ou o padrão.
#let valor_mapeado(p, rotulo, padrao: nao_informado) = {
  let c = mapeado(p, rotulo)
  if c == none or c.valor_formatado == none { padrao } else { c.valor_formatado }
}

// Todos os anexos do preenchimento, em ordem (campos e itens de grupo), baixados ou não.
#let anexos(p) = p.at("anexos_todos", default: ())

// Só os anexos que viraram imagem no disco.
#let fotos(p) = anexos(p).filter(a => a.arquivo != none and a.at("imagem", default: false))

// Uma foto do contrato, ou um quadro "Foto indisponível" do mesmo tamanho quando o download falhou.
#let foto(a, width: 100%, height: auto, fit: "contain") = {
  if a.arquivo != none and a.at("imagem", default: false) {
    image(a.arquivo, width: width, height: height, fit: fit)
  } else {
    let h = if height == auto { 30mm } else { height }
    box(width: width, height: h, fill: rgb("#F2F2F2"), stroke: 0.6pt + rgb("#999999"), inset: 4pt,
      align(center + horizon, text(size: 7pt, fill: rgb("#666666"))[
        *Foto indisponível* \ #a.situacao.replace("indisponível: ", "")
      ]))
  }
}
