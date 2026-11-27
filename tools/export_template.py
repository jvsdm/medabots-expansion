"""
export_template.py - Exporta as pecas de um bot como modelos de desenho (PNG indexado, 16 cores).

Uso:  python tools/export_template.py <bot_id> [rom] [pasta_saida]
      ex.: python tools/export_template.py 43   -> art/template_043_metabee/
      ROM da decomp (com <rom>.map ao lado): bot_id e o id NESSA build (bot_ids.json) e as tabelas saem do .map
      (gHeadPartSpriteNodes..., gMedabotPartSpriteTiles; moldes do Navi e proprios em gNaviSpriteNodeDescs e
      gCustomSpriteNodeDescs). Serve para qualquer bot: Core, Shingata, Navi, proprios (aba Art do WPF).

Saida (cada PNG no tamanho exato do molde, paleta de 16 cores, indice 0 = transparente):
  large_<peca>_<n>_m<molde>[_pose<k>].png  imagens grandes (tela de Medabots / ataques em batalha)
  mini_<componente>.png                    mini sprite (campo de batalha / menus)
  _folha.png                               tudo junto, ampliado 4x, com rotulos
  LEIAME.txt                               tamanhos e regras

Pedacos sem paleta propria usam a da peca principal (primeiro pedaco da mesma peca).
Registro do molde: +0x12 = altura, +0x13 = largura (pixels; como MoldDesc do Toolkit e decomp_navi).
"""
import json
import struct
import sys
from pathlib import Path
from PIL import Image, ImageDraw
from medarom import ROOT, GBA_BASE, off
from codecs_gba import malias_decompress, lz77_decompress

LITERAL_SITES = {"battle": 0x042DA6, "family": 0x042ED2,
                 "head": 0x0461F0, "right_arm": 0x04620E, "left_arm": 0x04622A, "legs": 0x046242}
ROW_SIZE = {"head": 16, "right_arm": 16, "left_arm": 16, "legs": 32}
PALETTE_SET = off("export.palette_set")  # paleta por familia (EU; Rokusho = +0x24, ver pc/versions)
DESCRIPTORS_POOL = 0x005364  # slot de ponteiro (ROM); mesmo offset nas duas versoes, o valor e lido da ROM
MINI = [("cabeca", 16, 16), ("braco_dir_1", 16, 16), ("braco_dir_2", 16, 16),
        ("braco_esq_1", 16, 16), ("braco_esq_2", 16, 16), ("pernas", 16, 48)]   # pernas: 3 quadros 16x16
KIND_PT = {"head": "cabeca", "right_arm": "braco_dir", "left_arm": "braco_esq", "legs": "pernas"}


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def literal(d, pc):
    hw = struct.unpack_from("<H", d, pc)[0]
    return u32(d, ((pc + 4) & ~3) + (hw & 0xFF) * 4) - GBA_BASE


def palette(d, off):
    out = []
    for i in range(16):
        c = struct.unpack_from("<H", d, off + 2 * i)[0]
        out += [(c & 31) * 8, (c >> 5 & 31) * 8, (c >> 10 & 31) * 8]
    return out


