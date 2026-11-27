"""
gfx_port.py - Copia os graficos de um bot de outra ROM da mesma engine (Shingata) para a ROM expandida.

Chamado pelo build.py para bots com "graphics_source".

- Sprites de batalha: 6 blocos Malias por bot -> copiados, ponteiros na linha nova.
- Familia de paleta: 1 byte (as paletas compartilhadas sao identicas nos dois jogos).
- Previews (tela de pecas/Medabot): cada entrada = molde (bits 0-5) + seletor (bits 6-13)
  + variante (bit 15). Os moldes (descritores) sao iguais entre os jogos (58/59); a arte do bot
  fica na lista de blobs do molde, em pares [imagem LZ77, paleta 32 B]. Para portar, a lista do
  molde e recriada com as entradas originais + as do bot novo, e o seletor e reescrito.
"""
import struct
import sys
import numpy as np
from medarom import ROOT, GBA_BASE, PREVIEW_TABLES, MOLD_TABLE
from codecs_gba import compressed_size, malias_decompress, lz77_store
import mini_palette

PREVIEW_DESCRIPTORS = MOLD_TABLE    # ponteiro p/ registro de cada molde (da versao em uso: perfil)
ORIGINAL_DESCRIPTORS = 50           # a tabela original acaba aqui (0x3D1E40 e outra tabela)
DESCRIPTOR_SLOTS = 64                # IDs cabem em 6 bits
CODE_END = 0x0A0000
PREVIEW_ROW = {"head": 16, "right_arm": 16, "left_arm": 16, "legs": 32}
PREVIEW_GFX = {"head": "PREVIEW_HEAD", "right_arm": "PREVIEW_RIGHT_ARM",
               "left_arm": "PREVIEW_LEFT_ARM", "legs": "PREVIEW_LEGS"}
SYNTHETIC_TEMPLATES = (PREVIEW_TABLES["head"] - 0x60, 4 * 0x18)   # 4 linhas de 6 palavras
PALETTE_SIZE = 0x20
ORIG_GFX_ROWS = 122


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


# Seletor: 7 bits no jogo original (0x45ECC); o build aplica patches.SELECTOR_8BIT_PATCH e passa a
# 8 bits (6-13). Os originais usam 0-127 (bit 13 nunca ligado); bots novos ocupam vagas livres ate 255.
SELECTOR_MASK = 0xFF
SELECTOR_SLOTS = 256
ORIGINAL_SLOTS = 128


def entry_selectors(entry):
    """Seletores ocupados por uma entrada (com variante, ocupa sel e sel+1)."""
    sel, vb = (entry >> 6) & SELECTOR_MASK, (entry >> 15) & 1
    return list(range(sel, sel + vb + 1))


