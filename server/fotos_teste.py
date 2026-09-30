"""Fotos simuladas, SÓ para o ambiente local de teste.

No ambiente local, os links dos anexos apontam para o armazenamento de desenvolvimento, onde as fotos
não existem (403). Com COLETUM_FOTOS_TESTE ligado ("1", "true" ou "sim", na variável de ambiente ou no
.env de teste), cada foto cujo download real falha (403, 404, erro de rede) vira uma imagem gerada aqui,
para ver layout e fluxo com fotos. A imagem é fixa por link (cor e rabisco saem do hash do link) e traz
"FOTO DE TESTE", o rótulo do campo e os 8 primeiros caracteres do hash; assinatura vira um rabisco.
Nada daqui troca o host do link nem tenta outro endereço: só entra DEPOIS que o download real falhou.
Desligada (o padrão, e o caso de todo cliente), nada muda. As respostas marcam o que foi simulado
(fotos_simuladas; situação "simulada" no índice de anexos) para ninguém confundir com foto real.
"""
from __future__ import annotations

import colorsys
import hashlib
import io
import random
from pathlib import Path
from urllib.parse import urlparse

from api import config

VARIAVEL = "COLETUM_FOTOS_TESTE"
LIGADO = {"1", "true", "sim"}
# extensões que viram imagem simulada ("" = link sem extensão); arquivo que não é foto segue falhando
EXT_IMAGEM = {"", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff"}
AVISO = ("{n} foto(s) desta resposta são SIMULADAS ({var} ligado, só no ambiente local de teste): o download "
         "real falhou e entrou uma imagem gerada no lugar. Não são as fotos do cliente.")


def ligado() -> bool:
    return (config(VARIAVEL) or "").strip().lower() in LIGADO


def aviso(n: int) -> str:
    return AVISO.format(n=n, var=VARIAVEL)


def _ext(link: str) -> str:
    return Path(urlparse(link or "").path).suffix.lower()


def simulavel(link: str) -> bool:
    return _ext(link) in EXT_IMAGEM


def eh_assinatura(link: str, tipo: str | None = None) -> bool:
    if tipo == "signature":
        return True
    return Path(urlparse(link or "").path).name.lower().startswith(("signature", "assinatura"))


def _fonte(tamanho: int, negrito: bool = False):
    """Bitstream Vera, que vem com o reportlab quando ele está instalado (tem acento); sem ela, a fonte padrão do Pillow."""
    from PIL import ImageFont
    try:
        import reportlab
        pasta = Path(reportlab.__file__).parent / "fonts"
        return ImageFont.truetype(str(pasta / ("VeraBd.ttf" if negrito else "Vera.ttf")), tamanho)
    except Exception:
        pass
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:  # Pillow antigo, sem tamanho
        return ImageFont.load_default()


def _foto(h: bytes, rotulo: str | None, formato: str) -> bytes:
    from PIL import Image, ImageDraw
    w, a = 1200, 900
    matiz = h[0] / 255
    fundo = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(matiz, 0.45, 0.80))
    traco = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(matiz, 0.55, 0.62))
    im = Image.new("RGB", (w, a), fundo)
    d = ImageDraw.Draw(im)
    passo = 50 + h[1] % 40
    for k in range(-a, w, passo):
        d.line([(k, 0), (k + a, a)], fill=traco, width=6)
    d.rectangle([12, 12, w - 13, a - 13], outline=(255, 255, 255), width=8)
    d.rectangle([90, 250, w - 90, 650], fill=(255, 255, 255))
    d.text((w // 2, 350), "FOTO DE TESTE", fill=(20, 20, 20), font=_fonte(92, True), anchor="mm")
    if rotulo:
        texto = rotulo if len(rotulo) <= 48 else rotulo[:45] + "..."
        d.text((w // 2, 480), texto, fill=(60, 60, 60), font=_fonte(44), anchor="mm")
    d.text((w // 2, 580), h.hex()[:8], fill=(110, 110, 110), font=_fonte(36), anchor="mm")
    saida = io.BytesIO()
    if formato == "PNG":
        im.save(saida, format="PNG", optimize=True)
    else:
        im.save(saida, format="JPEG", quality=80, optimize=True)
    return saida.getvalue()


def _assinatura(h: bytes, formato: str) -> bytes:
    from PIL import Image, ImageDraw
    w, a = 600, 250
    transparente = formato == "PNG"
    im = Image.new("RGBA" if transparente else "RGB", (w, a), (255, 255, 255, 0) if transparente else (255, 255, 255))
    d = ImageDraw.Draw(im)
    rnd = random.Random(h)
    x, pontos = 50, []
    while x < w - 50:
        pontos.append((x, rnd.randint(70, 180)))
        x += rnd.randint(30, 70)
    d.line(pontos, fill=(20, 30, 90, 255) if transparente else (20, 30, 90), width=5, joint="curve")
    d.text((w // 2, a - 22), f"assinatura de teste · {h.hex()[:8]}", fill=(120, 120, 120, 255) if transparente
           else (120, 120, 120), font=_fonte(18), anchor="mm")
    saida = io.BytesIO()
    im.save(saida, format=formato, **({"optimize": True} if formato == "PNG" else {"quality": 85}))
    return saida.getvalue()


def gerar(link: str, rotulo: str | None = None, tipo: str | None = None) -> bytes:
    """Imagem simulada para o link: JPEG de 1200x900 (PNG se o link termina em .png); assinatura vira um
    rabisco em PNG transparente (JPEG de fundo branco se o link termina em .jpg). Fixa por link."""
    h = hashlib.sha256((link or "").encode("utf-8")).digest()
    ext = _ext(link)
    if eh_assinatura(link, tipo):
        return _assinatura(h, "JPEG" if ext in (".jpg", ".jpeg") else "PNG")
    return _foto(h, rotulo, "PNG" if ext == ".png" else "JPEG")
