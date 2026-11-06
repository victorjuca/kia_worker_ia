"""
circulo.png y portada.jpg del proyecto, igual que CancionForm de kia (creaCirculo / creaPortadaYoutube /
defineParamMiniatura con ajuste automatico del nombre).

El texto se dibuja como en Java2D: Arial Black con negrita sintetica (Font.BOLD sobre una fuente que solo trae
el estilo normal: cada letra crece tamano/32 hacia la derecha y hacia arriba, y su avance tambien), contorno gris #d9d9d9 de
max(5, tamano/16) px con uniones redondas, relleno negro y sombra difuminada desplazada 12 px.
"""
import math
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CIRCULO_MAX = 400
SOMBRA_DESPLAZAMIENTO, SOMBRA_RADIO, SOMBRA_ALFA = 12, 6, 200
GRIS_CONTORNO = (0xD9, 0xD9, 0xD9)

# configuracion.properties de kia (img.tam1..4 e img.artista.*)
_ARTISTA = dict(nom_artista_x=59, nom_artista_y=694, nom_artista_tam_font=42)
# ajuste automatico del nombre (fondo de 1280 x 720)
AUTO_Y_MIN, AUTO_Y_MAX, AUTO_X_MAX, AUTO_MARGEN_TRIANGULO = 130, 630, 1255, 25
AUTO_FONT_MIN, AUTO_FONT_MAX, AUTO_INTERLINEA, AUTO_CENTRO_X, AUTO_ESCALA = 40, 200, 1.05, 640.0, 0.80


@dataclass
class Parametros:
    """ParametroMiniatura de kia (tabla portada)."""
    tamano_letra_ind: int
    tamano_font: int
    inicio_y: int
    salto_linea: int
    ancho_circulo: int
    plano_x_circulo: int
    plano_y_circulo: int
    nom_artista_x: int = _ARTISTA["nom_artista_x"]
    nom_artista_y: int = _ARTISTA["nom_artista_y"]
    nom_artista_tam_font: int = _ARTISTA["nom_artista_tam_font"]


BASE = [
    Parametros(0, 147, 394, 271, 350, 880, 80),
    Parametros(0, 190, 193, 355, 350, 880, 80),
    Parametros(0, 144, 44, 332, 350, 880, 80),
    Parametros(0, 164, 224, 372, 350, 880, 80),
]


# ------------------------------------------------------------------ texto como Java2D

class Fuente:
    def __init__(self, archivo: Path):
        if not Path(archivo).is_file():
            raise FileNotFoundError(f"No existe la fuente {archivo} (Arial Black: ariblk.ttf)")
        self.archivo = str(archivo)

    @lru_cache(maxsize=256)
    def _pil(self, tam: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.archivo, tam, layout_engine=ImageFont.Layout.BASIC)

    def posiciones(self, texto: str, tam: int, negrita: bool, fraccional: bool = True) -> list[tuple[str, float]]:
        """x de cada letra respecto al origen (GlyphVector sin kerning; con negrita el avance crece tam/32)."""
        f, extra, x, r = self._pil(tam), (tam / 32.0 if negrita else 0.0), 0.0, []
        for ch in texto:
            r.append((ch, x))
            # avance entero (con hinting) + lo de la negrita sin redondear; el espacio no tiene contorno y no engorda
            x += f.getlength(ch) + (extra if ch.strip() else 0.0)
        return r

    def mascara(self, tam_img: tuple[int, int], texto: str, tam: int, x: float, y: float, negrita: bool,
                crece: float = 0.0, antialias: bool = True, fraccional: bool = False,
                posiciones: list[tuple[str, float]] | None = None) -> Image.Image:
        """Silueta (L) del texto con la linea base en (x, y); 'crece' px extra alrededor (contorno)."""
        f = self._pil(tam)
        m = Image.new("L", tam_img, 0)
        d = ImageDraw.Draw(m)
        if not antialias:
            d.fontmode = "1"
        # negrita sintetica (FT_Outline_Embolden de Java): la letra engorda tam/32 y crece a la derecha y arriba
        b = tam / 64.0 if negrita else 0.0
        for ch, dx in posiciones if posiciones is not None else self.posiciones(texto, tam, negrita, fraccional):
            if ch.strip():
                d.text((x + dx + b, y - b), ch, font=f, fill=255, anchor="ls", stroke_width=b + crece, stroke_fill=255)
        return m

    def caja(self, texto: str, tam: int, negrita: bool = True, fraccional: bool = False):
        """Limites visuales (x0, y0, x1, y1) respecto al origen en la linea base (getVisualBounds de Java):
        se dibuja 4 veces mas grande y se toma cualquier pixel tocado, para acercarse a los limites del contorno."""
        k = 4
        t = tam * k
        x_fin = self.posiciones(texto, tam, negrita, fraccional)[-1][1] * k + t * 2 if texto else t
        ancho, alto = int(x_fin + t * 2), t * 3
        m = self.mascara((ancho, alto), texto, t, t, t * 2, negrita,
                         posiciones=[(c, x * k) for c, x in self.posiciones(texto, tam, negrita, fraccional)])
        b = m.getbbox()
        if b is None:
            return 0.0, 0.0, 0.0, 0.0
        return (b[0] - t) / k, (b[1] - t * 2) / k, (b[2] - t) / k, (b[3] - t * 2) / k


