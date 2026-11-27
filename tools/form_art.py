"""form_art.py - Desenhos da forma de Medachange de um bot proprio (data/bots, campo "medachange").

Uso:
  python tools/form_art.py picture ORIGEM.png DESTINO.png   desenho grande da forma (uma peca so, na perna)
  python tools/form_art.py mini ORIGEM.png DESTINO.png      mini da forma (32x24, veiculo de uma peca)

picture: tamanho de sprite do GBA (anim_molds.OBJ_SIZES, ate 64x64); sai PNG indexado (indice 0 = transparente) com
ate 15 cores (check_template.reduce_colors: libimagequant). mini: 32x24; os cantos de cima (8x8) nao tem pedaco do mini
que os cubra (avisa); as cores sao reduzidas no build (gfx_port.form_mini_components), aqui so copia e confere.
Imprime "ok LARGxALT CORES" no fim (a janela Decomp Project le essa linha).
"""
import sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from anim_molds import OBJ_SIZES                       # noqa: E402
from check_template import reduce_colors, snap          # noqa: E402


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ("picture", "mini"):
        raise SystemExit(__doc__)
    kind, src, dst = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    dst.parent.mkdir(parents=True, exist_ok=True)
    px = img.load()
    if kind == "mini":
        if (w, h) != (32, 24):
            raise SystemExit(f"o mini da forma e 32x24 (largura x altura); este tem {w}x{h}")
        lost = sum(1 for x in list(range(8)) + list(range(24, 32)) for y in range(8) if px[x, y][3] >= 128)
        if lost:
            print(f"aviso: {lost} pixels nos cantos de cima (8x8) ficam de fora do mini")
        img.save(dst)
        cols = len({snap(px[x, y][:3]) for y in range(h) for x in range(w) if px[x, y][3] >= 128})
        print(f"ok {w}x{h} {cols}")
        return
    if (w, h) not in OBJ_SIZES:
        raise SystemExit(f"{w}x{h} nao e tamanho de sprite do GBA ({', '.join(f'{a}x{b}' for a, b in sorted(OBJ_SIZES))})")
    pixels = [px[x, y][:3] for y in range(h) for x in range(w) if px[x, y][3] >= 128]
    if not pixels:
        raise SystemExit("desenho vazio (tudo transparente)")
    cmap, used = reduce_colors(pixels)
    colors = sorted(set(cmap.values()))
    index = {c: i + 1 for i, c in enumerate(colors)}
    out = Image.new("P", (w, h), 0)
    out.putpalette([255, 0, 255] + [v for c in colors for v in c] + [0] * (768 - 3 * (len(colors) + 1)))
    out.putdata([index[cmap[snap(p[:3])]] if p[3] >= 128 else 0 for p in img.getdata()])
    out.save(dst, transparency=0)
    before = len({snap(c) for c in pixels})
    if used != "-":
        print(f"cores: {before} -> {len(colors)} ({used})")
    print(f"ok {w}x{h} {len(colors)}")


if __name__ == "__main__":
    main()
