"""anim_molds.py - Esqueleto dos Medabots (moldes / nos) editavel: data/anim/molds.json.

Cada molde (no 1..63 da arvore de sprites da batalha) tem um registro SpriteNodeDesc de 0x18 bytes. Os nomes do C
estao trocados (pc/research/ANIMACAO_GUIA.md): aqui tudo e [para baixo, para a direita], como nas poses.

data/anim/molds.json guarda SO os moldes editados, com valores absolutos (campos ausentes ficam como no jogo):
    {"core": {"7": {"joint": [-12, 1], "pivot": [6, 8], "depth": 1, "sibling": 0, "child": 8}},
     "navi": {"52": {"joint": [-20, 0]}}}
  - core: a tabela do Medabots (gMedabotSpriteNodeDescs), usada pelas pecas do jogo (e pelas do Navi que usam um
    molde do jogo). Moldes 1, 2, 7..49; 3..6 sao as camadas de peca (cabeca, braco esq., braco dir., pernas), que o
    jogo copia de g*PartLayerTemplate: nelas so joint/depth valem (o filho e a raiz da peca, posto em tempo de jogo).
  - navi: os registros proprios do Navi (gNaviSpriteNodeDescs, builds com --navi), aplicados em tools/decomp_navi.py
    antes da linha do chao.
Campos: pivot [baixo, direita] (s32, ponto de giro dentro do desenho), joint [baixo, direita] (s8, onde o molde se
prende ao pai), depth (s8, somado a profundidade), sibling / child (0..63, 0 = nenhum).

Moldes proprios (EXP_CUSTOM_MOLDS; o molde do jogo e compartilhado, o proprio e so de um bot):
    "custom": {"1": {"base": "core:19", "joint": [-10, 2], "pivot": [30, 20], "depth": 0}},
    "use": {"core/metabee": {"right_arm": {"17": 1}}}
  - custom: 1..127, copia do molde base ("core:N" da tabela do jogo ou "navi:N" dos registros do Navi da build), com
    as mesmas imagens e tamanho, e pivot/joint/depth proprios (ausentes = os do base). Filho/irmao nao: a arvore e o
    movimento continuam os do no onde ele for usado.
  - picture (opcional): PNG indexado (indice 0 = transparente, ate 16 cores) com desenho e tamanho proprios. O
    tamanho tem que ser de sprite do GBA (8..64, ver OBJ_SIZES); as cores sao a paleta da peca (a mesma dos outros
    pedacos: a cabeca, cada braco e as pernas tem uma paleta so, a do 1o pedaco). Vale para todas as poses do no.
    Bots com pasta de arte (campo "art"): pedaco desenhado noutro tamanho vira molde proprio sozinho (decomp_expand).
  - use: bot (chave do bot_ids.json da build) -> peca -> no da linha da peca -> molde proprio. O no tem que estar na
    linha daquela peca do bot. A entrada ganha o campo custom (bits 17..23) e o motor desenha com o registro proprio
    (gCustomSpriteNodeDescs); braco com molde proprio vira espelho de verdade no lado 1, como o Navi com arte propria.

O build (decomp_expand.py) grava os do core na copia do baserom.gba da arvore (so bytes que nao sao ponteiro: os
ponteiros saem de config/data_ptrs, entao valem em qualquer build, com ou sem expansao).

Uso:
  python tools/anim_molds.py --show [--navi-build ROM MAP]   tabela do jogo (ou de uma build) com os campos
  python tools/anim_molds.py --check                          valida data/anim/molds.json
"""
import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOLDS_FILE = ROOT / "data/anim/molds.json"
GBA = 0x08000000
CORE_TABLE = 0x3D1BF8          # gMedabotSpriteNodeDescs (USA): 50 ponteiros
CORE_COUNT = 50
LAYERS = {3: 0x7ECA0, 4: 0x7ECB8, 5: 0x7ECD0, 6: 0x7ECE8}   # g{Head,LeftArm,RightArm,Leg}PartLayerTemplate
LAYER_NAMES = {3: "head layer", 4: "left arm layer", 5: "right arm layer", 6: "legs layer"}
FIELDS = ("pivot", "joint", "depth", "sibling", "child")
NODES = 64
CUSTOM_FIELDS = ("pivot", "joint", "depth")
MAX_CUSTOM = 127
PART_KEYS = ("head", "right_arm", "left_arm", "legs")
NODE_TABLES = (("gHeadPartSpriteNodes", 16), ("gRightArmPartSpriteNodes", 16), ("gLeftArmPartSpriteNodes", 16),
               ("gLegPartSpriteNodes", 32))
