"""anim_effects.py - Efeitos de golpe novos a partir de PNG (data/anim/effects/NOME.json + NOME.png).

Um efeito (bala, raio, explosao) tem 3 partes no jogo, e esta ferramenta cria as tres a partir de uma imagem:
  1. grafico de efeito  (gBattleSeqEffectGfx[2n], [2n+1]): tiles 4bpp comprimidos (Malias "Le") + 16 cores da paleta 14,
     carregados por `load_effect_gfx n` no comeco da VRAM de objetos (tile 0);
  2. quadros            (gSpriteFrameSets[set][quadro] -> SpriteFrame {count, pad, partes{forma, tamanho, tile, x, y}}):
     uma peca OAM por quadro, centrada no ponto do sprite (x = -largura/2, y = -altura/2);
  3. anim de sprite     (gBattleSpriteAnimScripts[n]): comandos de 3 bytes {frames, quadro_hi, quadro_lo}; 0xFE 0 = volta ao
     inicio, 0xFF = fim; o operando 8 do `spawn_effect` e o indice dela.

JSON (um por efeito; o PNG e uma tira horizontal de `frames` quadros de frame_w x frame_h):
  {"slot": 0, "name": "plasma", "png": "plasma.png", "frame_w": 32, "frame_h": 32, "frames": 4, "ticks": 4, "loop": true}
  slot = ordem (0, 1, 2... sem buracos). Ids que o roteiro usa (printados no build e mostrados no Move Editor):
      load_effect_gfx  GFX  = 24 + slot            (os 24 do jogo sao 0-23)
      spawn_effect ... ANIM = 118 + slot (operando 8)   (as 118 do jogo sao 0-117)
      conjunto de quadros   = 150 + slot           (os 150 do jogo sao 0-149)
Tamanhos de quadro validos (OBJ do GBA): 8x8 16x16 32x32 64x64 16x8 32x8 32x16 64x32 8x16 8x32 16x32 32x64.
Cores: transparente (alfa < 128) = 0 + ate 15 cores; com mais, quantiza (aviso). Todos os quadros dividem a paleta.
Tiles: todos os quadros em sequencia a partir do tile 0, no maximo 256 tiles (os bots usam a VRAM a partir do tile 320).
Sem efeito novo nenhum, a ROM nao muda.
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EFFECTS_DIR = ROOT / "data/anim/effects"
GBA = 0x08000000
# tabelas originais (USA): enderecos e tamanhos (entradas)
FRAME_SETS, FRAME_SETS_N = 0x3ABE30, 150
EFFECT_GFX, EFFECT_GFX_N = 0x3AF88C, 24          # pares (tiles, paleta)
ANIM_SCRIPTS, ANIM_SCRIPTS_N = 0x3B5F80, 118     # 36 de gBattleSpriteAnimScripts + 82 de gStaggeredSpriteAnimScripts
GFX_BASE, ANIM_BASE, SET_BASE = EFFECT_GFX_N, ANIM_SCRIPTS_N, FRAME_SETS_N
MAX_TILES = 256
SHAPES = {(8, 8): (0, 0), (16, 16): (0, 1), (32, 32): (0, 2), (64, 64): (0, 3),
          (16, 8): (1, 0), (32, 8): (1, 1), (32, 16): (1, 2), (64, 32): (1, 3),
          (8, 16): (2, 0), (8, 32): (2, 1), (16, 32): (2, 2), (32, 64): (2, 3)}


def malias_store(payload):
    """Bloco Malias ("Le") so com literais (modo 3 = 3 bytes, modo 2 = 1 byte): o jogo descomprime sem problema."""
    out = bytearray(b"Le" + len(payload).to_bytes(3, "little") + b"\0")
    i = 0
    while i < len(payload):
        cmd, body = 0, bytearray()
        for op in range(4):
            if i >= len(payload):
                break
            n = 3 if len(payload) - i >= 3 else 1
            cmd |= (3 if n == 3 else 2) << (2 * op)
            body += payload[i:i + n]
            i += n
        out.append(cmd)
        out += body
    return bytes(out)


def ids(slot):
    return {"gfx": GFX_BASE + slot, "anim": ANIM_BASE + slot, "set": SET_BASE + slot}


def load_all():
    """[(doc, caminho do json)] em ordem de slot, validado."""
    out = []
    for f in sorted(EFFECTS_DIR.glob("*.json")) if EFFECTS_DIR.exists() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append((d, f))
    out.sort(key=lambda x: x[0]["slot"])
    for i, (d, f) in enumerate(out):
        if d["slot"] != i:
            raise SystemExit(f"data/anim/effects: slots devem ser 0..{len(out) - 1} sem buracos ({f.name} tem {d['slot']})")
        if (d["frame_w"], d["frame_h"]) not in SHAPES:
            raise SystemExit(f"{f.name}: quadro {d['frame_w']}x{d['frame_h']} nao e um tamanho de OBJ valido")
        if not 1 <= d["frames"] <= 250 or not 1 <= d["ticks"] <= 250:
            raise SystemExit(f"{f.name}: frames e ticks de 1 a 250")
        if not (f.parent / d["png"]).exists():
            raise SystemExit(f"{f.name}: falta {d['png']}")
    return out


def convert(doc, folder):
    """PNG -> (tiles 4bpp de todos os quadros, paleta de 16 x BGR555, avisos)."""
    from PIL import Image
    fw, fh, n = doc["frame_w"], doc["frame_h"], doc["frames"]
    img = Image.open(folder / doc["png"]).convert("RGBA")
    if img.size != (fw * n, fh):
        raise SystemExit(f"{doc['png']}: tem {img.size[0]}x{img.size[1]}, esperava {fw * n}x{fh} ({n} quadros de {fw}x{fh})")
    warns = []
    px = img.load()
    colors = sorted({px[x, y][:3] for y in range(fh) for x in range(fw * n) if px[x, y][3] >= 128})
    if len(colors) > 15:
        warns.append(f"{len(colors)} cores: quantizadas para 15")
        rgb = Image.new("RGB", img.size)
        rgb.paste(img.convert("RGB"))
        q = rgb.quantize(colors=15, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()[:45]
        colors = [tuple(pal[i * 3:i * 3 + 3]) for i in range(15)]
        qpx = q.load()
        index = {(x, y): qpx[x, y] + 1 for y in range(fh) for x in range(fw * n)}
    else:
        lut = {c: i + 1 for i, c in enumerate(colors)}
        index = {(x, y): lut[px[x, y][:3]] for y in range(fh) for x in range(fw * n) if px[x, y][3] >= 128}
    palette = [0] + [((r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)) for r, g, b in colors]
    palette += [0] * (16 - len(palette))
    tiles = bytearray()
    for k in range(n):
        for ty in range(fh // 8):
            for tx in range(fw // 8):
                for row in range(8):
                    for col in range(0, 8, 2):
                        a = index.get((k * fw + tx * 8 + col, ty * 8 + row), 0) & 15
                        b = index.get((k * fw + tx * 8 + col + 1, ty * 8 + row), 0) & 15
                        tiles.append(a | (b << 4))
    if len(tiles) // 32 > MAX_TILES:
        raise SystemExit(f"{doc['png']}: {len(tiles) // 32} tiles, o maximo e {MAX_TILES} (reduza quadros ou tamanho)")
    return bytes(tiles), palette, warns


def effect_asm(doc, folder):
    s = doc["slot"]
    fw, fh, n = doc["frame_w"], doc["frame_h"], doc["frames"]
    tiles, palette, warns = convert(doc, folder)
    shape, size = SHAPES[(fw, fh)]
    per = (fw // 8) * (fh // 8)
    a = [f"@ efeito {s}: {doc['name']} ({fw}x{fh} x {n} quadros, {len(tiles) // 32} tiles)\n",
         f"\t.align 2\nsEffTiles{s}:\n"]
    blob = malias_store(tiles)
    a += ["\t.byte " + ", ".join(str(v) for v in blob[i:i + 32]) + "\n" for i in range(0, len(blob), 32)]
    a.append(f"\t.align 2\nsEffPal{s}:\n\t.2byte " + ", ".join(f"0x{v:04X}" for v in palette) + "\n")
    for k in range(n):   # um SpriteFrame por quadro: 1 peca centrada no ponto do sprite
        a.append(f"\t.align 2\nsEffFrame{s}_{k}:\n\t.2byte 1, 0\n\t.byte {shape << 6}, {size << 6}\n"
                 f"\t.2byte {k * per}, {(-fw // 2) & 0xFFFF}, {(-fh // 2) & 0xFFFF}\n")
    a.append(f"\t.align 2\nsEffSet{s}:\n" + "".join(f"\t.4byte sEffFrame{s}_{k}\n" for k in range(n)))
    cmds = []
    for k in range(n):
        frame = ((SET_BASE + s) << 8) | k
        cmds += [doc["ticks"], frame >> 8, frame & 0xFF]
    cmds += [0xFE, 0, 0] if doc.get("loop", True) else [0xFF, 0, 0]
    a.append(f"sEffAnim{s}:\n\t.byte " + ", ".join(str(v) for v in cmds) + "\n")
    return "".join(a), warns


RENAMED = ("gSpriteFrameSets", "gBattleSeqEffectGfx", "gBattleSpriteAnimScripts")


def data_ptrs(tree):
    """config/data_ptrs da arvore: endereco (USA) de uma palavra-ponteiro dos dados -> "simbolo+offset" do alvo."""
    ptrs = {}
    for f in (Path(tree) / "config/data_ptrs").glob("*.tsv"):
        for line in f.read_text().splitlines():
            if line and not line.startswith("#"):
                a, sym = line.split("\t", 1)
                ptrs[int(a, 16) - GBA] = sym
    return ptrs


def ptr_table(ptrs, off, count):
    """As palavras da tabela original como simbolo+offset. NUNCA o numero cru: na build de expansao o codigo cresce e
    os dados originais andam (ex.: a tabela de 0x083B5F80 vai para 0x083B6164), entao um ponteiro cru da ROM original
    aponta para o lugar errado (foi o que travou a luta em 2026-11-22). O linker recalcula pelo simbolo."""
    out = []
    for i in range(count):
        sym = ptrs.get(off + 4 * i)
        if sym is None:
            raise SystemExit(f"anim_effects: ponteiro em 0x{GBA + off + 4 * i:08X} sem simbolo em config/data_ptrs")
        base = sym.split("+")[0]
        if base in RENAMED:
            sym = sym.replace(base, base + "_vanilla", 1)
        out.append(f"\t.4byte {sym}\n")
    return "".join(out)


def apply(dst, rom):
    """Na arvore gerada: as 3 tabelas originais viram _vanilla (no lugar) e as novas (as originais + os efeitos)
    vao para o fim de expansion.s. Sem efeitos, nada muda."""
    effects = load_all()
    if not effects:
        return
    dst = Path(dst)
    ptrs = data_ptrs(dst)
    for nm in ("gSpriteFrameSets", "gBattleSeqEffectGfx", "gBattleSpriteAnimScripts"):
        hit = 0
        for f in dst.glob("data/*.s"):
            t = f.read_text()
            new = t.replace(f"\t.global {nm}\n{nm}:", f"\t.global {nm}_vanilla\n{nm}_vanilla:")
            if new != t:
                f.write_text(new)
                hit += 1
        assert hit == 1, nm
    out = ["\n@ efeitos de golpe novos (tools/anim_effects.py, data/anim/effects)\n"]
    for doc, f in effects:
        text, warns = effect_asm(doc, f.parent)
        out.append(text)
        i = ids(doc["slot"])
        print(f"  efeito {doc['name']}: load_effect_gfx {i['gfx']}, spawn_effect anim {i['anim']}"
              + "".join(f"  AVISO {w}" for w in warns))
    out.append("\t.align 2\n\t.global gSpriteFrameSets\ngSpriteFrameSets:\n" + ptr_table(ptrs, FRAME_SETS, FRAME_SETS_N)
               + "".join(f"\t.4byte sEffSet{d['slot']}\n" for d, _ in effects))
    out.append("\t.global gBattleSeqEffectGfx\ngBattleSeqEffectGfx:\n" + ptr_table(ptrs, EFFECT_GFX, EFFECT_GFX_N * 2)
               + "".join(f"\t.4byte sEffTiles{d['slot']}\n\t.4byte sEffPal{d['slot']}\n" for d, _ in effects))
    out.append("\t.global gBattleSpriteAnimScripts\ngBattleSpriteAnimScripts:\n" + ptr_table(ptrs, ANIM_SCRIPTS, ANIM_SCRIPTS_N)
               + "".join(f"\t.4byte sEffAnim{d['slot']}\n" for d, _ in effects))
    exp = dst / "asm/expansion.s"
    exp.write_text(exp.read_text() + "".join(out))


if __name__ == "__main__":
    rom = (__import__("paths").DECOMP / "baserom.gba").read_bytes()
    for d, f in load_all():
        i = ids(d["slot"])
        tiles, pal, warns = convert(d, f.parent)
        print(f"{d['name']}: load_effect_gfx {i['gfx']} / anim {i['anim']} / {len(tiles) // 32} tiles", *warns)
    if not load_all():
        print("data/anim/effects vazio")
    sys.exit(0)