def eu_descriptor_usage(original):
    """molde -> conjunto de seletores usados pela ROM original."""
    used = {}

    def scan(base, count):
        for i in range(count):
            e = u32(original, base + 4 * i)
            d = e & 0x3F
            if d:
                used.setdefault(d, set()).update(entry_selectors(e))

    for kind, size in PREVIEW_ROW.items():
        scan(PREVIEW_TABLES[kind], ORIG_GFX_ROWS * size // 4)
    scan(*SYNTHETIC_TEMPLATES[:1], SYNTHETIC_TEMPLATES[1] // 4)
    return used


def free_selector(taken, width):
    for sel in range(1, SELECTOR_SLOTS - width + 1):
        if all(s not in taken for s in range(sel, sel + width)):
            return sel
    return None


def descriptor_blob_table(rom_bytes, descriptor_table, d):
    record = u32(rom_bytes, descriptor_table + 4 * d) - GBA_BASE
    return record, u32(rom_bytes, record) - GBA_BASE


# IDs de molde que nenhuma tela usa (preview, templates e filhos). 3-6 apontam para RAM
# (moldes montados em tempo de execucao) e 1-2 sao registros antigos: evitados.
CLONE_IDS = list(range(63, 49, -1))


class DescriptorState:
    """Listas de blobs por molde (originais recriados e clones) durante o build."""

    def __init__(self, original):
        self.original = original
        self.used = eu_descriptor_usage(original)
        self.tables = {}     # molde -> 256 ponteiros
        self.clones = {}     # molde original -> clone
        self.free_ids = [i for i in CLONE_IDS if i not in self._ids_in_use()]

    def _ids_in_use(self):
        ids, stack = set(self.used), list(self.used)
        while stack:
            rec = u32(self.original, PREVIEW_DESCRIPTORS + 4 * stack.pop()) - GBA_BASE
            for child in (self.original[rec + 0x0F], self.original[rec + 0x10]):
                if child and child not in ids:
                    ids.add(child)
                    stack.append(child)
        return ids

    def _source_record(self, d):
        original = next((o for o, c in self.clones.items() if c == d), d)
        return u32(self.original, PREVIEW_DESCRIPTORS + 4 * original) - GBA_BASE

    def clone_of(self, d):
        if d not in self.clones:
            if not self.free_ids:
                raise SystemExit("sem IDs de molde livres para clonar")
            c = self.free_ids.pop(0)
            self.clones[d] = c
            self.used[c] = {0}
            # posicoes de um clone comecam todas com o par 0 do original (imagem padrao)
            _, bt = descriptor_blob_table(self.original, PREVIEW_DESCRIPTORS, d)
            self.tables[c] = [u32(self.original, bt), u32(self.original, bt + 4)] * SELECTOR_SLOTS
        return self.clones[d]

    def taken(self, d):
        return self.used.setdefault(d, set())

    def table(self, d):
        if d not in self.tables:
            _, bt = descriptor_blob_table(self.original, PREVIEW_DESCRIPTORS, d)
            words = [u32(self.original, bt + 4 * i) for i in range(ORIGINAL_SLOTS * 2)]
            self.tables[d] = words + words[:2] * (SELECTOR_SLOTS - ORIGINAL_SLOTS)
        return self.tables[d]

    def write(self, rom, alloc, log):
        clone_ids = set(self.clones.values())
        pointer_table = PREVIEW_DESCRIPTORS
        if clone_ids:
            # A tabela original tem so 50 moldes; logo apos (0x3D1E40) vem outra tabela (roteiros
            # de animacao de batalha). Os clones ganham uma tabela nova de 64 posicoes.
            pointer_table = alloc.take(DESCRIPTOR_SLOTS * 4)
            filler = u32(self.original, PREVIEW_DESCRIPTORS + 4 * 1)
            for i in range(DESCRIPTOR_SLOTS):
                value = u32(self.original, PREVIEW_DESCRIPTORS + 4 * i) if i < ORIGINAL_DESCRIPTORS else filler
                struct.pack_into("<I", rom.data, pointer_table + 4 * i, value)
            pools = [o for o in range(0, CODE_END, 4) if u32(rom.data, o) == GBA_BASE + PREVIEW_DESCRIPTORS]
            for o in pools:
                struct.pack_into("<I", rom.data, o, GBA_BASE + pointer_table)
            log.append(f"tabela de moldes: {ORIGINAL_DESCRIPTORS} -> {DESCRIPTOR_SLOTS} posicoes em "
                       f"0x{pointer_table:06X} ({len(pools)} ponteiros reapontados)")
        for d, words in self.tables.items():
            at = alloc.take(len(words) * 4)
            for i, w in enumerate(words):
                struct.pack_into("<I", rom.data, at + 4 * i, w)
            if d in clone_ids:
                rec = alloc.take(0x18)
                rom.data[rec:rec + 0x18] = self.original[self._source_record(d):self._source_record(d) + 0x18]
                for child_at in (rec + 0x0F, rec + 0x10):
                    child = rom.data[child_at]
                    rom.data[child_at] = self.clones.get(child, child)
                struct.pack_into("<I", rom.data, pointer_table + 4 * d, GBA_BASE + rec)
            else:
                rec = u32(self.original, PREVIEW_DESCRIPTORS + 4 * d) - GBA_BASE
            struct.pack_into("<I", rom.data, rec, GBA_BASE + at)


def hex_bgr555(text):
    r, g, b = int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
    return r // 8 | (g // 8) << 5 | (b // 8) << 10


def bgr555_hex(c):
    return f"#{(c & 31) * 8:02x}{(c >> 5 & 31) * 8:02x}{(c >> 10 & 31) * 8:02x}"


KIND_PT = {"head": "cabeca", "right_arm": "braco_dir", "left_arm": "braco_esq", "legs": "pernas"}
MINI_FILES = [["mini_cabeca"], ["mini_braco_dir_1"], ["mini_braco_dir_2"], ["mini_braco_esq_1"],
              ["mini_braco_esq_2"], ["mini_pernas_1", "mini_pernas_2", "mini_pernas_3"]]


def art_mini(folder, name):
    """Mini sprite de uma pasta de desenho (mini_*.png 16x16, formato do export_template): (paleta de origem com 16
    cores, [6 componentes 4bpp]); cores nos indices 1.. na ordem em que aparecem. Usado por gfx_port e decomp_navi."""
    from PIL import Image
    colors, comps = [], []
    for names in MINI_FILES:
        payload = bytearray()
        for nm in names:
            img = Image.open(folder / f"{nm}.png").convert("RGBA")
            if img.size != (16, 16):
                raise SystemExit(f"{nm}.png: o mini sprite e 16x16")
            idx = []
            for r, g, b_, a in img.getdata():
                if a < 128:
                    idx.append(0)
                    continue
                c = (r // 8 * 8, g // 8 * 8, b_ // 8 * 8)
                if c not in colors:
                    colors.append(c)
                idx.append(colors.index(c) + 1)
            for ty in range(2):
                for tx in range(2):
                    for y in range(8):
                        for x in range(0, 8, 2):
                            q = (ty * 8 + y) * 16 + tx * 8 + x
                            payload.append(idx[q] | idx[q + 1] << 4)
        comps.append(bytes(payload))
    if len(colors) > 15:
        raise SystemExit(f"mini sprite de {name}: {len(colors)} cores (max. 15)")
    src_pal = [mini_palette.rgb(0)] + [np.array(c, float) for c in colors]
    src_pal += [mini_palette.rgb(0)] * (16 - len(src_pal))
    return src_pal, comps


def png_tiles(path, width, height):
    """PNG indexado (indice 0 = transparente) -> tiles 4bpp na ordem do jogo (linha a linha)."""
    from PIL import Image
    img = Image.open(path)
    if img.mode != "P" or img.size != (width, height):
        raise SystemExit(f"{path}: precisa ser PNG indexado {width}x{height} (rode tools/check_template.py --limpar)")
    px = img.load()
    out = bytearray()
    for ty in range(height // 8):
        for tx in range(width // 8):
            for y in range(8):
                for x in range(0, 8, 2):
                    lo, hi = px[tx * 8 + x, ty * 8 + y], px[tx * 8 + x + 1, ty * 8 + y]
                    if lo > 15 or hi > 15:
                        raise SystemExit(f"{path}: indice de cor > 15")
                    out.append(lo | hi << 4)
    return bytes(out), img.getpalette()[:48]


def form_mini_components(path, log):
    """Mini da forma de Medachange (veiculo de uma peca so): PNG 32x24, origem nos pes (meio da borda de baixo).
    O jogo monta o mini com 4 objetos 16x16 (init_battle_medabot_sprites): cabeca (x 8..24, y 0..16), braco dir.
    (0..16, 8..24), braco esq. (16..32, 8..24), pernas (8..24, 8..24). Corte sem sobreposicao: cabeca = faixa de cima
    (y 0..8), bracos = as metades de baixo, pernas vazias. Lado do jogador usa os quadros 1 (braco dir.) e 4 (braco
    esq.); o lado espelhado usa 2 e 3 com flip: 1 e 3 = metade esquerda, 2 e 4 = metade direita. Cantos de cima (8x8)
    ficam de fora. Cores: ate 15 (check_template.reduce_colors, libimagequant)."""
    from PIL import Image
    sys.path.insert(0, str(ROOT / "tools"))
    from check_template import reduce_colors, snap
    img = Image.open(path).convert("RGBA")
    if img.size != (32, 24):
        raise SystemExit(f"{path}: o mini da forma e 32x24 (largura x altura)")
    px = img.load()
    lost = sum(1 for x in list(range(8)) + list(range(24, 32)) for y in range(8) if px[x, y][3] >= 128)
    if lost:
        log.append(f"{path.name}: {lost} pixels nos cantos de cima (8x8) ficam de fora do mini")
    pixels = [px[x, y][:3] for y in range(24) for x in range(32) if px[x, y][3] >= 128]
    cmap, _ = reduce_colors(pixels)
    colors = sorted(set(cmap.values()))
    index = {c: i + 1 for i, c in enumerate(colors)}

    def block(x0, y0, rows):
        grid = [[0] * 16 for _ in range(16)]
        for y in range(16):
            for x in range(16):
                cx, cy = x0 + x, y0 + y
                if y < rows and 0 <= cx < 32 and 0 <= cy < 24 and px[cx, cy][3] >= 128:
                    grid[y][x] = index[cmap[snap(px[cx, cy][:3])]]
        out = bytearray()
        for ty in range(2):
            for tx in range(2):
                for y in range(8):
                    for x in range(0, 8, 2):
                        out.append(grid[ty * 8 + y][tx * 8 + x] | grid[ty * 8 + y][tx * 8 + x + 1] << 4)
        return bytes(out)
    head = block(8, 0, 8)
    left, right = block(0, 8, 16), block(16, 8, 16)
    empty = bytes(128)
    comps = [head, left, right, left, right, empty * 3]
    pal = [mini_palette.rgb(0)] + [np.array(c, float) for c in colors]
    pal += [mini_palette.rgb(0)] * (16 - len(pal))
    log.append(f"mini da forma <- {path.name}: {len(set(snap(c) for c in pixels))} -> {len(colors)} cores")
    return comps, pal


def palette_bgr555(rgb48):
    rgb48 = rgb48 + [0] * (48 - len(rgb48))
    return struct.pack("<16H", *(min(31, rgb48[3 * i] // 8) | min(31, rgb48[3 * i + 1] // 8) << 5 |
                                 min(31, rgb48[3 * i + 2] // 8) << 10 for i in range(16)))


def port_graphics(rom, original, bots, gfx_at, alloc, log, use_art=True):
    ported = [b for b in bots if "graphics_source" in b or "recolor" in b or (use_art and "art" in b)]
    if not ported and not any((b.get("medachange") or {}).get("mini") for b in bots):
        return
    state = DescriptorState(original.data)
    copied = {}              # (rom, offset) -> novo ponteiro absoluto
    recolor_jobs = []        # (bot, paleta de origem, componentes) do mini sprite
    sprites_at = gfx_at["BATTLE_SPRITES"][1]
    sources = {}

    def copy_blob(src_name, src, ptr, palette):
        if ptr == 0:
            return 0
        key = (src_name, ptr)
        if key not in copied:
            off = ptr - GBA_BASE
            size = PALETTE_SIZE if palette else compressed_size(src, off)
            at = alloc.take(size)
            rom.data[at:at + size] = src[off:off + size]
            copied[key] = GBA_BASE + at
        return copied[key]

    def recolor_native(b):
        """Bot que reaproveita os desenhos de um bot nativo (graphics_from) com cores proprias:
        cada cor de "recolor" (#rrggbb -> #rrggbb) troca nas paletas das imagens grandes (vagas novas
        de seletor apontando p/ a mesma imagem) e na paleta de origem do mini sprite."""
        bid = b["bot_id"]
        cmap = {hex_bgr555(k): hex_bgr555(v) for k, v in b["recolor"].items()}

        def mapped(c):
            return cmap.get(c & 0x7FFF, c & 0x7FFF) | (c & 0x8000)

        new_palettes = {}
        moldes = set()
        for kind, size in PREVIEW_ROW.items():
            row_at = gfx_at[PREVIEW_GFX[kind]][1] + bid * size
            for i in range(size // 4):
                e = u32(rom.data, row_at + 4 * i)
                d = e & 0x3F
                if d == 0:
                    continue
                table, taken = state.table(d), state.taken(d)
                sels = entry_selectors(e)
                pairs = [(table[s * 2], table[s * 2 + 1]) for s in sels]
                if all(pal == img for img, pal in pairs):
                    continue                       # parte sem paleta propria: usa a da principal
                new_sel = free_selector(taken, len(sels))
                if new_sel is None:
                    raise SystemExit(f"molde {d} sem seletor livre (256 vagas esgotadas)")
                for k, (img, pal) in enumerate(pairs):
                    taken.add(new_sel + k)
                    if pal != img and pal not in new_palettes:
                        words = struct.unpack_from("<16H", original.data, pal - GBA_BASE)
                        at = alloc.take(PALETTE_SIZE)
                        struct.pack_into("<16H", rom.data, at, *(mapped(c) for c in words))
                        new_palettes[pal] = GBA_BASE + at
                    table[(new_sel + k) * 2:(new_sel + k) * 2 + 2] = [img, new_palettes.get(pal, img)]
                struct.pack_into("<I", rom.data, row_at + 4 * i,
                                 (e & ~0x3F & ~(SELECTOR_MASK << 6)) | d | (new_sel << 6))
                moldes.add(d)

        sprites_at = gfx_at["BATTLE_SPRITES"][1]
        fam = rom.data[gfx_at["PALETTE_FAMILY"][1] + bid]
        comps = [malias_decompress(original.data, u32(rom.data, sprites_at + (bid * 6 + k) * 4) - GBA_BASE)[0]
                 for k in range(6)]
        words = struct.unpack_from("<16H", original.data, mini_palette.MINI_PALETTES + 32 * fam)
        src_pal = [mini_palette.rgb(mapped(c) & 0x7FFF) for c in words]
        recolor_jobs.append((b, src_pal, comps, False))
        log.append(f"cores de {b['name']} (bot {bid}): {len(new_palettes)} paletas novas; moldes {sorted(moldes)}")

    def import_art(b):
        """Desenhos proprios (campo "art" = pasta no formato do export_template, ja limpa): cada
        pedaco grande vira imagem nova (LZ77) numa vaga nova de seletor; a peca principal ganha a
        paleta do PNG e as secundarias usam a dela. O mini sprite entra no remapeamento de cores."""
        from PIL import Image
        bid, folder = b["bot_id"], ROOT / b["art"]
        moldes = set()
        for kind, size in PREVIEW_ROW.items():
            row_at = gfx_at[PREVIEW_GFX[kind]][1] + bid * size
            part_palette = None
            for i in range(size // 4):
                e = u32(rom.data, row_at + 4 * i)
                d = e & 0x3F
                if d == 0:
                    continue
                table, taken = state.table(d), state.taken(d)
                sels = entry_selectors(e)
                rec = u32(original.data, PREVIEW_DESCRIPTORS + 4 * d) - GBA_BASE
                w, h = original.data[rec + 0x13], original.data[rec + 0x12]   # +0x13 largura, +0x12 altura
                new_sel = free_selector(taken, len(sels))
                if new_sel is None:
                    raise SystemExit(f"molde {d} sem seletor livre (256 vagas esgotadas)")
                own_size = False
                for k, s in enumerate(sels):
                    suffix = f"_pose{k + 1}" if len(sels) > 1 else ""
                    path = folder / f"large_{KIND_PT[kind]}_{i + 1}_m{d:02d}{suffix}.png"
                    with Image.open(path) as probe:
                        if probe.size != (w, h):
                            # tamanho proprio: o build da decomp da a este pedaco um molde proprio com esse desenho
                            # (anim_molds "picture"); aqui so confere a paleta da peca
                            if len(sels) > 1:
                                raise SystemExit(f"{path.name}: pedaco com poses tem que ficar {w}x{h} (por enquanto)")
                            if probe.mode != "P":
                                raise SystemExit(f"{path.name}: precisa ser PNG indexado (check_template --limpar)")
                            pal = probe.getpalette()[:48]
                            if part_palette is None:
                                part_palette = pal
                            elif pal != part_palette:
                                raise SystemExit(f"{path.name}: paleta diferente dos outros pedacos da peca")
                            own_size = True
                            break
                    raw, pal = png_tiles(path, w, h)
                    if part_palette is None:
                        part_palette = pal
                    elif pal != part_palette:
                        raise SystemExit(f"{path.name}: paleta diferente dos outros pedacos da peca")
                    blob = lz77_store(raw)
                    at = alloc.take(len(blob))
                    rom.data[at:at + len(blob)] = blob
                    img_ptr = GBA_BASE + at
                    own_palette = table[s * 2 + 1] != table[s * 2]
                    if own_palette:
                        pat = alloc.take(PALETTE_SIZE)
                        rom.data[pat:pat + PALETTE_SIZE] = palette_bgr555(pal)
                        pal_ptr = GBA_BASE + pat
                    else:
                        pal_ptr = img_ptr
                    taken.add(new_sel + k)
                    table[(new_sel + k) * 2:(new_sel + k) * 2 + 2] = [img_ptr, pal_ptr]
                if own_size:
                    log.append(f"{b['name']}: pedaco m{d:02d} com tamanho proprio (molde proprio no build da decomp)")
                    continue
                struct.pack_into("<I", rom.data, row_at + 4 * i,
                                 (e & ~0x3F & ~(SELECTOR_MASK << 6)) | d | (new_sel << 6))
                moldes.add(d)

        src_pal, comps = art_mini(folder, b["name"])
        recolor_jobs.append((b, src_pal, comps, False))
        log.append(f"desenhos de {b['name']} (bot {bid}) <- {b['art']}; moldes {sorted(moldes)}")

    for b in ported:
        if use_art and "art" in b:
            import_art(b)
            continue
        if "recolor" in b:
            recolor_native(b)
            continue
        gs, bid = b["graphics_source"], b["bot_id"]
        src = sources.setdefault(gs["rom"], __import__("roms").by_name(gs["rom"]).read_bytes())
        t, sb = gs["tables"], gs["bot"]

        for k in range(6):
            ptr = u32(src, t["battle_sprites"] + (sb * 6 + k) * 4)
            struct.pack_into("<I", rom.data, sprites_at + (bid * 6 + k) * 4, copy_blob(gs["rom"], src, ptr, False))
        rom.data[gfx_at["PALETTE_FAMILY"][1] + bid] = src[t["palette_family"] + sb]
        rom.data[gfx_at["MOVE_STYLE"][1] + bid] = src[t["move_style"] + sb]
        if "mini_palettes" in t:            # paletas proprias do jogo de origem -> recolorir
            fam = src[t["palette_family"] + sb]
            comps = [malias_decompress(src, u32(src, t["battle_sprites"] + (sb * 6 + k) * 4) - GBA_BASE)[0]
                     for k in range(6)]
            recolor_jobs.append((b, mini_palette.palettes(src, t["mini_palettes"] + 32 * fam, 1)[0], comps, True))

        moldes = set()
        native = gs.get("native_previews", {})     # {"right_arm": 42}: imagem grande da peca de um bot nativo
        for kind, size in PREVIEW_ROW.items():
            if kind in native:
                src_row = PREVIEW_TABLES[kind] + native[kind] * size
                rom.data[gfx_at[PREVIEW_GFX[kind]][1] + bid * size:
                         gfx_at[PREVIEW_GFX[kind]][1] + (bid + 1) * size] = original.data[src_row:src_row + size]
                continue
            row = [u32(src, t[f"preview_{kind}"] + sb * size + 4 * i) for i in range(size // 4)]
            live = [e for e in row if e & 0x3F]
            # Clones (IDs >= 50) quebram a batalha: o estado das pecas e um vetor de 50 posicoes por
            # molde (EWRAM 0x20260D0). So para experimento (force_clone); o normal e usar as vagas
            # 128-255 dos moldes originais (seletor de 8 bits).
            if gs.get("force_clone") and kind in ("right_arm", "left_arm"):
                mapping = {e & 0x3F: state.clone_of(e & 0x3F) for e in live}
            else:
                mapping = {e & 0x3F: e & 0x3F for e in live}
            out = []
            for e in row:
                d = e & 0x3F
                if d == 0:
                    out.append(e)
                    continue
                nd = mapping[d]
                _, src_bt = descriptor_blob_table(src, t["preview_descriptors"], d)
                table, taken = state.table(nd), state.taken(nd)
                src_sels = entry_selectors(e)
                new_sel = free_selector(taken, len(src_sels))
                if new_sel is None:
                    raise SystemExit(f"molde {nd} sem seletor livre (256 vagas esgotadas)")
                for k, s in enumerate(src_sels):
                    taken.add(new_sel + k)
                    img_ptr, pal_ptr = u32(src, src_bt + 8 * s), u32(src, src_bt + 8 * s + 4)
                    new_img = copy_blob(gs["rom"], src, img_ptr, False)
                    new_pal = new_img if pal_ptr == img_ptr else copy_blob(gs["rom"], src, pal_ptr, True)
                    table[(new_sel + k) * 2:(new_sel + k) * 2 + 2] = [new_img, new_pal]
                out.append((e & ~0x3F & ~(SELECTOR_MASK << 6)) | nd | (new_sel << 6))
                moldes.add(nd)
            row_at = gfx_at[PREVIEW_GFX[kind]][1] + bid * size
            for i, e in enumerate(out):
                struct.pack_into("<I", rom.data, row_at + 4 * i, e)
        log.append(f"graficos de {b['name']} (bot {bid}) <- {gs['rom'][:30]}... bot {sb}; moldes {sorted(moldes)}")

    # mini da forma de Medachange (medachange.mini) de qualquer bot, com ou sem desenhos proprios: tarefa de paleta propria
    for b in bots:
        form_mini = (b.get("medachange") or {}).get("mini")
        if form_mini:
            fcomps, fpal = form_mini_components(ROOT / form_mini, log)
            recolor_jobs.append(({"name": b["name"] + " (forma)", "_form_of": b}, fpal, fcomps, False))

    if recolor_jobs:
        base = mini_palette.palettes(original.data, mini_palette.MINI_PALETTES, 3)
        extra, results = mini_palette.recolor([(b["name"], p, c, s) for b, p, c, s in recolor_jobs], base, log)
        at = mini_palette.MINI_PALETTES + 32 * mini_palette.EXTRA_BANK
        assert not any(original.data[at + 2:at + 32]), "banco 3 das paletas de mini sprite nao esta livre"
        rom.data[at:at + 32] = extra
        for (b, _, _, _), (bank, comps) in zip(recolor_jobs, results):
            if "_form_of" in b:   # mini da forma de Medachange: vai na linha da forma (decomp_expand), nao aqui
                b["_form_of"]["_form_mini"] = (bank, [mini_palette.malias_store(p) for p in comps])
                continue
            for k, payload in enumerate(comps):
                blob = mini_palette.malias_store(payload)
                p = alloc.take(len(blob))
                rom.data[p:p + len(blob)] = blob
                struct.pack_into("<I", rom.data, sprites_at + (b["bot_id"] * 6 + k) * 4, GBA_BASE + p)
            rom.data[gfx_at["PALETTE_FAMILY"][1] + b["bot_id"]] = bank
        log.append(f"paleta extra dos mini sprites no banco {mini_palette.EXTRA_BANK} (0x{at:06X})")

    state.write(rom, alloc, log)
    log.append(f"previews: {len(state.tables)} listas de blobs recriadas, clones {state.clones}, "
               f"{len(copied)} blocos copiados")