CUSTOM_SHIFT = 17
OBJ_SIZES = {(8, 8), (16, 16), (32, 32), (64, 64), (16, 8), (32, 8), (32, 16), (64, 32), (8, 16), (8, 32), (16, 32),
             (32, 64)}   # (largura, altura) validas de sprite do GBA


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def decode(rec):
    """Campos editaveis de um registro de 0x18 bytes."""
    pv, ph = struct.unpack_from("<ii", rec, 4)
    jv, jh, dp = struct.unpack_from("<bbb", rec, 12)
    return {"pivot": [pv, ph], "joint": [jv, jh], "depth": dp, "sibling": rec[15], "child": rec[16]}


def encode(rec, fields):
    """Grava os campos em rec (bytearray de 0x18) no lugar."""
    if "pivot" in fields:
        struct.pack_into("<ii", rec, 4, *fields["pivot"])
    if "joint" in fields:
        struct.pack_into("<bb", rec, 12, *fields["joint"])
    if "depth" in fields:
        struct.pack_into("<b", rec, 14, fields["depth"])
    if "sibling" in fields:
        rec[15] = fields["sibling"]
    if "child" in fields:
        rec[16] = fields["child"]
    return rec


def _check_fields(where, m, f, layer):
    bad = set(f) - set(FIELDS)
    if bad:
        raise SystemExit(f"anim_molds: {where} {m}: campo desconhecido {sorted(bad)} (validos: {', '.join(FIELDS)})")
    for k in ("pivot", "joint"):
        if k in f:
            v = f[k]
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v)):
                raise SystemExit(f"anim_molds: {where} {m}: {k} tem que ser [baixo, direita] inteiros")
            if k == "joint" and not all(-128 <= x <= 127 for x in v):
                raise SystemExit(f"anim_molds: {where} {m}: joint fora de -128..127")
            if k == "pivot" and not all(-4096 <= x <= 4096 for x in v):
                raise SystemExit(f"anim_molds: {where} {m}: pivot fora de -4096..4096")
    if "depth" in f and not (isinstance(f["depth"], int) and -128 <= f["depth"] <= 127):
        raise SystemExit(f"anim_molds: {where} {m}: depth fora de -128..127")
    for k in ("sibling", "child"):
        if k in f and not (isinstance(f[k], int) and 0 <= f[k] < NODES):
            raise SystemExit(f"anim_molds: {where} {m}: {k} fora de 0..63")
    if layer and set(f) - {"joint", "depth"}:
        raise SystemExit(f"anim_molds: {where} {m} ({LAYER_NAMES[m]}): na camada de peca so joint e depth valem")


def load(path=MOLDS_FILE):
    """{"core": {m: campos}, "navi": {m: campos}} (vazio sem o arquivo)."""
    out = {"core": {}, "navi": {}, "custom": {}, "use": {}}
    if not Path(path).exists():
        return out
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in doc:
        if k not in ("core", "navi", "custom", "use") and not k.startswith("_"):
            raise SystemExit(f"anim_molds: chave {k!r} desconhecida em {path} (core / navi / custom / use)")
    for key, f in (doc.get("custom") or {}).items():
        c = int(key)
        if not 1 <= c <= MAX_CUSTOM:
            raise SystemExit(f"anim_molds: custom {c}: fora de 1..{MAX_CUSTOM}")
        base = str(f.get("base", ""))
        tab, _, num = base.partition(":")
        if tab not in ("core", "navi") or not num.isdigit() or not 1 <= int(num) < NODES:
            raise SystemExit(f"anim_molds: custom {c}: base {base!r} (use 'core:N' ou 'navi:N')")
        if tab == "core" and (int(num) >= CORE_COUNT or int(num) < 7):
            raise SystemExit(f"anim_molds: custom {c}: base {base}: molde do jogo com desenho e 7..49")
        rest = {k: v for k, v in f.items() if k not in ("base", "picture") and not k.startswith("_")}
        if "picture" in f:
            pic = Path(f["picture"]) if Path(f["picture"]).is_absolute() else ROOT / f["picture"]
            if not pic.exists():
                raise SystemExit(f"anim_molds: custom {c}: picture {f['picture']} nao existe")
            rest_pic = str(pic)
        else:
            rest_pic = None
        if set(rest) - set(CUSTOM_FIELDS):
            raise SystemExit(f"anim_molds: custom {c}: so pivot, joint e depth (filho/irmao seguem o no)")
        _check_fields("custom", c, rest, False)
        out["custom"][c] = dict(rest, base=(tab, int(num)))
        if rest_pic:
            out["custom"][c]["picture"] = rest_pic
    for bot, parts in (doc.get("use") or {}).items():
        if bot.startswith("_"):
            continue
        for part, nodes in parts.items():
            if part not in PART_KEYS:
                raise SystemExit(f"anim_molds: use {bot}: peca {part!r} (validas: {', '.join(PART_KEYS)})")
            for node, c in nodes.items():
                if not 1 <= int(node) < NODES:
                    raise SystemExit(f"anim_molds: use {bot} {part}: no {node} fora de 1..63")
                if c not in out["custom"]:
                    raise SystemExit(f"anim_molds: use {bot} {part} no {node}: molde proprio {c} nao existe")
                out["use"].setdefault(bot, {}).setdefault(part, {})[int(node)] = c
    for where in ("core", "navi"):
        for key, f in (doc.get(where) or {}).items():
            m = int(key)
            if not 1 <= m < NODES:
                raise SystemExit(f"anim_molds: {where} {m}: molde fora de 1..63")
            if where == "core" and m >= CORE_COUNT:
                raise SystemExit(f"anim_molds: core {m}: o jogo tem 50 moldes; os 50+ sao do Navi (use \"navi\")")
            _check_fields(where, m, f, where == "core" and m in LAYERS)
            out[where][m] = f
    return out


