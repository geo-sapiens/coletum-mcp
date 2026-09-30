"""Contrato de dados dos modelos Typst: o dados.json que o template lê.

Monta, a partir da estrutura do formulário e dos preenchimentos da API, um JSON estável (versão 1,
descrito em ../skills/pdf-no-modelo/CONTRATO_DADOS.md): documento, formulário e, para cada
preenchimento, metadados, campos na ordem da estrutura (rótulo, tipo, valor bruto e formatado), grupos
como lista de itens e anexos já baixados numa pasta do trabalho. Reusa a formatação do baixar.py
(fmt_valor), os metadados e o nome legível dos anexos do achatar.py (linha_meta, plano_anexos) e o
download do baixar.py (Baixador: link direto, sem o token, só de hosts permitidos).
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

from achatar import (TIPOS_COORDENADA, Achatador, coord5_texto, coord_bruta, data_local, eh_arquivo, eh_multiplo,
                     fuso, lat_long, linha_meta, plano_anexos, slug)
from baixar import Baixador, fmt_valor

VERSAO_CONTRATO = 1
GERADO_POR = "Coletum via MCP"
PLATAFORMA = {"mobile": "Aplicativo", "web_private": "Sistema web", "web_public": "Link público"}
TIPOS_DATA = {"date"}
TIPOS_DATA_HORA = {"datetime", "date_time"}
TIPOS_HORA = {"time"}
TIPOS_NUMERO = {"float", "int", "integer", "number", "decimal"}
TIPOS_ESCOLHA = {"select", "checkbox", "radio", "multiselect"}
TIPOS_BOOLEANO = {"boolean", "bool"}
META_MAPEAVEIS = ("id", "criado_por", "criado_em", "horario_dispositivo", "plataforma", "coordenada",
                  "editado_por", "editado_em")


def _br(local: str | None) -> str | None:
    """'2026-09-01 08:15:00' -> '01/09/2026 08:15'."""
    if not local or len(local) < 16:
        return None
    return f"{local[8:10]}/{local[5:7]}/{local[:4]} {local[11:16]}"


def _iso(valor: str | None) -> str | None:
    """Data da API ('...-0300', sem dois-pontos) em ISO legível por qualquer biblioteca."""
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%dT%H:%M:%S%z").isoformat()
    except ValueError:
        return valor


def texto_coordenada(lat, lon) -> str | None:
    if lat is None or lon is None:
        return None
    return f"Latitude: {coord5_texto(lat, ',')} / Longitude: {coord5_texto(lon, ',')}"


def classe_do_tipo(comp: dict, valor) -> str:
    tipo = (comp.get("type") or "").lower()
    if tipo == "group":
        return "grupo"
    if eh_arquivo(comp):
        return "anexo"
    if tipo in TIPOS_COORDENADA or (isinstance(valor, dict) and "coordinates" in valor):
        return "coordenada"
    if tipo in ("relational", "relation") or (isinstance(valor, dict) and "answer_id" in valor):
        return "relacional"
    if tipo in TIPOS_NUMERO:
        return "numero"
    if tipo in TIPOS_DATA or tipo in TIPOS_DATA_HORA:
        return "data"
    if tipo in TIPOS_HORA:
        return "hora"
    if tipo in TIPOS_BOOLEANO or isinstance(valor, bool):
        return "booleano"
    if tipo in TIPOS_ESCOLHA or "options" in comp:
        return "escolha"
    return "texto"


def _vazio(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


def formatar(comp: dict, v) -> tuple[str | None, list | None]:
    """(valor_formatado, valores): valores só para campo múltiplo (lista já formatada)."""
    tipo = (comp.get("type") or "").lower()
    if _vazio(v):
        return None, ([] if eh_multiplo(comp) and tipo != "group" else None)
    if tipo in TIPOS_COORDENADA or (isinstance(v, dict) and "coordinates" in v):
        return texto_coordenada(*lat_long(v)), None
    if tipo in TIPOS_HORA and isinstance(v, str) and re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", v):
        return v[:5], None
    if isinstance(v, list):
        itens = [fmt_valor(x, tipo) for x in v]
        itens = [x for x in itens if x]
        return (", ".join(itens) or None), itens
    return fmt_valor(v, tipo), None


class Montador:
    """Monta o contrato de um conjunto de preenchimentos, baixando os anexos para <trabalho>/fotos."""

    def __init__(self, estrutura: dict, id_formulario, trabalho: Path, max_fotos: int = 200,
                 baixar: bool = True) -> None:
        self.e = estrutura
        self.fid = id_formulario
        self.trabalho = trabalho
        self.pasta_fotos = trabalho / "fotos"
        self.max_fotos = max_fotos
        self.bx = Baixador(baixar)
        self.fotos_gravadas = self.fotos_indisponiveis = self.fotos_fora = self.fotos_simuladas = 0
        self._gravadas: dict[str, tuple[str | None, str, dict]] = {}

    # ---- anexos ------------------------------------------------------------------------------
    def _anexo(self, link: str, nome: str, rotulo: str | None = None, tipo: str | None = None) -> dict:
        """Baixa (uma vez por link), reduz para no máximo 1.600 px e grava em fotos/. Nunca guarda o link.
        Foto simulada (COLETUM_FOTOS_TESTE, só no teste local) entra com a situação "simulada"."""
        if link in self._gravadas:
            arq, situacao, extra = self._gravadas[link]
            return {"arquivo": arq, "nome": nome, "situacao": situacao, **extra}
        if self.fotos_gravadas + self.fotos_indisponiveis >= self.max_fotos:
            self.fotos_fora += 1
            return {"arquivo": None, "nome": nome, "situacao": "fora do limite de fotos desta chamada",
                    "imagem": False}
        conteudo, motivo = self.bx.baixar(link, rotulo, tipo)
        arq, extra = None, {"imagem": False}
        if conteudo:
            try:
                from PIL import Image, ImageOps
                im = ImageOps.exif_transpose(Image.open(io.BytesIO(conteudo)))
                tem_alfa = im.mode in ("RGBA", "LA", "P") and ("transparency" in im.info or im.mode != "P")
                im.thumbnail((1600, 1600))
                self.pasta_fotos.mkdir(parents=True, exist_ok=True)
                base = Path(nome).stem
                if tem_alfa:
                    destino = self.pasta_fotos / f"{base}.png"
                    im.convert("RGBA").save(destino, format="PNG", optimize=True)
                else:
                    destino = self.pasta_fotos / f"{base}.jpg"
                    im.convert("RGB").save(destino, format="JPEG", quality=82, optimize=True)
                arq = f"/fotos/{destino.name}"
                extra = {"imagem": True, "largura_px": im.size[0], "altura_px": im.size[1]}
            except Exception:
                motivo = "o arquivo não é uma imagem que o PDF aceite"
        if arq:
            self.fotos_gravadas += 1
            situacao = "baixado"
            if self.bx.simulada(link):
                self.fotos_simuladas += 1
                situacao = "simulada"
        else:
            self.fotos_indisponiveis += 1
            situacao = f"indisponível: {motivo}"
        self._gravadas[link] = (arq, situacao, extra)
        return {"arquivo": arq, "nome": nome, "situacao": situacao, **extra}

    # ---- campos ------------------------------------------------------------------------------
    def _campos(self, comps: list, valores, pid: str, id_item: str | None, nomes: dict,
                todos_anexos: list, caminho_rotulo: str) -> tuple[list, dict]:
        valores = valores if isinstance(valores, dict) else {}
        campos, indice = [], {}
        for c in comps:
            k = c.get("id")
            rot = c.get("label") or k
            v = valores.get(k)
            classe = classe_do_tipo(c, v)
            campo = {"chave": k, "rotulo": rot, "tipo": c.get("type"), "classe": classe,
                     "multiplo": eh_multiplo(c) and c.get("type") != "group", "ajuda": c.get("help_block") or None}
            if classe == "grupo":
                repetivel = eh_multiplo(c)
                if repetivel:
                    brutos = v if isinstance(v, list) else ([] if v is None else [v])
                else:
                    brutos = [v if isinstance(v, dict) else {}]
                itens = []
                for i, item in enumerate(brutos):
                    # id_item = código da planilha (base 0); numero = ordem de leitura (1 = o primeiro)
                    idi = f"{id_item or pid}.{i}" if repetivel else (id_item or pid)
                    sub, sub_idx = self._campos(c.get("components") or [], item, pid,
                                                idi if repetivel else id_item, nomes, todos_anexos,
                                                f"{caminho_rotulo}{rot}" + (f" · item {i + 1}" if repetivel else "") + " · ")
                    itens.append({"id_item": idi if repetivel else None, "numero": i + 1, "campos": sub,
                                  "indice": sub_idx})
                campo.update({"repetivel": repetivel, "itens": itens, "qtd_itens": len(itens) if repetivel else None,
                              "vazio": repetivel and not itens, "valor": None, "valor_formatado": None})
            elif classe == "anexo":
                links = v if isinstance(v, list) else ([v] if v else [])
                anexos = []
                for n, link in enumerate(links):  # n = posição no campo, base 0 como no plano de anexos
                    nome = nomes.get((id_item, k, n)) or f"{pid.replace('.', '-')}_{slug(rot, 20)}_{n:02d}.jpg"
                    a = self._anexo(str(link), nome, rot, c.get("type"))
                    a["legenda"] = f"{caminho_rotulo}{rot}" + (f" {n + 1}" if len(links) > 1 else "")
                    anexos.append(a)
                    todos_anexos.append({**a, "campo": rot, "chave_campo": k, "tipo_campo": c.get("type"),
                                        "id_item": id_item})
                campo.update({"anexos": anexos, "vazio": not anexos, "valor": None,
                              "valor_formatado": f"{len(anexos)} arquivo{'s' if len(anexos) != 1 else ''}" if anexos else None})
            else:
                fmt, lista = formatar(c, v)
                if classe == "coordenada":
                    v = coord_bruta(v)   # o bruto também em até 5 casas, como a tela
                campo.update({"valor": v, "valor_formatado": fmt, "vazio": fmt is None})
                if lista is not None:
                    campo["valores"] = lista
                if classe == "coordenada":
                    la, lo = lat_long(v)
                    campo["coordenada"] = {"lat": la, "long": lo, "texto": fmt} if la is not None else None
                elif classe == "relacional" and isinstance(v, dict):
                    campo["relacionado"] = {"id": v.get("answer_id"), "rotulo": v.get("label")}
            indice.setdefault(k, len(campos))
            indice.setdefault(rot, len(campos))
            campos.append(campo)
        return campos, indice

    def _metadados(self, p: dict) -> dict:
        m = linha_meta(p)
        md = p.get("meta_data") or {}
        disp_local, _ = data_local(md.get("created_at_device"))
        coord = None
        if m["lat"] is not None:
            coord = {"lat": m["lat"], "long": m["long"], "precisao_m": m["precisao_m"],
                     "altitude_m": m["altitude_m"], "texto": texto_coordenada(m["lat"], m["long"])}
        editado = None
        if m["editado_em"]:
            editado = {"por": {"id": m["editado_por_id"], "nome": m["editado_por_nome"]},
                       "em": _br(m["editado_em"]), "em_iso": _iso(m["editado_em_original"]),
                       "plataforma": m["origem_edicao"], "plataforma_texto": PLATAFORMA.get(m["origem_edicao"] or "")}
        return {
            "criado_por": {"id": m["criado_por_id"], "nome": m["criado_por_nome"]},
            "criado_em": _br(m["criado_em"]), "criado_em_iso": _iso(m["criado_em_original"]),
            "horario_dispositivo": _br(disp_local), "horario_dispositivo_iso": _iso(md.get("created_at_device")),
            "plataforma": m["origem_criacao"], "plataforma_texto": PLATAFORMA.get(m["origem_criacao"] or "", m["origem_criacao"]),
            "coordenada": coord, "edicao": editado, "tamanho_anexos_bytes": m["total_size"],
        }

    def preenchimento(self, p: dict) -> dict:
        pid = str(p.get("id"))
        ach = Achatador(self.e)
        ach.adicionar(p)
        nomes = {(l["id_item"], l["chave_campo"], int(l["posicao"])): l["nome_arquivo"]
                 for l in plano_anexos(ach, self.fid, self.e.get("name") or "")}
        todos: list = []
        campos, indice = self._campos(self.e.get("components") or [], p.get("answer") or {}, pid, None, nomes,
                                      todos, "")
        return {"id": pid, "metadados": self._metadados(p), "campos": campos, "indice": indice,
                "anexos_todos": todos}

    def fechar(self) -> None:
        self.bx.fechar()


# --------------------------------------------------------------------------------------------
# Mapeamento: rótulo do modelo do cliente -> campo do formulário
# --------------------------------------------------------------------------------------------

def _achar(campos: list, indice: dict, nome: str) -> dict | None:
    i = indice.get(nome)
    if i is None:
        alvo = slug(nome, 200)
        for c in campos:
            if slug(c["chave"] or "", 200) == alvo or slug(c["rotulo"] or "", 200) == alvo:
                return c
        return None
    return campos[i]


def resolver_caminho(p: dict, caminho: str) -> dict | None:
    """'chave', 'rotulo', 'GRUPO/CAMPO' (1º item), 'GRUPO[2]/CAMPO' ou 'meta:<nome>'."""
    caminho = str(caminho).strip()
    if caminho.startswith("meta:"):
        nome = caminho[5:].strip()
        md = p["metadados"]
        if nome == "id":
            txt = p["id"]
        elif nome in ("criado_por", "editado_por"):
            fonte = md["criado_por"] if nome == "criado_por" else (md.get("edicao") or {}).get("por") or {}
            txt = fonte.get("nome")
        elif nome == "coordenada":
            txt = (md.get("coordenada") or {}).get("texto")
        elif nome == "plataforma":
            txt = md.get("plataforma_texto")
        elif nome == "editado_em":
            txt = (md.get("edicao") or {}).get("em")
        elif nome in md:
            txt = md.get(nome)
        else:
            return None
        return {"chave": caminho, "rotulo": nome, "classe": "metadado", "valor": txt, "valor_formatado": txt,
                "vazio": txt in (None, "")}
    campos, indice = p["campos"], p["indice"]
    partes = [x for x in caminho.split("/") if x.strip()]
    for n, parte in enumerate(partes):
        m = re.fullmatch(r"(.+?)\[(\d+)\]", parte.strip())
        nome, pos = (m.group(1).strip(), int(m.group(2))) if m else (parte.strip(), 1)
        c = _achar(campos, indice, nome)
        if c is None:
            return None
        if n == len(partes) - 1:
            return c
        if c["classe"] != "grupo" or len(c["itens"]) < pos:
            return None
        item = c["itens"][pos - 1]
        campos, indice = item["campos"], item["indice"]
    return None


def aplicar_mapeamento(dados: dict, mapeamento: dict | None) -> list[str]:
    """Põe em cada preenchimento 'mapeados': {rótulo do modelo: campo}. O caminho pode ser uma lista de
    alternativas (vale a primeira preenchida). Devolve os rótulos sem campo."""
    faltam: set = set()
    for p in dados["preenchimentos"]:
        p["mapeados"] = {}
        for rot, caminho in (mapeamento or {}).items():
            if str(rot).startswith("_"):
                continue
            opcoes = caminho if isinstance(caminho, list) else [caminho]
            c = None
            for op in opcoes:  # lista = alternativas: vale a primeira preenchida (ou a primeira que existir)
                achado = resolver_caminho(p, op) if op else None
                if achado is not None and (c is None or (c.get("vazio") and not achado.get("vazio"))):
                    c = achado
                if c is not None and not c.get("vazio"):
                    break
            if c is None:
                faltam.add(f"{rot} ({caminho})" if caminho else f"{rot} (sem campo)")
                c = {"chave": None, "rotulo": rot, "classe": "sem_campo", "valor": None, "valor_formatado": None,
                     "vazio": True}
            p["mapeados"][rot] = c
    return sorted(faltam)


def documento(estrutura: dict, empresa: str | None, logo: str | None, variaveis: dict | None, qtd: int,
              aparencia: dict | None = None) -> dict:
    agora = datetime.now(fuso())
    return {"versao_contrato": VERSAO_CONTRATO, "gerado_em": agora.strftime("%d/%m/%Y %H:%M"),
            "gerado_em_iso": agora.isoformat(timespec="seconds"), "gerado_por": GERADO_POR,
            "fuso": str(fuso()), "empresa": empresa or None, "logo": logo, "variaveis": variaveis or {},
            "aparencia": aparencia or {}, "qtd_preenchimentos": qtd}


# --------------------------------------------------------------------------------------------
# Aparência pedida na conversa: vale nos modelos embutidos; template do cliente lê se quiser
# --------------------------------------------------------------------------------------------

ORIENTACOES = {"retrato": "retrato", "paisagem": "paisagem", "deitada": "paisagem", "horizontal": "paisagem",
               "vertical": "retrato", "landscape": "paisagem", "portrait": "retrato"}


def _lista_de_nomes(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def normalizar_aparencia(bruto: dict | None) -> tuple[dict, list[str]]:
    """Aparência no formato do contrato, só com as chaves pedidas e válidas. Devolve (aparencia, avisos).

    Aceita: campos{ocultar[], ordem[], mostrar_vazios}, fotos{por_linha 1 a 4}, fonte{tamanho 6 a 16},
    cores{destaque #RRGGBB (primaria vale como sinônimo)}, pagina{orientacao retrato|paisagem}."""
    ap: dict = {}
    avisos: list[str] = []
    b = bruto if isinstance(bruto, dict) else {}
    c = b.get("campos") if isinstance(b.get("campos"), dict) else {}
    campos: dict = {}
    for chave in ("ocultar", "ordem"):
        if chave in c:
            campos[chave] = _lista_de_nomes(c[chave])
    if "mostrar_vazios" in c and c["mostrar_vazios"] is not None:
        campos["mostrar_vazios"] = bool(c["mostrar_vazios"])
    if campos:
        ap["campos"] = campos
    f = b.get("fotos") if isinstance(b.get("fotos"), dict) else {}
    if f.get("por_linha") is not None:
        try:
            n = int(float(f["por_linha"]))
            if not 1 <= n <= 4:
                avisos.append(f"Aparência: fotos.por_linha vai de 1 a 4; usei {min(max(n, 1), 4)}.")
            ap["fotos"] = {"por_linha": min(max(n, 1), 4)}
        except (TypeError, ValueError):
            avisos.append(f"Aparência: fotos.por_linha inválido ({f['por_linha']!r}); usei o padrão do modelo.")
    t = b.get("fonte") if isinstance(b.get("fonte"), dict) else {}
    if t.get("tamanho") is not None:
        try:
            v = float(t["tamanho"])
            if not 6 <= v <= 16:
                avisos.append("Aparência: fonte.tamanho vai de 6 a 16 pt; usei o limite mais próximo.")
            v = min(max(v, 6.0), 16.0)
            ap["fonte"] = {"tamanho": int(v) if v.is_integer() else round(v, 1)}
        except (TypeError, ValueError):
            avisos.append(f"Aparência: fonte.tamanho inválido ({t['tamanho']!r}); usei o padrão do modelo.")
    cores = b.get("cores") if isinstance(b.get("cores"), dict) else {}
    destaque = cores.get("destaque") or cores.get("primaria")
    if destaque is not None:
        if isinstance(destaque, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", destaque.strip()):
            ap["cores"] = {"destaque": "#" + destaque.strip().lstrip("#").upper()}
        else:
            avisos.append(f"Aparência: cor de destaque inválida ({destaque!r}); use #RRGGBB. Usei a padrão.")
    pg = b.get("pagina") if isinstance(b.get("pagina"), dict) else {}
    if pg.get("orientacao") is not None:
        o = ORIENTACOES.get(str(pg["orientacao"]).strip().lower())
        if o:
            ap["pagina"] = {"orientacao": o}
        else:
            avisos.append(f"Aparência: pagina.orientacao deve ser retrato ou paisagem ({pg['orientacao']!r}); "
                          "usei retrato.")
    return ap, avisos


def mesclar_aparencia(base: dict | None, extra: dict | None) -> dict:
    """Aparência do modelo salvo com a da chamada por cima (grupo a grupo)."""
    saida = {k: dict(v) for k, v in (base or {}).items() if isinstance(v, dict)}
    for k, v in (extra or {}).items():
        if isinstance(v, dict):
            saida.setdefault(k, {}).update(v)
    return saida


def _filtrar_campos(campos: list, ocultar: set, ordem: dict, vazios: bool, usados: set) -> list:
    def nomes(c):
        return {slug(c.get("chave") or "", 200), slug(c.get("rotulo") or "", 200)} - {""}

    saida = []
    for c in campos:
        n = nomes(c)
        if n & ocultar:
            usados.update(n & ocultar)
            continue
        if c["classe"] == "grupo":
            c = dict(c)
            itens = []
            for it in c["itens"]:
                sub = _filtrar_campos(it["campos"], ocultar, ordem, vazios, usados)
                itens.append({**it, "campos": sub, "indice": _indice(sub)})
            if not vazios and (not itens or all(not it["campos"] for it in itens)):
                continue
            c["itens"] = itens
        elif not vazios and c.get("vazio"):
            continue
        saida.append(c)
    if ordem:
        def pos(c):
            achados = [ordem[x] for x in nomes(c) if x in ordem]
            if achados:
                usados.update(x for x in nomes(c) if x in ordem)
            return min(achados) if achados else None
        citados = sorted([c for c in saida if pos(c) is not None], key=pos)
        saida = citados + [c for c in saida if pos(c) is None]
    return saida


def _indice(campos: list) -> dict:
    indice: dict = {}
    for i, c in enumerate(campos):
        indice.setdefault(c["chave"], i)
        indice.setdefault(c["rotulo"], i)
    return indice


def _anexos_em_ordem(campos: list, id_item, saida: list) -> list:
    """Refaz anexos_todos a partir dos campos visíveis, como o Montador monta (campo, chave, tipo, item)."""
    for c in campos:
        if c["classe"] == "grupo":
            for it in c["itens"]:
                _anexos_em_ordem(it["campos"], it["id_item"] if c["repetivel"] else id_item, saida)
        elif c["classe"] == "anexo":
            for a in c.get("anexos") or []:
                saida.append({**a, "campo": c["rotulo"], "chave_campo": c["chave"], "tipo_campo": c["tipo"],
                              "id_item": id_item})
    return saida


def aplicar_aparencia(dados: dict, aparencia: dict | None) -> list[str]:
    """Aplica campos.ocultar, campos.ordem e campos.mostrar_vazios em campos, indice e anexos_todos de cada
    preenchimento (em qualquer nível, pela chave ou pelo rótulo). Sem esses ajustes, não toca em nada.
    Devolve os nomes pedidos que não casaram com nenhum campo."""
    c = (aparencia or {}).get("campos") or {}
    ocultar_lista, ordem_lista = c.get("ocultar") or [], c.get("ordem") or []
    vazios = c.get("mostrar_vazios", True)
    if not ocultar_lista and not ordem_lista and vazios:
        return []
    ocultar = {slug(x, 200) for x in ocultar_lista}
    ordem: dict = {}
    for i, x in enumerate(ordem_lista):
        ordem.setdefault(slug(x, 200), i)
    usados: set = set()
    for p in dados["preenchimentos"]:
        p["campos"] = _filtrar_campos(p["campos"], ocultar, ordem, vazios, usados)
        p["indice"] = _indice(p["campos"])
        p["anexos_todos"] = _anexos_em_ordem(p["campos"], None, [])
    return sorted({x for x in ocultar_lista + ordem_lista if slug(x, 200) not in usados})


def formulario(estrutura: dict, id_formulario) -> dict:
    return {"id": id_formulario, "nome": estrutura.get("name"), "versao": estrutura.get("version"),
            "categoria": estrutura.get("category")}