def _sombra(lienzo: Image.Image, silueta: Image.Image):
    """dibujaSombra: la silueta en negro (alfa 200) difuminada (caja de 13 px, 2 pasadas) y recorrida 12 px."""
    a = silueta.point(lambda v: v * SOMBRA_ALFA // 255)
    for _ in range(2):
        a = a.filter(ImageFilter.BoxBlur(SOMBRA_RADIO))
    capa = Image.new("L", lienzo.size, 0)
    capa.paste(a, (SOMBRA_DESPLAZAMIENTO, SOMBRA_DESPLAZAMIENTO))
    negro = Image.new("RGBA", lienzo.size, (0, 0, 0, 255))
    negro.putalpha(capa)
    lienzo.alpha_composite(negro)


def _pinta(lienzo: Image.Image, mascara: Image.Image, color):
    capa = Image.new("RGBA", lienzo.size, color + (255,))
    capa.putalpha(mascara)
    lienzo.alpha_composite(capa)


# ------------------------------------------------------------------ parametros

def arma_renglones(nombre: str) -> list[str]:
    """1 a 3 palabras: una por renglon; 4 o mas: de dos en dos."""
    lp = (nombre or "").split()
    if len(lp) <= 3:
        return lp
    return [" ".join(lp[i:i + 2]) for i in range(0, len(lp), 2)]


def _borde_triangulo(y: float) -> float:
    d = min(1.0, abs(y - 360) / 360.0)
    return 5 + 160 * (1 - d)


def _acomodo(fuente: Fuente, ren: list[str], f: int, forzar: bool):
    centro_y = (AUTO_Y_MIN + AUTO_Y_MAX) / 2.0
    gap = AUTO_INTERLINEA * f
    contorno = max(5.0, f / 16.0)
    cajas = [fuente.caja(r, f, fraccional=True) for r in ren]
    arriba = min(i * gap + c[1] - contorno / 2 for i, c in enumerate(cajas))
    abajo = max(i * gap + c[3] + contorno / 2 for i, c in enumerate(cajas))
    if abajo - arriba > AUTO_Y_MAX - AUTO_Y_MIN and not forzar:
        return None
    b0 = centro_y - (arriba + abajo) / 2
    lo, hi = -math.inf, math.inf
    for i, c in enumerate(cajas):
        b = b0 + i * gap
        sup, inf = b + c[1], b + c[3]
        y_cercano = max(sup, min(360, inf))
        mitad = (c[2] - c[0]) / 2 + contorno / 2
        lo = max(lo, _borde_triangulo(y_cercano) + AUTO_MARGEN_TRIANGULO + mitad)
        hi = min(hi, AUTO_X_MAX - mitad)
    if lo > hi and not forzar:
        return None
    centro_x = max(lo, min(hi, AUTO_CENTRO_X)) if lo <= hi else lo
    return f, gap, b0, centro_x


def ajusta_automatico(fuente: Fuente, nombre: str, base: Parametros) -> Parametros:
    """ajustaTextoAutomatico: la letra mas grande que cabe en la franja amarilla, reducida al 80 %."""
    ren = arma_renglones(nombre)
    if not ren:
        return replace(base)
    maximo = None
    f = AUTO_FONT_MAX
    while f >= AUTO_FONT_MIN and maximo is None:
        maximo = _acomodo(fuente, ren, f, f - 2 < AUTO_FONT_MIN)
        f -= 2
    if maximo is None:
        return replace(base)
    f = max(AUTO_FONT_MIN, int(math.floor(maximo[0] * AUTO_ESCALA + 0.5)))
    ac = _acomodo(fuente, ren, f, True) or maximo
    tam, gap, b0, cx = ac
    return replace(base, tamano_font=tam, salto_linea=int(math.floor(gap * 2 + 0.5)),
                   inicio_y=int(math.floor(b0 * 2 - 480 + 0.5)), tamano_letra_ind=int(math.floor(cx - 640 + 0.5)))


def define_parametros(fuente: Fuente, nombre: str, auto: bool = True) -> Parametros:
    """defineParamMiniatura: por numero de palabras (1, 2, 3, 4+) y ajuste automatico (img.auto.ajuste)."""
    n = len((nombre or "").split())
    base = BASE[min(max(n, 1), 4) - 1]
    return ajusta_automatico(fuente, nombre, base) if auto else replace(base)


# ------------------------------------------------------------------ circulo

def _escala_cuadrado(img: Image.Image, lado: int) -> Image.Image:
    w = img.width
    while w // 2 >= lado:
        w //= 2
        img = img.resize((w, w), Image.Resampling.BICUBIC)
    return img if w == lado else img.resize((lado, lado), Image.Resampling.BICUBIC)


def crea_circulo(imagen: Path, destino: Path) -> bool:
    """Recorte cuadrado al centro, maximo 400 px, fuera del circulo transparente."""
    src = Image.open(imagen).convert("RGBA")
    lado = min(src.size)
    x0, y0 = (src.width - lado) // 2, (src.height - lado) // 2
    cuadro = src.crop((x0, y0, x0 + lado, y0 + lado))
    if lado > CIRCULO_MAX:
        cuadro, lado = _escala_cuadrado(cuadro, CIRCULO_MAX), CIRCULO_MAX
    yy, xx = np.mgrid[0:lado, 0:lado]
    r = lado / 2.0
    dentro = ((xx + 0.5 - r) ** 2 + (yy + 0.5 - r) ** 2) <= r * r     # el clip de Java2D no se suaviza
    a = np.array(cuadro)
    a[..., 3] = np.where(dentro, a[..., 3], 0)
    Image.fromarray(a, "RGBA").save(destino, "PNG")
    return True


# ------------------------------------------------------------------ portada

def crea_portada(fondo: Path, fuente: Fuente, nombre: str, artista: str, circulo: Path | None,
                 p: Parametros, destino: Path):
    """creaPortadaYoutube (sin texto de caratula ni arrastre): circulo con sombra, nombre y artista."""
    lienzo = Image.open(fondo).convert("RGBA")
    W, H = lienzo.size

    if circulo is not None and circulo.is_file():
        im = Image.open(circulo).convert("RGBA")
        if im.width > CIRCULO_MAX:
            _escala_cuadrado(im, CIRCULO_MAX).save(circulo, "PNG")     # circulos viejos: se reducen al usarlos
        c = im.resize((p.ancho_circulo, p.ancho_circulo), Image.Resampling.BOX)
        silueta = Image.new("L", lienzo.size, 0)
        silueta.paste(c.getchannel("A"), (p.plano_x_circulo, p.plano_y_circulo))
        _sombra(lienzo, silueta)
        lienzo.alpha_composite(c, (p.plano_x_circulo, p.plano_y_circulo)) if p.plano_x_circulo >= 0 and p.plano_y_circulo >= 0 \
            else lienzo.paste(c, (p.plano_x_circulo, p.plano_y_circulo), c)

    renglones = arma_renglones(nombre)
    centro_x = W // 2 + p.tamano_letra_ind
    tam = p.tamano_font
    contorno = max(5.0, tam / 16.0)
    lugares = []
    y_ren = p.inicio_y
    for r in renglones:
        x0, _, x1, _ = fuente.caja(r, tam)
        x = int(math.floor(centro_x - x0 - (x1 - x0) / 2 + 0.5))
        y = (480 + y_ren) // 2 if 480 + y_ren >= 0 else -((-(480 + y_ren)) // 2)
        lugares.append((r, x, y))
        y_ren += p.salto_linea
    for r, x, y in lugares:          # primero todas las sombras
        _sombra(lienzo, fuente.mascara(lienzo.size, r, tam, x, y, True, crece=contorno / 2))
    for r, x, y in lugares:          # luego contorno gris y relleno negro
        _pinta(lienzo, fuente.mascara(lienzo.size, r, tam, x, y, True, crece=contorno / 2), GRIS_CONTORNO)
        _pinta(lienzo, fuente.mascara(lienzo.size, r, tam, x, y, True), (0, 0, 0))

    # artista: Arial Black normal, blanco, sin suavizado (drawString de Graphics sin antialias)
    _pinta(lienzo, fuente.mascara(lienzo.size, artista, p.nom_artista_tam_font, p.nom_artista_x, p.nom_artista_y,
                                  False, antialias=False), (255, 255, 255))

    rgb = Image.new("RGB", lienzo.size, (255, 255, 255))
    rgb.paste(lienzo, mask=lienzo.getchannel("A"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.suffix.lower() in (".jpg", ".jpeg"):
        rgb.save(destino, "JPEG", quality=92)
    else:
        rgb.save(destino, "PNG")
