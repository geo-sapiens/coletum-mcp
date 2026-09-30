"""PDF no modelo do cliente: análise do PDF modelo, modelos Typst salvos, compilação e lado a lado.

- analisar(): lê um PDF (ou foto) que o cliente já usa e devolve tamanho, margens, linhas de texto com
  posição e fonte, cores, imagens embutidas (salvas como candidatas a logo) e as páginas como imagem.
- Modelos salvos: pasta COLETUM_PASTA_MODELOS (padrão Documentos/Coletum/modelos), um modelo por pasta
  (<nome>/modelo.typ, modelo.json, arquivos/, fontes/). Os embutidos (./modelos/) são só leitura.
  A Noto Sans (./modelos/_fontes/, SIL OFL 1.1) entra em toda compilação: o cliente não instala fonte.
- compilar(): monta a pasta do trabalho (dados.json, fotos, arquivos do modelo, coletum.typ) e compila com
  o Typst, com a raiz na pasta do trabalho (o template não lê nada fora dela) e sem pacotes da internet.
- lado_a_lado(): PNG com a página do modelo à esquerda e a da amostra à direita.
- Preferências do cliente: preferencias.md na pasta de modelos.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import contrato
from api import pasta_padrao

AQUI = Path(__file__).resolve().parent
EMBUTIDOS = AQUI / "modelos"
COMUM = EMBUTIDOS / "_comum" / "coletum.typ"
ESTILO = EMBUTIDOS / "_comum" / "coletum_estilo.typ"  # visual da exportação, comum aos embutidos
FONTES_EMBUTIDAS = EMBUTIDOS / "_fontes"  # Noto Sans (SIL OFL 1.1), a fonte da exportação; vai em toda compilação
PASTA_MODELOS_PADRAO = pasta_padrao("modelos")
NOME_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,59}$")
EXT_FONTE = {".ttf", ".otf", ".ttc", ".otc"}
EXT_ARQUIVO = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".json", ".csv", ".txt", ".typ", ".pdf"}
EXT_IMAGEM = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MM = 25.4 / 72


class ErroModelo(Exception):
    """Mensagem em português, pronta para a IA."""


# --------------------------------------------------------------------------------------------
# Pasta de modelos e preferências
# --------------------------------------------------------------------------------------------

def pasta_modelos(config) -> Path:
    p = Path(config("COLETUM_PASTA_MODELOS") or PASTA_MODELOS_PADRAO).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ler_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _info(pasta: Path, embutido: bool) -> dict:
    meta = _ler_json(pasta / "modelo.json")
    return {"nome": pasta.name, "descricao": meta.get("descricao"), "formularios": meta.get("formularios") or [],
            "campos_mapeados": len(meta.get("mapeamento") or {}), "embutido": embutido,
            "somente_leitura": embutido, "criado_em": meta.get("criado_em"),
            "atualizado_em": meta.get("atualizado_em"), "caminho": str(pasta),
            **({"aparencia_aceita": meta["aparencia_aceita"]} if meta.get("aparencia_aceita") else {}),
            **({"aparencia": meta["aparencia"]} if meta.get("aparencia") else {})}


def listar(config) -> dict:
    saida = []
    for base, embutido in ((EMBUTIDOS, True), (pasta_modelos(config), False)):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.name.startswith(("_", ".")) and (d / "modelo.typ").is_file():
                saida.append(_info(d, embutido))
    pm = pasta_modelos(config)
    return {"pasta_modelos": str(pm), "modelos": saida, "tem_preferencias": (pm / "preferencias.md").is_file()}


def achar_modelo(nome_ou_caminho: str, config) -> tuple[Path, Path, dict]:
    """Devolve (arquivo .typ, pasta do modelo, modelo.json). Aceita nome salvo, nome embutido ou caminho .typ."""
    s = str(nome_ou_caminho).strip()
    p = Path(s).expanduser()
    if s.endswith(".typ") or p.is_file():
        if not p.is_file():
            raise ErroModelo(f"Template não encontrado: {p}")
        return p, p.parent, _ler_json(p.parent / "modelo.json")
    for base in (pasta_modelos(config), EMBUTIDOS):
        d = base / s
        if (d / "modelo.typ").is_file():
            return d / "modelo.typ", d, _ler_json(d / "modelo.json")
    nomes = [m["nome"] for m in listar(config)["modelos"]]
    raise ErroModelo(f"Modelo '{s}' não existe. Modelos disponíveis: {', '.join(nomes) or '(nenhum)'}. "
                     "Use listar_modelos, ou passe o caminho de um .typ ou o texto em template_typst.")


def _copiar_arquivos(origens: list[str] | None, destino: Path, extensoes: set[str], tipo: str) -> list[str]:
    copiados = []
    for o in origens or []:
        p = Path(str(o)).expanduser()
        if not p.is_file():
            raise ErroModelo(f"Arquivo de {tipo} não encontrado: {p}")
        if p.suffix.lower() not in extensoes:
            raise ErroModelo(f"{p.name}: extensão {p.suffix or '(nenhuma)'} não aceita para {tipo} "
                             f"({', '.join(sorted(extensoes))}).")
        destino.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, destino / p.name)
        copiados.append(p.name)
    return copiados


def salvar(config, nome: str, template_typst: str, descricao: str | None, formularios: list | None,
           mapeamento: dict | None, arquivos: list[str] | None, fontes: list[str] | None,
           substituir: bool, logo: str | None = None, variaveis: dict | None = None,
           aparencia: dict | None = None) -> dict:
    nome = str(nome or "").strip()
    if not NOME_VALIDO.match(nome):
        raise ErroModelo(f"Nome de modelo inválido: '{nome}'. Use de 2 a 60 caracteres, minúsculas, números, "
                         "_ ou - (ex.: vistoria_obra).")
    if (EMBUTIDOS / nome).is_dir():
        raise ErroModelo(f"'{nome}' é um modelo embutido (somente leitura). Escolha outro nome.")
    verificar_template(template_typst)
    destino = pasta_modelos(config) / nome
    anterior = _ler_json(destino / "modelo.json")
    if destino.exists() and not substituir:
        raise ErroModelo(f"Já existe um modelo '{nome}' em {destino}. Para trocar, chame de novo com "
                         "substituir=true (confirme com o cliente antes).")
    temp = destino.with_name(f".{nome}_novo")
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    try:
        (temp / "modelo.typ").write_text(template_typst, encoding="utf-8")
        arqs = _copiar_arquivos(arquivos, temp / "arquivos", EXT_ARQUIVO, "arquivo do modelo")
        fnts = _copiar_arquivos(fontes, temp / "fontes", EXT_FONTE, "fonte")
        if logo:
            lp = Path(logo).expanduser()
            if not lp.is_file() or lp.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg", ".gif"}:
                raise ErroModelo(f"Logo não encontrado ou fora dos formatos PNG, JPG, GIF, SVG: {logo}")
            (temp / "arquivos").mkdir(exist_ok=True)
            for velho in (temp / "arquivos").glob("logo.*"):
                velho.unlink()
            shutil.copy2(lp, temp / "arquivos" / f"logo{lp.suffix.lower()}")
        if destino.exists() and substituir:  # arquivos e fontes antigos seguem, se não vieram novos
            for sub in ("arquivos", "fontes"):
                if (destino / sub).is_dir():
                    for f in (destino / sub).iterdir():
                        if f.is_file() and not (temp / sub / f.name).exists():
                            (temp / sub).mkdir(exist_ok=True)
                            shutil.copy2(f, temp / sub / f.name)
        agora = datetime.now().isoformat(timespec="seconds")
        meta = {"nome": nome, "descricao": descricao or anterior.get("descricao"),
                "formularios": [int(x) for x in (formularios or anterior.get("formularios") or [])],
                "mapeamento": mapeamento if mapeamento is not None else anterior.get("mapeamento") or {},
                "variaveis": variaveis if variaveis is not None else anterior.get("variaveis") or {},
                "aparencia": aparencia if aparencia is not None else anterior.get("aparencia") or {},
                "criado_em": anterior.get("criado_em") or agora, "atualizado_em": agora,
                "versao_contrato": 1}
        (temp / "modelo.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if destino.exists():
            shutil.rmtree(destino)
        temp.rename(destino)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return {"nome": nome, "caminho": str(destino), "substituido": bool(anterior) and substituir,
            "arquivos": sorted(p.name for p in (destino / "arquivos").glob("*")) if (destino / "arquivos").is_dir() else [],
            "fontes": sorted(p.name for p in (destino / "fontes").glob("*")) if (destino / "fontes").is_dir() else [],
            "campos_mapeados": len(meta["mapeamento"])}


def ler_preferencias(config) -> dict:
    p = pasta_modelos(config) / "preferencias.md"
    if not p.is_file():
        return {"existe": False, "caminho": str(p), "texto": "",
                "observacao": "Ainda não há preferências salvas. Na primeira vez, faça as perguntas essenciais da skill pdf-no-modelo (Conhecer o cliente)."}
    return {"existe": True, "caminho": str(p), "texto": p.read_text(encoding="utf-8"),
            "atualizado_em": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}


def salvar_preferencias(config, texto: str, modo: str) -> dict:
    p = pasta_modelos(config) / "preferencias.md"
    texto = (texto or "").strip()
    if not texto:
        raise ErroModelo("Texto vazio: nada para salvar.")
    if len(texto) > 20000:
        raise ErroModelo("Preferências passam de 20 mil caracteres: resuma antes de salvar.")
    if modo == "acrescentar" and p.is_file():
        atual = p.read_text(encoding="utf-8").rstrip()
        texto = f"{atual}\n\n{texto}"
    p.write_text(texto + "\n", encoding="utf-8")
    return {"caminho": str(p), "caracteres": len(texto), "modo": modo}


# --------------------------------------------------------------------------------------------
# Compilação
# --------------------------------------------------------------------------------------------

def verificar_template(texto: str) -> None:
    if not texto or not texto.strip():
        raise ErroModelo("Template vazio.")
    if re.search(r"""["']@[a-z]+/""", texto):
        raise ErroModelo("O template importa um pacote do Typst (\"@preview/...\"). Pacotes baixam da internet e "
                         "ficam fora desta versão: escreva a função no próprio template.")