def core_records(rom):
    """{molde: (offset do registro, bytearray)} da tabela do jogo, camadas pelos templates."""
    out = {}
    for m in range(1, CORE_COUNT):
        if m in LAYERS:
            o = LAYERS[m]
        else:
            p = u32(rom, CORE_TABLE + 4 * m)
            assert p >> 24 == 0x08, f"molde {m}: ponteiro 0x{p:08X}"
            o = p - GBA
        out[m] = (o, bytearray(rom[o:o + 0x18]))
    return out


def check_tree(recs, where):
    """Partindo de qualquer molde (a raiz de cada peca e posta em tempo de jogo), filho/irmao nao pode voltar a um
    no ja visto (ciclo ou dois pais) nem levar a um molde que nao existe nessa tabela."""
    for start in recs:
        seen = set()
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                raise SystemExit(f"anim_molds: {where}: partindo do molde {start}, o no {n} aparece duas vezes "
                                 "(ciclo ou dois pais)")
            seen.add(n)
            if n not in recs:
                raise SystemExit(f"anim_molds: {where}: a arvore chega no molde {n}, que nao existe nessa tabela")
            r = recs[n]
            if r[16]:
                stack.append(r[16])
            if r[15]:
                stack.append(r[15])


def apply(dst):
    """Grava os moldes "core" de data/anim/molds.json na copia do baserom.gba da arvore dst. Sem edicao: nada."""
    core = load()["core"]
    if not core:
        return
    rp = Path(dst) / "baserom.gba"
    rom = bytearray(rp.read_bytes())
    recs = core_records(rom)
    for m, f in core.items():
        encode(recs[m][1], f)
    check_tree({m: r for m, (_, r) in recs.items()}, "core")
    for m, (o, r) in recs.items():
        rom[o:o + 0x18] = r
    rp.write_bytes(bytes(rom))
    print(f"  esqueleto (data/anim/molds.json): {len(core)} moldes do jogo editados: {sorted(core)}")


def apply_navi(records):
    """Moldes "navi": edita no lugar os registros do Navi (decomp_navi.plan, {alvo: bytearray})."""
    navi = load()["navi"]
    for m, f in navi.items():
        if m not in records:
            raise SystemExit(f"anim_molds: navi {m}: nenhum bot do Navi desta build tem esse molde "
                             f"(os do Navi: {sorted(records)}); para o molde do jogo use \"core\"")
        encode(records[m], f)
    return sorted(navi)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--baserom", default=str(__import__("paths").DECOMP / "baserom.gba"))
    a = ap.parse_args()
    rom = Path(a.baserom).read_bytes()
    recs = core_records(rom)
    if a.show:
        for m, (_, r) in recs.items():
            d = decode(r)
            tag = f"  ({LAYER_NAMES[m]})" if m in LAYERS else ""
            print(f"{m:2}: pivot {d['pivot']} joint {d['joint']} depth {d['depth']} sibling {d['sibling']} "
                  f"child {d['child']} size {r[18]}x{r[19]}{tag}")
    if a.check or not a.show:
        doc = load()
        for m, f in doc["core"].items():
            encode(recs[m][1], f)
        check_tree({m: r for m, (_, r) in recs.items()}, "core")
        print(f"ok: {len(doc['core'])} moldes core, {len(doc['navi'])} navi")


