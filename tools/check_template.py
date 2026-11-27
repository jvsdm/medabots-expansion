"""
check_template.py - Confere uma pasta de pecas desenhadas (formato do export_template.py) e refaz a folha.

Uso:  python tools/check_template.py art/template_120_sagehorn [--limpar]
      --limpar [--metodo=auto|liq|fusao|maxcov|mediancut]: copias em <pasta>/_limpo com no maximo 15 cores por peca e no mini (o campo "art" do bot aponta para ela)

Para cada PNG: tamanho certo para o molde (registro +0x12/+0x13), transparencia, cores fora da grade
do GBA (canal nao multiplo de 8) e, por peca (todos os pedacos de cabeca / braco dir / braco esq /
pernas juntos), o total de cores visiveis (max. 15; a cor 0 e a transparente).
Reescreve _folha.png (ampliada 4x, rosa = transparente).
"""
import json
import re
import struct
import sys
from pathlib import Path
from PIL import Image, ImageDraw
from medarom import ROOT, GBA_BASE

DESCRIPTORS = 0x3D1D78
MAX_COLORS = 15
OBJ_SIZES = {(8, 8), (16, 16), (32, 32), (64, 64), (16, 8), (32, 8), (32, 16), (64, 32), (8, 16), (8, 32), (16, 32),
             (32, 64)}   # (largura, altura) de sprite do GBA: pedaco noutra medida ganha molde proprio no build


def mold_size(rom, mold):
    rec = struct.unpack_from("<I", rom, DESCRIPTORS + 4 * mold)[0] - GBA_BASE
    return rom[rec + 0x13], rom[rec + 0x12]   # (largura, altura): +0x13 largura, +0x12 altura


def visible_pixels(img):
    """(cor RGB, eh_visivel) por pixel, respeitando paleta + indice/alpha de transparencia."""
    rgba = img.convert("RGBA")
    return [(p[:3], p[3] >= 128) for p in rgba.getdata()]


def snap(c):
    """Cor -> grade do GBA (canal multiplo de 8, 0-248)."""
    return tuple(min(248, int(round(v / 8)) * 8) for v in c)


def group_of(stem):
    """Pecas que dividem uma paleta: os pedacos de cada peca grande; o mini sprite inteiro (8 quadros)."""
    m = re.match(r"large_(cabeca|braco_dir|braco_esq|pernas)_", stem)
    if m:
        return f"large_{m.group(1)}"
    return "mini" if stem.startswith("mini_") else stem


METHODS = ("auto", "liq", "fusao", "maxcov", "mediancut")


def _fusion(pixels):
    """Funde a cor menos importante na mais proxima (custo = distancia x pixels): some com tons de pincel."""
    count = {}
    for c in pixels:
        c = snap(c)
        count[c] = count.get(c, 0) + 1
    merged, live = {c: c for c in count}, dict(count)

    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b))
    while len(live) > MAX_COLORS:
        def nearest(c):
            return min((o for o in live if o != c), key=lambda o: (dist(c, o), -live[o], o))
        rare = min(live, key=lambda c: (dist(c, nearest(c)) * live[c], c))
        target = nearest(rare)
        live[target] += live.pop(rare)
        for c, t in merged.items():
            if t == rare:
                merged[c] = target
    return merged


def _quantize(pixels, method):
    strip = Image.new("RGB", (len(pixels), 1))
    strip.putdata([snap(c) for c in pixels])
    q = strip.quantize(colors=MAX_COLORS, method=method, kmeans=4, dither=Image.Dither.NONE).convert("RGB")
    out = {}
    for src, dst in zip(strip.getdata(), q.getdata()):
        out.setdefault(src, snap(dst))
    return out


def worst_error(pixels, cmap):
    """Maior distancia entre uma cor original e a que ela virou (cada cor distinta conta igual)."""
    return max(sum((x - y) ** 2 for x, y in zip(c, cmap[c])) ** 0.5 for c in {snap(c) for c in pixels})