def _limpar_caminhos(texto: str, trabalho: Path) -> str:
    """O Typst escreve o arquivo relativo à pasta atual (../../...): deixa só o caminho dentro do trabalho."""
    return re.sub(r"(?<=\s)\S*?" + re.escape(trabalho.name) + "/", "", texto)


def _diagnostico(e, arquivo_typ: Path, trabalho: Path) -> str:
    diag = getattr(e, "diagnostic", None) or str(e)
    return _limpar_caminhos(diag, trabalho).strip()[:3000]


def preparar_trabalho(trabalho: Path, texto_typ: str, pasta_modelo: Path | None, arquivos_extra: list[str] | None,
                      logo: str | None) -> tuple[list[str], str | None]:
    """Copia coletum.typ, os arquivos do modelo e os extras; devolve (pastas de fontes, logo relativo)."""
    trabalho.mkdir(parents=True, exist_ok=True)
    shutil.copy2(COMUM, trabalho / "coletum.typ")
    shutil.copy2(ESTILO, trabalho / "coletum_estilo.typ")
    (trabalho / "modelo.typ").write_text(texto_typ, encoding="utf-8")
    fontes = []
    if pasta_modelo is not None:
        if (pasta_modelo / "arquivos").is_dir():
            shutil.copytree(pasta_modelo / "arquivos", trabalho / "arquivos", dirs_exist_ok=True)
        if (pasta_modelo / "fontes").is_dir():
            fontes.append(str(pasta_modelo / "fontes"))
    if FONTES_EMBUTIDAS.is_dir():  # depois das do modelo: modelo embutido, salvo ou texto solto acham a Noto Sans
        fontes.append(str(FONTES_EMBUTIDAS))
    _copiar_arquivos(arquivos_extra, trabalho / "arquivos", EXT_ARQUIVO, "arquivo do modelo")
    logo_rel = None
    if logo:
        lp = Path(logo).expanduser()
        if not lp.is_file() and (trabalho / "arquivos" / logo).is_file():
            lp = trabalho / "arquivos" / logo
        if not lp.is_file():
            raise ErroModelo(f"Logo não encontrado: {logo}")
        if lp.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg", ".gif"}:
            raise ErroModelo("Logo precisa ser PNG, JPG, GIF ou SVG.")
        destino = trabalho / "arquivos" / f"logo{lp.suffix.lower()}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        if lp.resolve() != destino.resolve():
            shutil.copy2(lp, destino)
        logo_rel = f"/arquivos/{destino.name}"
    if logo_rel is None:  # logo guardado no modelo (salvar_modelo com logo)
        for ext in (".png", ".jpg", ".jpeg", ".svg", ".gif"):
            if (trabalho / "arquivos" / f"logo{ext}").is_file():
                logo_rel = f"/arquivos/logo{ext}"
                break
    return fontes, logo_rel