if __name__ == "__main__":
    sys.exit(main())


# ---- moldes proprios (EXP_CUSTOM_MOLDS) ----

def custom_asm(custom, rom, navi_records, word):
    """Registros dos moldes proprios + gCustomSpriteNodeDescs[0..max]. rom = baserom da arvore (moldes do jogo ja
    editados); navi_records = {alvo: registro} do decomp_navi; word(off) = .4byte da palavra-ponteiro do baserom."""
    if not custom:
        return ""
    core = core_records(rom)
    out = ["\n@ ---- moldes proprios (data/anim/molds.json custom, tools/anim_molds.py) ----\n"]
    for c in sorted(custom):
        f = custom[c]
        tab, m = f["base"]
        if tab == "core":
            o, rec = core[m]
            frames = word(o)
            if ".incbin" in frames:
                raise SystemExit(f"anim_molds: custom {c}: a lista de imagens do molde {m} nao tem simbolo")
        else:
            if m not in (navi_records or {}):
                raise SystemExit(f"anim_molds: custom {c}: base navi:{m}, mas nenhum bot do Navi desta build usa esse "
                                 f"molde (os do Navi: {sorted(navi_records or {})})")
            rec, frames = bytearray(navi_records[m]), f"\t.4byte gNaviArt{m}\n"
        rec = encode(bytearray(rec), {k: v for k, v in f.items() if k in CUSTOM_FIELDS})
        if f.get("picture"):
            tiles, pal, (w, h) = picture_tiles(f["picture"])
            rec[0x12], rec[0x13] = h, w        # o C chama de width a medida vertical (set_oam_sprite_shape_size)
            blob = _lz77(tiles)
            out.append(f"\t.align 2\ngCustomImg{c}:\n\t.byte " + ", ".join(f"0x{v:02X}" for v in blob) + "\n")
            out.append(f"\t.align 1\ngCustomPal{c}:\n\t.2byte " + ", ".join(f"0x{v:04X}" for v in pal) + "\n")
            # lista de imagens: o mesmo desenho em todo seletor (todas as poses do no), paleta junto (o jogo so le a
            # do 1o pedaco da peca)
            out.append(f"\t.align 2\ngCustomArt{c}:\n" + f"\t.4byte gCustomImg{c}, gCustomPal{c}\n" * 256)
            frames = f"\t.4byte gCustomArt{c}\n"
        out.append(f"\t.align 2\ngCustomNode{c}:\n{frames}\t.byte " + ", ".join(f"0x{v:02X}" for v in rec[4:0x18])
                   + "\n")
    top = max(custom)
    out.append("\t.align 2\n\t.global gCustomSpriteNodeDescs\ngCustomSpriteNodeDescs:\n")
    out += [f"\t.4byte {('gCustomNode%d' % i) if i in custom else 0}\n" for i in range(top + 1)]
    return "".join(out)


def _table_block(text, name):
    """(inicio, fim) das linhas de dados da tabela `name` no asm: .incbin baserom, .byte e .4byte numericos."""
    head = f"\t.global {name}\n{name}:\n"
    i = text.index(head) + len(head)
    j = i
    for line in text[i:].splitlines(keepends=True):
        t = line.strip()
        if not (t.startswith('.incbin "baserom.gba"') or t.startswith(".byte") or t.startswith(".4byte")):
            break
        j += len(line)
    return i, j