def reduce_colors(pixels, method="auto"):
    """({cor da grade do GBA: cor final} com no maximo 15 cores, metodo usado). Ate 15: as proprias. Acima:
    fusao (a menos usada vai na mais proxima), maxcov (MAXCOVERAGE do Pillow) ou mediancut; auto = o de menor pior
    erro por cor (a fusao apagava detalhe pequeno de cor distinta, como o vermelho de um chifre; Saikachis 2026-11-23).
    liq = libimagequant (o do pngquant), sem pontilhado: o mais fiel no olho (cabeca do Saikachis: mantem o degrade
    laranja e o vermelho; o maxcov achatava o sombreado). auto = liq quando o Pillow tem libimagequant, senao mediancut.
    O "pior erro" so informa: escolher por ele dava o maxcov, que o usuario achou horrivel (2026-11-24)."""
    cols = sorted({snap(c) for c in pixels})
    if len(cols) <= MAX_COLORS:
        return {c: c for c in cols}, "-"
    cands = {"fusao": lambda: _fusion(pixels), "maxcov": lambda: _quantize(pixels, Image.Quantize.MAXCOVERAGE),
             "mediancut": lambda: _quantize(pixels, Image.Quantize.MEDIANCUT),
             "liq": lambda: _quantize(pixels, Image.Quantize.LIBIMAGEQUANT)}
    if method == "auto":
        from PIL import features
        method = "liq" if features.check_feature("libimagequant") else "mediancut"
    return cands[method](), method


def clean(folder, files, method="auto"):
    """Copias limpas em <pasta>/_limpo: cores na grade do GBA e no maximo 15 visiveis por grupo (pecas grandes:
    todos os pedacos da peca; mini: os 8 quadros juntos); PNG indexado, indice 0 transparente, mesma paleta no grupo.
    Os arquivos originais nao sao tocados. Grava _limpo/_folha.png."""
    out = folder / "_limpo"
    out.mkdir(exist_ok=True)
    groups = {}
    for p in files:
        groups.setdefault(group_of(p.stem), []).append(p)
    log = []
    for key, paths in groups.items():
        imgs = {p: Image.open(p).convert("RGBA") for p in paths}
        pixels = [(r, g, b) for img in imgs.values() for r, g, b, a in img.getdata() if a >= 128]
        cmap, used = reduce_colors(pixels, method)
        count = {}
        for c in pixels:
            t = cmap[snap(c)]
            count[t] = count.get(t, 0) + 1
        palette = sorted(count, key=lambda c: (-count[c], c))
        index = {c: i + 1 for i, c in enumerate(palette)}
        flat = [255, 0, 255] + [v for c in palette for v in c]
        for p, img in imgs.items():
            q = Image.new("P", img.size, 0)
            q.putpalette(flat + [0] * (768 - len(flat)))
            q.putdata([index[cmap[snap((r, g, b))]] if a >= 128 else 0 for r, g, b, a in img.getdata()])
            q.save(out / p.name, transparency=0)
        before = len({snap(c) for c in pixels})
        err = round(worst_error(pixels, cmap)) if pixels else 0
        log.append(f"{key}: {before} -> {len(palette)} cores" + ("" if used == "-" else f" ({used}, pior erro {err})"))
    sheet(sorted(out.glob("*.png")), out / "_folha.png")
    print("limpeza -> " + str(out))
    print("\n".join("  " + line for line in log))