def compilar(trabalho: Path, saida_pdf: Path, fontes: list[str], nome_dados: str = "dados.json") -> dict:
    """Compila <trabalho>/modelo.typ para saida_pdf. Raiz = trabalho. Erro vira ErroModelo com linha e coluna."""
    import typst

    pacotes = trabalho / ".pacotes"
    pacotes.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    try:
        pdf, alertas = typst.compile_with_warnings(str(trabalho / "modelo.typ"), None, root=str(trabalho),
                                                   font_paths=fontes, sys_inputs={"dados": f"/{nome_dados}"},
                                                   package_path=str(pacotes))
    except typst.TypstError as e:
        raise ErroModelo("O Typst não compilou o template. Corrija e gere de novo.\n"
                         + _diagnostico(e, trabalho / "modelo.typ", trabalho)
                         + ("\nDica: " + " | ".join(e.hints) if getattr(e, "hints", None) else "")) from None
    except RuntimeError as e:
        raise ErroModelo(f"O Typst não compilou o template: {e}") from None
    segundos = time.perf_counter() - t0
    saida_pdf.parent.mkdir(parents=True, exist_ok=True)
    saida_pdf.write_bytes(pdf)
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(saida_pdf))
    paginas = len(doc)
    doc.close()
    res = {"caminho": str(saida_pdf), "paginas": paginas, "tamanho_kb": round(len(pdf) / 1024, 1),
           "segundos_compilacao": round(segundos, 3)}
    msgs = list(dict.fromkeys(getattr(w, "message", str(w)) for w in alertas or []))
    fontes_fora = [m.split(":", 1)[1].strip() for m in msgs if m.startswith("unknown font family:")]
    avisos = [m for m in msgs if not m.startswith("unknown font family:")]
    if fontes_fora:
        avisos.insert(0, "Fontes não instaladas nesta máquina (o Typst usou a próxima da lista do template, ou a "
                         f"padrão): {', '.join(fontes_fora)}")
    if avisos:
        res["avisos_typst"] = avisos[:10]
    return res