def tiles_image(raw, width, height, pal):
    img = Image.new("P", (width, height), 0)
    img.putpalette(pal + [0] * (768 - len(pal)))
    px = img.load()
    tw = width // 8
    for t in range(min(len(raw) // 32, tw * (height // 8))):
        for y in range(8):
            for x in range(8):
                b = raw[t * 32 + y * 4 + x // 2]
                px[(t % tw) * 8 + x, (t // tw) * 8 + y] = (b >> 4) if x & 1 else (b & 15)
    img.info["transparency"] = 0
    return img


def decomp_tables(rom_path, d):
    """Enderecos (offset na ROM) das tabelas de uma ROM da decomp, pelo .map ao lado; None se nao for."""
    mp = rom_path.with_suffix(".map")
    if not mp.exists():
        return None
    sym = {}
    for line in mp.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("0x08") and parts[1].startswith("g"):
            sym.setdefault(parts[1], int(parts[0], 16) - GBA_BASE)
    lay = rom_path.with_suffix(".layout.json")
    pal = json.loads(lay.read_text(encoding="utf-8"))["tables"].get("PartSelectionComponentPaletteSet") if lay.exists() else None
    if pal is None:     # paletas dos mini sprites: os 0x60 bytes da USA (0x50DEF8) achados na ROM
        base = (ROOT / "build/scratch/decomp_rok/baserom.gba").read_bytes()[0x50DEF8:0x50DEF8 + 0x60]
        pal = d.find(base)
    return {"rows": {"head": sym["gHeadPartSpriteNodes"], "right_arm": sym["gRightArmPartSpriteNodes"],
                     "left_arm": sym["gLeftArmPartSpriteNodes"], "legs": sym["gLegPartSpriteNodes"]},
            "descs": sym["gMedabotSpriteNodeDescs"], "navi": sym.get("gNaviSpriteNodeDescs"),
            "custom": sym.get("gCustomSpriteNodeDescs"), "family": sym["gMedabotSpritePalettes"],
            "battle": sym["gMedabotPartSpriteTiles"], "palette_set": pal}


def bot_name(bot):
    f = next((ROOT / "data" / "bots").glob(f"{bot:03d}_*.json"), None)
    return json.loads(f.read_text(encoding="utf-8"))["name"] if f else f"bot{bot}"


def main():
    bot = int(sys.argv[1])
    rom_path = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "Medabots - Metabee (Europe).gba"
    name = bot_name(bot)
    slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "art" / f"template_{bot:03d}_{slug}"
    out.mkdir(parents=True, exist_ok=True)
    d = rom_path.read_bytes()
    dec = decomp_tables(rom_path, d)
    descriptors = dec["descs"] if dec else u32(d, DESCRIPTORS_POOL) - GBA_BASE
    palette_set = dec["palette_set"] if dec else PALETTE_SET
    pieces = []

    for kind, size in ROW_SIZE.items():
        row = (dec["rows"][kind] if dec else literal(d, LITERAL_SITES[kind])) + bot * size
        main_pal = None
        for i in range(size // 4):
            e = u32(d, row + 4 * i)
            mold = e & 0x3F
            if not mold:
                continue
            sel, variant = (e >> 6) & 0xFF, (e >> 15) & 1
            table = descriptors
            if dec and (e >> 17) & 0x7F and dec["custom"] is not None:    # molde proprio do bot (EXP_CUSTOM_MOLDS)
                table, mold = dec["custom"], (e >> 17) & 0x7F
            elif dec and (e >> 16) & 1 and dec["navi"] is not None:      # peca do Navi (EXP_NAVI_SPRITES)
                table = dec["navi"]
            rec = u32(d, table + 4 * mold) - GBA_BASE
            blobs = u32(d, rec) - GBA_BASE
            w, h = d[rec + 0x13], d[rec + 0x12]   # +0x12 altura, +0x13 largura
            for k in range(variant + 1):
                img_ptr, pal_ptr = u32(d, blobs + (sel + k) * 8), u32(d, blobs + (sel + k) * 8 + 4)
                raw, _ = lz77_decompress(d, img_ptr - GBA_BASE)
                if pal_ptr != img_ptr:
                    pal = palette(d, pal_ptr - GBA_BASE)
                    main_pal = main_pal or pal
                else:
                    pal = main_pal or palette(d, palette_set)
                suffix = f"_pose{k + 1}" if variant else ""
                fname = f"large_{KIND_PT[kind]}_{i + 1}_m{mold:02d}{suffix}.png"
                img = tiles_image(raw, w, h, pal)
                img.save(out / fname, transparency=0)
                pieces.append((fname, img))

    fam = d[(dec["family"] if dec else literal(d, LITERAL_SITES["family"])) + bot]
    mini_pal = palette(d, palette_set + 32 * fam)
    bt = dec["battle"] if dec else literal(d, LITERAL_SITES["battle"])
    for k, (label, w, h) in enumerate(MINI):
        raw, _ = malias_decompress(d, u32(d, bt + (bot * 6 + k) * 4) - GBA_BASE)
        img = tiles_image(raw, w, h, mini_pal)
        frames = [img] if h == w else [img.crop((0, f * w, w, (f + 1) * w)) for f in range(h // w)]
        for f, frame in enumerate(frames):
            frame.info["transparency"] = 0
            fname = f"mini_{label}.png" if len(frames) == 1 else f"mini_{label}_{f + 1}.png"
            frame.save(out / fname, transparency=0)
            pieces.append((fname, frame))

    # tamanho de cada pedaco grande como esta ROM o desenha: o check_template confere por ele (moldes do Navi e
    # proprios nao existem na ROM EU)
    (out / "_tamanhos.json").write_text(json.dumps({f: [im.width, im.height] for f, im in pieces if f.startswith("large_")},
                                                   indent=1) + chr(10), encoding="utf-8")
    scale, pad = 4, 14
    cols = 6
    cell_w = 64 * scale + pad
    cell_h = 64 * scale + pad + 14
    rows = (len(pieces) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (64, 64, 64))
    draw = ImageDraw.Draw(sheet)
    for n, (fname, img) in enumerate(pieces):
        x, y = (n % cols) * cell_w + 4, (n // cols) * cell_h + 4
        draw.text((x, y), f"{fname} ({img.width}x{img.height})", fill=(230, 230, 230))
        big = img.convert("RGBA").resize((img.width * scale, img.height * scale), Image.NEAREST)
        bg = Image.new("RGBA", big.size, (255, 0, 255, 255))
        sheet.paste(Image.alpha_composite(bg, big).convert("RGB"), (x, y + 14))
    sheet.save(out / "_folha.png")

    (out / "LEIAME.txt").write_text(
        f"Modelo de desenho: {name} (bot {bot})\n\n"
        "Imagens grandes (large_*): cada arquivo e um pedaco que o jogo encaixa e anima nas juntas.\n"
        "  - Mantenha o tamanho exato de cada PNG.\n"
        "  - 16 cores por peca (cabeca, braco direito, braco esquerdo, pernas); a cor 0 e transparente,\n"
        "    sobram 15. Todos os pedacos da mesma peca devem usar a mesma paleta (a do pedaco 1).\n"
        "  - Cores com 5 bits por canal: R, G e B em multiplos de 8 (0-248).\n"
        "  - _pose1/_pose2: duas poses do mesmo pedaco (o jogo alterna).\n"
        "Mini sprite (mini_*): bonequinho do campo de batalha e menus, 16x16 cada; mini_pernas_1/2/3 sao\n"
        "  os quadros da animacao de andar. Tamanhos fixos; as cores sao\n"
        "  aproximadas pelo build para as 4 paletas compartilhadas (a sua paleta nao vai exata).\n"
        "_folha.png: tudo ampliado 4x (rosa = transparente), so para conferencia.\n",
        encoding="utf-8")
    print(f"{len(pieces)} pecas -> {out}")
    for fname, img in pieces:
        print(f"  {fname}: {img.width}x{img.height}")


if __name__ == "__main__":
    main()