def sheet(paths, dst):
    """Folha com as pecas ampliadas 4x (rosa = transparente) e o tamanho/cores de cada uma."""
    pieces = []
    for p in paths:
        if p.name.startswith("_"):
            continue
        img = Image.open(p)
        pieces.append((p.name, img, len({c for c, vis in visible_pixels(img) if vis})))
    scale, pad, cols_n = 4, 14, 6
    cell_w, cell_h = 64 * scale + pad, 64 * scale + pad + 14
    rows = max(1, (len(pieces) + cols_n - 1) // cols_n)
    out = Image.new("RGB", (cols_n * cell_w, rows * cell_h), (64, 64, 64))
    draw = ImageDraw.Draw(out)
    for n, (name, img, ncolors) in enumerate(pieces):
        x, y = (n % cols_n) * cell_w + 4, (n // cols_n) * cell_h + 4
        draw.text((x, y), f"{name} ({img.width}x{img.height}, {ncolors} cores)", fill=(230, 230, 230))
        big = img.convert("RGBA").resize((img.width * scale, img.height * scale), Image.NEAREST)
        bg = Image.new("RGBA", big.size, (255, 0, 255, 255))
        out.paste(Image.alpha_composite(bg, big).convert("RGB"), (x, y + 14))
    out.save(dst)


def main():
    folder = Path(sys.argv[1])
    if not folder.is_absolute():
        folder = ROOT / folder
    rom = (ROOT / "Medabots - Metabee (Europe).gba").read_bytes()
    files = sorted(p for p in folder.glob("*.png") if not p.name.startswith("_"))
    # tamanhos gravados pelo export_template (peca como a ROM de origem desenha; moldes do Navi e proprios)
    sizes_file = folder / "_tamanhos.json"
    known = {k: tuple(v) for k, v in json.loads(sizes_file.read_text(encoding="utf-8")).items()} if sizes_file.exists() else {}
    problems, parts, notes = [], {}, []
    pieces = []
    for p in files:
        img = Image.open(p)
        m = re.match(r"large_(cabeca|braco_dir|braco_esq|pernas)_\d+_m(\d+)", p.stem)
        expected = known.get(p.name) or (mold_size(rom, int(m.group(2))) if m else (16, 16))
        if img.size != expected:
            if m and img.size in OBJ_SIZES and "_pose" not in p.stem:
                notes.append(f"{p.name}: medida propria {img.size[0]}x{img.size[1]} (molde {expected[0]}x{expected[1]}): "
                             "o build da a este pedaco um molde proprio (anim_molds picture)")
            else:
                problems.append(f"{p.name}: tamanho {img.size[0]}x{img.size[1]}, esperado {expected[0]}x{expected[1]}"
                                + (" (pedaco com poses fica no tamanho do molde)" if "_pose" in p.stem else
                                   " (ou outro tamanho de sprite do GBA)"))
        pixels = visible_pixels(img)
        colors = {c for c, vis in pixels if vis}
        if not any(not vis for _, vis in pixels):
            problems.append(f"{p.name}: nenhum pixel transparente (o fundo virou cor?)")
        off_grid = sorted({c for c in colors if any(v % 8 for v in c)})
        if off_grid:
            problems.append(f"{p.name}: {len(off_grid)} cor(es) fora da grade do GBA (serao arredondadas)")
        key = f"large_{m.group(1)}" if m else "mini"
        parts.setdefault(key, set()).update(tuple(v // 8 for v in c) for c in colors)
        pieces.append((p.name, img, len(colors)))

    report = []
    for key, cols in sorted(parts.items()):
        if key == "mini":
            status = "ok" if len(cols) <= MAX_COLORS else f"PASSOU do limite ({MAX_COLORS}; --limpar reduz)"
            report.append(f"mini sprite: {len(cols)} cores nos 8 quadros - {status}")
            continue
        status = "ok" if len(cols) <= MAX_COLORS else f"PASSOU do limite ({MAX_COLORS})"
        report.append(f"{key}: {len(cols)} cores visiveis - {status}")
        if len(cols) > MAX_COLORS:
            problems.append(f"{key}: {len(cols)} cores somando os pedacos (max. {MAX_COLORS})")

    sheet(files, folder / "_folha.png")

    if "--limpar" in sys.argv:
        method = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--metodo=")), "auto")
        if method not in METHODS:
            raise SystemExit(f"--metodo={method}: use {', '.join(METHODS)}")
        clean(folder, files, method)

    print(f"{len(pieces)} arquivos; folha -> {folder / '_folha.png'}")
    print("\n".join(report))
    for line in notes:
        print("nota: " + line)
    print("problemas:" if problems else "sem problemas")
    for line in problems:
        print("  - " + line)


if __name__ == "__main__":
    main()