# --------------------------------------------------------------------------------------------
# Imagens de páginas e lado a lado
# --------------------------------------------------------------------------------------------

def _pagina_png(caminho: Path, indice: int, dpi: float):
    """PIL.Image da página (índice 0) de um PDF, ou a própria imagem se o arquivo for foto."""
    from PIL import Image, ImageOps
    if caminho.suffix.lower() in EXT_IMAGEM:
        im = ImageOps.exif_transpose(Image.open(caminho)).convert("RGB")
        alvo = int(11.69 * dpi)  # altura de uma página A4 na mesma resolução
        im.thumbnail((alvo * 2, alvo))
        return im
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(caminho))
    try:
        if indice >= len(doc):
            return None
        return doc[indice].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        doc.close()


def png_bytes(im, max_lado: int | None = None) -> bytes:
    if max_lado and max(im.size) > max_lado:
        im = im.copy()
        im.thumbnail((max_lado, max_lado))
    b = io.BytesIO()
    im.save(b, format="PNG", optimize=True)
    return b.getvalue()


def lado_a_lado(modelo: Path, amostra: Path, destino: Path, pagina_modelo: int = 1, pagina_amostra: int = 1,
                dpi: float = 90) -> Path:
    from PIL import Image, ImageDraw
    a = _pagina_png(modelo, pagina_modelo - 1, dpi)
    b = _pagina_png(amostra, pagina_amostra - 1, dpi)
    if a is None or b is None:
        raise ErroModelo("Página inexistente no modelo ou na amostra para o lado a lado.")
    alt = max(a.height, b.height)
    if a.height != alt:
        a = a.resize((int(a.width * alt / a.height), alt))
    if b.height != alt:
        b = b.resize((int(b.width * alt / b.height), alt))
    gap, topo = 24, 36
    tela = Image.new("RGB", (a.width + b.width + 3 * gap, alt + topo + gap), (228, 231, 235))
    tela.paste(a, (gap, topo))
    tela.paste(b, (2 * gap + a.width, topo))
    d = ImageDraw.Draw(tela)
    d.text((gap, 12), f"MODELO  {modelo.name}  p. {pagina_modelo}", fill=(40, 40, 40))
    d.text((2 * gap + a.width, 12), f"AMOSTRA  {amostra.name}  p. {pagina_amostra}", fill=(40, 40, 40))
    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino, format="PNG", optimize=True)
    return destino