def _materialize(block, rom):
    out = bytearray()
    for line in block.splitlines():
        t = line.strip()
        if t.startswith(".incbin"):
            _, off, n = [x.strip() for x in t.split(",")]
            off, n = int(off, 0), int(n, 0)
            out += rom[off:off + n]
        else:
            kind, vals = t.split(None, 1)
            size = 1 if kind == ".byte" else 4
            for v in vals.split(","):
                out += (int(v.strip(), 0) & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
    return out


def patch_node_tables(text, use, ids, rom):
    """Marca o campo custom nas entradas das linhas de peca dos bots de `use` (tabelas g*PartSpriteNodes do asm, so
    numeros) e reescreve as tabelas como .4byte. ids = bot_ids.json da build."""
    if not use:
        return text
    for k, (name, size) in enumerate(NODE_TABLES):
        part = PART_KEYS[k]
        hits = [(bot, nodes[part]) for bot, nodes in use.items() if part in nodes]
        if not hits:
            continue
        i, j = _table_block(text, name)
        data = _materialize(text[i:j], rom)
        for bot, nodes in hits:
            if bot not in ids:
                raise SystemExit(f"anim_molds: use {bot}: bot fora desta build (bot_ids.json)")
            row = ids[bot] * size
            if row + size > len(data):
                raise SystemExit(f"anim_molds: use {bot}: linha {ids[bot]} fora da tabela {name}")
            for node, c in nodes.items():
                found = False
                for e in range(row, row + size, 4):
                    w = struct.unpack_from("<I", data, e)[0]
                    if w & 0x3F == 0:
                        break
                    if w & 0x3F == node:
                        struct.pack_into("<I", data, e, (w & ~(0x7F << CUSTOM_SHIFT)) | (c << CUSTOM_SHIFT))
                        found = True
                        break
                if not found:
                    raise SystemExit(f"anim_molds: use {bot} {part}: o no {node} nao esta na linha dessa peca")
        words = struct.unpack_from(f"<{len(data) // 4}I", data)
        block = "".join("\t.4byte " + ", ".join(f"0x{w:08X}" for w in words[n:n + 8]) + "\n"
                        for n in range(0, len(words), 8))
        text = text[:i] + block + text[j:]
    return text


def picture_tiles(path):
    """PNG indexado -> (tiles 4bpp na ordem do jogo, paleta BGR555 de 16 cores, (largura, altura))."""
    from PIL import Image
    img = Image.open(path)
    if img.mode != "P":
        raise SystemExit(f"anim_molds: {path}: precisa ser PNG indexado (tools/check_template.py --limpar)")
    w, h = img.size
    if (w, h) not in OBJ_SIZES:
        raise SystemExit(f"anim_molds: {path}: {w}x{h} nao e tamanho de sprite do GBA "
                         f"({', '.join(f'{a}x{b}' for a, b in sorted(OBJ_SIZES))})")
    px = img.load()
    out = bytearray()
    for ty in range(h // 8):
        for tx in range(w // 8):
            for y in range(8):
                for x in range(0, 8, 2):
                    lo, hi = px[tx * 8 + x, ty * 8 + y], px[tx * 8 + x + 1, ty * 8 + y]
                    if lo > 15 or hi > 15:
                        raise SystemExit(f"anim_molds: {path}: indice de cor > 15 (maximo 16 cores)")
                    out.append(lo | hi << 4)
    rgb = (img.getpalette() or [])[:48]
    rgb += [0] * (48 - len(rgb))
    pal = [min(31, rgb[3 * i] // 8) | min(31, rgb[3 * i + 1] // 8) << 5 | min(31, rgb[3 * i + 2] // 8) << 10
           for i in range(16)]
    return bytes(out), pal, (w, h)


def _lz77(payload):
    sys.path.insert(0, str(ROOT / "tools"))
    from codecs_gba import lz77_store
    return lz77_store(payload)


ART_PIECE = r"large_(cabeca|braco_dir|braco_esq|pernas)_(\d+)_m(\d+)(_pose\d+)?\.png"
ART_PART = {"cabeca": "head", "braco_dir": "right_arm", "braco_esq": "left_arm", "pernas": "legs"}


def art_customs(bots, rom, custom, use):
    """Bots com pasta de arte (bots = {chave: pasta}): pedaco desenhado noutro tamanho que o molde vira molde proprio
    (picture = o PNG da pasta). Acrescenta em custom/use (numeros depois dos de molds.json). Devolve o que criou."""
    import re
    core = core_records(rom)
    made = []
    for key, folder in sorted(bots.items()):
        for png in sorted(Path(folder).glob("large_*.png")):
            m = re.fullmatch(ART_PIECE, png.name)
            if not m or m.group(4):
                continue
            d = int(m.group(3))
            if d not in core:
                continue
            from PIL import Image
            with Image.open(png) as img:
                size = img.size
            rec = core[d][1]
            if size == (rec[0x13], rec[0x12]):
                continue
            c = next(i for i in range(1, MAX_CUSTOM + 1) if i not in custom)
            custom[c] = {"base": ("core", d), "picture": str(png)}
            use.setdefault(key, {}).setdefault(ART_PART[m.group(1)], {})[d] = c
            made.append(f"{key} {png.name} {size[0]}x{size[1]} -> molde proprio {c}")
    return made