# --------------------------------------------------------------------------------------------
# Análise do PDF modelo
# --------------------------------------------------------------------------------------------

def _hex(cor) -> str | None:
    if cor is None:
        return None
    if isinstance(cor, (int, float)):
        cor = (cor,)
    try:
        v = [float(x) for x in cor]
    except (TypeError, ValueError):
        return None
    if len(v) == 1:
        r = g = b = v[0]
    elif len(v) == 3:
        r, g, b = v
    elif len(v) == 4:
        c, m, y, k = v
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return None
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(x * 255))) for x in (r, g, b)))


def _fonte(nome: str | None) -> str:
    n = str(nome or "")
    return n.split("+", 1)[1] if re.match(r"^[A-Z]{6}\+", n) else n


def _estilo(fonte: str) -> str:
    f = fonte.lower()
    partes = []
    if any(x in f for x in ("bold", "black", "heavy", "semibold", "demi")):
        partes.append("negrito")
    if any(x in f for x in ("italic", "oblique")):
        partes.append("itálico")
    return " ".join(partes) or "normal"


def _r(x: float) -> float:
    return round(x * MM, 1)


def analisar(caminho: Path, paginas: list[int] | None, dpi: float, pasta_saida: Path, max_paginas: int = 3,
             max_linhas: int = 120) -> tuple[dict, list[bytes]]:
    """Devolve (resumo JSON, [PNG de cada página]). Imagens embutidas vão para pasta_saida."""
    if not caminho.is_file():
        raise ErroModelo(f"Arquivo não encontrado: {caminho}")
    pasta_saida.mkdir(parents=True, exist_ok=True)
    ext = caminho.suffix.lower()
    if ext in EXT_IMAGEM:
        im = _pagina_png(caminho, 0, dpi)
        return ({"arquivo": caminho.name, "tipo": "imagem", "paginas_total": 1,
                 "largura_px": im.width, "altura_px": im.height,
                 "observacao": ("Foto ou digitalização: não há texto nem fontes para extrair. Leia o layout pela "
                                "imagem; peça ao cliente o PDF original se existir.")}, [png_bytes(im)])
    if ext != ".pdf":
        raise ErroModelo(f"Formato não aceito: {ext}. Mande PDF (Word salvo como PDF serve) ou foto (PNG ou JPG).")
    import pdfplumber
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    doc = pdfium.PdfDocument(str(caminho))
    total = len(doc)
    pedidas = [p for p in (paginas or list(range(1, total + 1))) if 1 <= int(p) <= total]
    avisos = []
    if len(pedidas) > max_paginas:
        avisos.append(f"Analisei {max_paginas} de {len(pedidas)} páginas pedidas (teto por chamada). Peça as outras "
                      "em paginas=[...].")
        pedidas = pedidas[:max_paginas]
    resumo_paginas, imagens_png = [], []
    cores_texto, cores_area, cores_linha, fontes = Counter(), Counter(), Counter(), Counter()
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", caminho.stem)[:40]
    with pdfplumber.open(str(caminho)) as pdf:
        for num in pedidas:
            pg = pdf.pages[num - 1]
            W, H = float(pg.width), float(pg.height)
            linhas = []
            segmentos = []
            for ln in pg.extract_text_lines(return_chars=True, strip=True):
                # uma linha visual vira vários blocos quando há um vão grande (colunas, rótulo e valor em células)
                atual: list = []
                for ch in sorted(ln.get("chars", []), key=lambda c: c["x0"]):
                    if atual and ch["x0"] - atual[-1]["x1"] > max(float(ch.get("size", 8)) * 1.6, 5):
                        segmentos.append(atual)
                        atual = []
                    atual.append(ch)
                if atual:
                    segmentos.append(atual)
            for seg in segmentos:
                chars = [c for c in seg if c.get("text", "").strip()]
                if not chars:
                    continue
                partes, ant = [], None
                for c in seg:  # o PDF não guarda o espaço como caractere: o vão vira espaço
                    if ant is not None and c["x0"] - ant["x1"] > float(c.get("size", 8)) * 0.15 and c.get("text") != " ":
                        partes.append(" ")
                    partes.append(c.get("text", ""))
                    ant = c
                ln = {"text": re.sub(r"\s+", " ", "".join(partes)).strip(), "x0": min(c["x0"] for c in chars),
                      "x1": max(c["x1"] for c in chars), "top": min(c["top"] for c in chars)}
                f = Counter(_fonte(c.get("fontname")) for c in chars).most_common(1)[0][0]
                tam = Counter(round(float(c.get("size", 0)), 1) for c in chars).most_common(1)[0][0]
                cor = Counter(_hex(c.get("non_stroking_color")) for c in chars).most_common(1)[0][0]
                for c in chars:
                    cores_texto[_hex(c.get("non_stroking_color"))] += 1
                    fontes[(_fonte(c.get("fontname")), round(float(c.get("size", 0)), 1))] += 1
                texto = ln["text"]
                linhas.append({"texto": texto[:120] + ("..." if len(texto) > 120 else ""),
                               "x_mm": _r(ln["x0"]), "y_mm": _r(ln["top"]), "largura_mm": _r(ln["x1"] - ln["x0"]),
                               "fonte": f, "tamanho_pt": tam, "estilo": _estilo(f), "cor": cor,
                               "alinhamento": ("centro" if abs((ln["x0"] + ln["x1"]) / 2 - W / 2) < 6 and ln["x0"] > W * 0.2
                                               else "direita" if W - ln["x1"] < W * 0.2 and ln["x0"] > W * 0.45 else "esquerda")})
            areas = []
            for r in pg.rects + [c for c in pg.curves if c.get("fill")]:
                w, h = float(r.get("width", 0)), float(r.get("height", 0))
                if r.get("fill"):
                    cor = _hex(r.get("non_stroking_color"))
                    if cor and cor != "#FFFFFF" and w * h < W * H * 0.9:
                        cores_area[cor] += round(w * h)
                        if w * h > 400:
                            areas.append({"x_mm": _r(r["x0"]), "y_mm": _r(r["top"]), "largura_mm": _r(w),
                                          "altura_mm": _r(h), "cor": cor})
                if r.get("stroke"):
                    cor = _hex(r.get("stroking_color"))
                    if cor:
                        cores_linha[cor] += 1
            for l in pg.lines:
                cor = _hex(l.get("stroking_color"))
                if cor:
                    cores_linha[cor] += 1
            # imagens embutidas
            imgs = []
            page = doc[num - 1]
            for k, obj in enumerate(page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,), max_depth=3), 1):
                try:
                    esq, baixo, dir_, topo = obj.get_bounds()
                    try:  # render=True aplica a máscara (transparência do logo); sem ela, o fundo sai preto
                        pil = obj.get_bitmap(render=True).to_pil()
                        if pil.mode == "RGBA" and pil.getchannel("A").getextrema()[0] == 255:
                            pil = pil.convert("RGB")
                    except Exception:
                        pil = obj.get_bitmap(render=False).to_pil()
                    arq = pasta_saida / f"{base}_p{num}_imagem{k}.png"
                    if pil.mode not in ("RGB", "RGBA", "L", "LA"):
                        pil = pil.convert("RGBA")
                    pil.save(arq, format="PNG")
                    y_mm = _r(H - topo)
                    larg, alt = _r(dir_ - esq), _r(topo - baixo)
                    imgs.append({"arquivo": str(arq), "x_mm": _r(esq), "y_mm": y_mm, "largura_mm": larg,
                                 "altura_mm": alt, "pixels": list(pil.size),
                                 "candidata_a_logo": bool(y_mm < H * MM * 0.2 and larg < W * MM * 0.35 and alt < 40)})
                except Exception as ex:
                    avisos.append(f"Página {num}: não consegui extrair a imagem {k} ({type(ex).__name__}).")
                if k >= 30:
                    avisos.append(f"Página {num}: mais de 30 imagens; parei nas 30 primeiras.")
                    break
            xs = [l["x_mm"] for l in linhas] + [i["x_mm"] for i in imgs]
            xe = [l["x_mm"] + l["largura_mm"] for l in linhas] + [i["x_mm"] + i["largura_mm"] for i in imgs]
            ys = [l["y_mm"] for l in linhas] + [i["y_mm"] for i in imgs]
            ye = [l["y_mm"] + l["tamanho_pt"] * MM for l in linhas] + [i["y_mm"] + i["altura_mm"] for i in imgs]
            margens = None
            if xs:
                margens = {"esquerda": round(min(xs), 1), "direita": round(W * MM - max(xe), 1),
                           "topo": round(min(ys), 1), "base": round(H * MM - max(ye), 1)}
            cortadas = len(linhas) > max_linhas
            resumo_paginas.append({"pagina": num, "largura_mm": _r(W), "altura_mm": _r(H),
                                   "orientacao": "paisagem" if W > H else "retrato",
                                   "margens_estimadas_mm": margens, "linhas_de_texto": linhas[:max_linhas],
                                   "linhas_omitidas": max(0, len(linhas) - max_linhas) if cortadas else 0,
                                   "areas_preenchidas": sorted(areas, key=lambda a: -a["largura_mm"] * a["altura_mm"])[:15],
                                   "imagens": imgs})
            imagens_png.append(png_bytes(_pagina_png(caminho, num - 1, dpi)))
    doc.close()
    resumo = {
        "arquivo": caminho.name, "tipo": "pdf", "paginas_total": total, "paginas_analisadas": pedidas,
        "fontes_mais_usadas": [{"fonte": f, "tamanho_pt": t, "estilo": _estilo(f), "caracteres": n}
                               for (f, t), n in fontes.most_common(8)],
        "cores_do_texto": [{"cor": c, "caracteres": n} for c, n in cores_texto.most_common(6) if c],
        "cores_das_areas_preenchidas": [{"cor": c, "area_pt2": n} for c, n in cores_area.most_common(6)],
        "cores_das_linhas": [{"cor": c, "tracos": n} for c, n in cores_linha.most_common(6)],
        "paginas": resumo_paginas, "pasta_das_imagens": str(pasta_saida),
    }
    if avisos:
        resumo["avisos"] = avisos
    if not any(p["linhas_de_texto"] for p in resumo_paginas):
        resumo["observacao"] = "Nenhum texto extraído: o PDF parece digitalizado (imagem). Leia o layout pelas imagens."
    return resumo, imagens_png


# --------------------------------------------------------------------------------------------
# Geração ponta a ponta (contrato + compilação), usada pela ferramenta gerar_pdf_modelo e pelos testes
# --------------------------------------------------------------------------------------------

def _nome_pdf(base: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", base.replace(".", "-")).strip("_") + ".pdf"


def gerar(estrutura: dict, preenchimentos: list, fid, texto_typ: str, pasta_modelo: Path | None,
          nome_modelo: str, mapeamento: dict | None, arquivos_extra: list[str] | None, empresa: str | None,
          logo: str | None, variaveis: dict | None, modo: str, pasta_saida: Path, max_fotos: int = 200,
          comparar_com: str | None = None, pagina_comparada: int = 1,
          aparencia: dict | None = None) -> tuple[dict, bytes | None]:
    """Monta a pasta do trabalho, grava dados.json e compila. Devolve (resultado, PNG do lado a lado ou None)."""
    verificar_template(texto_typ)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = re.sub(r"[^A-Za-z0-9_\-]+", "_", nome_modelo)[:40] or "modelo"
    trabalho = pasta_saida / f"trabalho_{base}_{fid}_{carimbo}"
    n = 2
    while trabalho.exists():  # duas gerações no mesmo segundo não dividem a pasta
        trabalho = pasta_saida / f"trabalho_{base}_{fid}_{carimbo}_{n}"
        n += 1
    fontes, logo_rel = preparar_trabalho(trabalho, texto_typ, pasta_modelo, arquivos_extra, logo)
    mt = contrato.Montador(estrutura, fid, trabalho, max_fotos)
    t0 = time.perf_counter()
    try:
        ps = [mt.preenchimento(p) for p in preenchimentos]
    finally:
        mt.fechar()
    t_dados = time.perf_counter() - t0
    dados = {"documento": contrato.documento(estrutura, empresa, logo_rel, variaveis, len(ps), aparencia),
             "formulario": contrato.formulario(estrutura, fid), "preenchimentos": ps}
    sem_campo = contrato.aplicar_mapeamento(dados, mapeamento)
    aparencia_sem_campo = contrato.aplicar_aparencia(dados, aparencia)

    def gravar(d: dict) -> None:
        (trabalho / "dados.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    arquivos = []
    if modo == "um_por_preenchimento" and len(ps) > 1:
        for p in ps:
            d = {**dados, "documento": {**dados["documento"], "qtd_preenchimentos": 1}, "preenchimentos": [p]}
            gravar(d)
            destino = pasta_saida / _nome_pdf(f"{base}_{fid}_{p['id']}")
            arquivos.append({**compilar(trabalho, destino, fontes), "preenchimentos": [p["id"]]})
        gravar(dados)
    else:
        gravar(dados)
        nome = f"{base}_{fid}_{ps[0]['id']}" if len(ps) == 1 else f"{base}_{fid}_{len(ps)}_preenchimentos_{carimbo}"
        destino = pasta_saida / _nome_pdf(nome)
        arquivos.append({**compilar(trabalho, destino, fontes), "preenchimentos": [p["id"] for p in ps]})
    res = {"modelo": nome_modelo, "arquivos": arquivos, "pasta_do_trabalho": str(trabalho),
           "modo": "um_pdf" if len(arquivos) == 1 else "um_por_preenchimento",
           "segundos_montando_dados": round(t_dados, 3),
           "segundos_compilando": round(sum(a["segundos_compilacao"] for a in arquivos), 3),
           "fotos": {"no_trabalho": mt.fotos_gravadas, "indisponiveis": mt.fotos_indisponiveis,
                     "fora_do_limite": mt.fotos_fora, "tentativas": mt.bx.tentativas, "baixadas": mt.bx.baixadas,
                     "mb_baixados": round(mt.bx.bytes / 1e6, 2), "motivos_de_falha": mt.bx.motivos}}
    if mt.bx.simular:  # no_trabalho inclui as simuladas (COLETUM_FOTOS_TESTE, só no teste local)
        res["fotos"].update({"simuladas": mt.fotos_simuladas, "motivos_das_simuladas": mt.bx.motivos_simuladas})
        res["fotos_simuladas"] = mt.fotos_simuladas
    if aparencia:
        res["aparencia"] = aparencia
    if aparencia_sem_campo:
        res["aparencia_sem_campo"] = aparencia_sem_campo
    if mapeamento:
        res["mapeamento"] = {"rotulos": len([k for k in mapeamento if not str(k).startswith("_")]),
                             "sem_campo": sem_campo}
    png = None
    if comparar_com:
        alvo = pasta_saida / f"lado_a_lado_{base}_{fid}_{carimbo}.png"
        lado_a_lado(Path(comparar_com).expanduser(), Path(arquivos[0]["caminho"]), alvo, pagina_comparada,
                    pagina_comparada)
        res["lado_a_lado"] = str(alvo)
        from PIL import Image
        png = png_bytes(Image.open(alvo), max_lado=1400)
    return res, png
