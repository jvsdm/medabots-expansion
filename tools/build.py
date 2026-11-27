"""
build.py - Gera ROM expandida (16 MB) com N bots a partir da ROM original + data/bots/*.json.

Uso:  python tools/build.py [--shop SHOP:SLOT:BOT ...] [--out caminho.gba]
      ex.: --shop 0:2:120   (loja 0, slot 2 vende o bot 120)

Etapas:
  1. Expande para 16 MB.
  2. Tabelas por bot em TABLE_AREA, com N bots + 2 linhas de Tinpet (IDs N e N+1):
       stats, nomes de bot, nomes de peca, sprites de batalha, familia de paleta, 4 previews.
     Bot novo copia os graficos do bot em "graphics_from" (padrao: Metabee, 43).
  3. Reaponta os literal pools do codigo para as tabelas novas.
  4. Troca as constantes 119/120/121 por N-1/N/N+1 (tools/patches.py).
  5. Inventario: move p/ EWRAM com 240 slots por tipo (stride <<5), save/load byte a byte.
  6. Opcional: lojas.

Saves feitos com a ROM original NAO sao compativeis (formato do inventario no save mudou).
"""
import argparse
import json
import struct
from pathlib import Path
import patches as P
from gfx_port import port_graphics
from medarom import (Rom, ROOT, GBA_BASE, BOT_COUNT, PART_KINDS, PART_SIZE, PART_STATS,
                     BOT_NAMES, PART_NAMES, BATTLE_SPRITES, PALETTE_FAMILY, MOVE_STYLE, PREVIEW_TABLES,
                     SHOP_TABLE_SIG, part_fields, encode_text)

ROM_SIZE = 0x1000000
TABLE_AREA = 0xC00000      # longe de 0x850000 (onde o legado/insert_text_v2 gravava traducoes)
CODE_END = 0x0A0000
MAX_BOTS = 240             # inventario: 240 x 2 B x 4 tipos = 0x780 = espaco do save
ORIG_GFX_ROWS = 122        # 120 bots + Tinpet M/F
DEFAULT_GFX_FROM = 43      # Metabee

# (nome, base original, bytes por bot)
GFX_TABLES = [
    ("BATTLE_SPRITES", BATTLE_SPRITES, 24),
    ("PALETTE_FAMILY", PALETTE_FAMILY, 1),
    ("MOVE_STYLE", MOVE_STYLE, 1),
    ("PREVIEW_HEAD", PREVIEW_TABLES["head"], 16),
    ("PREVIEW_RIGHT_ARM", PREVIEW_TABLES["right_arm"], 16),
    ("PREVIEW_LEFT_ARM", PREVIEW_TABLES["left_arm"], 16),
    ("PREVIEW_LEGS", PREVIEW_TABLES["legs"], 32),
]


class Allocator:
    def __init__(self, start):
        self.next = start

    def take(self, size, align=4):
        self.next = (self.next + align - 1) & ~(align - 1)
        o, self.next = self.next, self.next + size
        return o


def load_bots(with_shingata=True, with_art=True):
    files = sorted((ROOT / "data" / "bots").glob("*.json"))
    bots = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    if not with_art:
        bots = [b for b in bots if not b.get("local_only")]
    if not with_shingata:
        bots = [b for b in bots if "Shingata" not in b.get("graphics_source", {}).get("rom", "")]
    ids = [b["bot_id"] for b in bots]
    if ids != list(range(len(bots))):
        raise SystemExit(f"bot_ids precisam ser 0..N-1 sem buracos; achei {ids[:3]}...{ids[-3:]}")
    if len(bots) > MAX_BOTS:
        raise SystemExit(f"{len(bots)} bots > limite {MAX_BOTS}")
    return bots


def code_pools(rom, target):
    return [o for o in range(0, CODE_END, 4) if rom.u32(o) == target]


def repoint(rom, old, new, name, log):
    """old/new sao enderecos absolutos do GBA (0x08xxxxxx ROM, 0x02/0x03xxxxxx RAM)."""
    pools = code_pools(rom, old)
    if not pools:
        raise SystemExit(f"{name}: nenhum ponteiro encontrado")
    for o in pools:
        struct.pack_into("<I", rom.data, o, new)
    log.append(f"{name}: {len(pools)} ponteiros -> 0x{new:08X}")


def patch_imm(rom, pc, expected, new):
    """Troca o imm8 de mov/cmp/add/sub Thumb (formato 3), conferindo o valor antigo."""
    op = rom.data[pc + 1]
    if not (0x20 <= op <= 0x3F) or rom.data[pc] != expected:
        raise SystemExit(f"0x{pc:06X}: esperava imm 0x{expected:X}, achei {rom.data[pc + 1]:02X}{rom.data[pc]:02X}")
    rom.data[pc] = new


def patch_hw(rom, pc, old, new):
    cur = struct.unpack_from("<H", rom.data, pc)[0]
    if cur != old:
        raise SystemExit(f"0x{pc:06X}: esperava {old:04X}, achei {cur:04X}")
    struct.pack_into("<H", rom.data, pc, new)


def patch_literal(rom, at, old, new):
    if rom.u32(at) != old:
        raise SystemExit(f"literal 0x{at:06X}: esperava 0x{old:X}, achei 0x{rom.u32(at):X}")
    struct.pack_into("<I", rom.data, at, new)


def thumb_ldr_lit(pc, rd, lit_addr):
    off = lit_addr - ((pc + 4) & ~3)
    assert off % 4 == 0 and 0 <= off < 1024
    return 0x4800 | (rd << 8) | (off // 4)


def repair_italic_font(rom, log):
    """Devolve os tons escuros da fonte italica da ROM EU (ver patches.ITALIC_FONT)."""
    base, size = P.ITALIC_FONT, P.ITALIC_FONT_SIZE
    pixels = [(b >> (4 * k)) & 15 for b in rom.data[base:base + size] for k in (0, 1)]
    if 0 not in pixels or any(v >= 0xB for v in pixels):
        log.append("fonte italica: sem o defeito da ROM EU, mantida")
        return
    fixed = 0
    for glyph in range(size // 64):
        g = pixels[glyph * 128:(glyph + 1) * 128]          # 16 linhas x 8 pixels (2 tiles 8x8)

        def at(y, x):
            return g[(y // 8) * 64 + (y % 8) * 8 + x]

        new = list(g)
        for y in range(16):
            for x in range(8):
                if at(y, x) != 0:
                    continue
                ink = sum(1 for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))
                          if 0 <= y + dy < 16 and 0 <= x + dx < 8 and at(y + dy, x + dx) != 1)
                new[(y // 8) * 64 + (y % 8) * 8 + x] = {4: 0xF, 3: 0xE}.get(ink, 0xD)
                fixed += 1
        for i in range(64):
            rom.data[base + glyph * 64 + i] = new[2 * i] | new[2 * i + 1] << 4
    log.append(f"fonte italica: {fixed} pixels reconstruidos (0x{base:06X})")


def patch_starter(rom, log):
    """Reescreve o fim de 0x44B58 (bot inicial) para o stride novo de 480 B por tipo."""
    bot = rom.data[P.STARTER_ID_AT]
    if rom.data[P.STARTER_ID_AT + 1] != 0x20:
        raise SystemExit("rotina do bot inicial diferente do esperado")
    base = bot * 2 + 1
    ra, la, legs = 480 + base, 960 + base, 1440 + base
    lit_a, lit_b = 0x044BA0, 0x044BA4
    patch_literal(rom, lit_a, 240 + base, ra)
    patch_literal(rom, lit_b, 720 + base, la)
    code = [
        thumb_ldr_lit(0x044B7E, 3, lit_a),  # ldr r3, =RA
        0x18C8,                             # adds r0, r1, r3
        0x7002,                             # strb r2, [r0]
        thumb_ldr_lit(0x044B84, 0, lit_b),  # ldr r0, =LA
        0x1808,                             # adds r0, r1, r0
        0x7002,                             # strb r2, [r0]
        0x30F0,                             # adds r0, #0xF0
        0x30F0,                             # adds r0, #0xF0   (LA + 0x1E0 = pernas)
        0x7002,                             # strb r2, [r0]
        0x4770,                             # bx lr
    ]
    assert la + 0x1E0 == legs
    for i, hw in enumerate(code):
        struct.pack_into("<H", rom.data, 0x044B7E + i * 2, hw)
    log.append(f"bot inicial {bot}: offsets {base:#x}/{ra:#x}/{la:#x}/{legs:#x}")


def build_rom(bots, shops=(), preco_teste=None, use_art=True, data_only=False):
    """ROM expandida em memoria para a lista `bots` (bot_id 0..N-1). Devolve (bytes, linhas de log).
    Usado tambem por tools/decomp_expand.py --bot-list (so os bots escolhidos, sem arquivo intermediario).
    data_only: so as tabelas e os graficos (o que a descompilacao leva, tools/decomp_lift_binary.py), sem os remendos
    de codigo da ROM europeia; serve sobre qualquer versao com perfil (ex.: Rokusho USA, MEDABOTS_VERSION=rokusho_us)."""
    rom, original = Rom(), Rom()
    rom.data += b"\xFF" * (ROM_SIZE - len(rom.data))
    ids = [b["bot_id"] for b in bots]
    if ids != list(range(len(bots))):
        raise SystemExit(f"bot_ids precisam ser 0..N-1 sem buracos; achei {ids[:3]}...{ids[-3:]}")
    n = len(bots)
    tinpet = P.TINPET_ID
    if n > tinpet:
        raise SystemExit(f"{n} bots: o maximo e {tinpet} (Tinpet fixo em {tinpet}/{tinpet + 1})")
    rows = tinpet + 2                             # bots, vagas vazias, Tinpet M/F
    shop_bots = {int(spec.split(":")[2], 0) for spec in shops}
    alloc = Allocator(TABLE_AREA)
    log = [f"{n} bots; Tinpet fixo = {tinpet}/{tinpet + 1}; IDs {n}-{tinpet - 1} vazios"]
    # ---- stats ----
    stats_at = alloc.take(rows * 4 * PART_SIZE)
    rom.data[stats_at:stats_at + rows * 4 * PART_SIZE] = bytes(rows * 4 * PART_SIZE)
    for b in bots:
        for k, kind in enumerate(PART_KINDS):
            st = dict(b["parts"][kind]["stats"])
            if preco_teste is not None and (b["bot_id"] >= BOT_COUNT or b["bot_id"] in shop_bots):
                st["buy_price"] = preco_teste    # byte 11 = preco de compra / 100
            raw = bytes(st[f] for f in part_fields(kind))
            o = stats_at + (b["bot_id"] * 4 + k) * PART_SIZE
            rom.data[o:o + PART_SIZE] = raw

    # ---- nomes ----
    def string_ptr(text, table=None, index=None):
        if table is not None:
            p = original.ptr_at(table, index)
            if original.text(p) == text:
                return p
        enc = encode_text(text)
        o = alloc.take(len(enc), align=1)
        rom.data[o:o + len(enc)] = enc
        return o

    tinpet_name = string_ptr("TINPET")
    bot_names_at = alloc.take(rows * 4)
    part_names_at = alloc.take(rows * 4 * 4)
    for bid in range(rows):
        if bid < n:
            b = bots[bid]
            orig = bid < BOT_COUNT
            bp = string_ptr(b["name"], BOT_NAMES if orig else None, bid if orig else None)
            pps = [string_ptr(b["parts"][kind]["name"], PART_NAMES if orig else None,
                              bid * 4 + k if orig else None) for k, kind in enumerate(PART_KINDS)]
        else:
            bp, pps = tinpet_name, [tinpet_name] * 4
        struct.pack_into("<I", rom.data, bot_names_at + bid * 4, GBA_BASE + bp)
        for k, p in enumerate(pps):
            struct.pack_into("<I", rom.data, part_names_at + (bid * 4 + k) * 4, GBA_BASE + p)

    # ---- graficos ----
    def source_row(bid):
        if bid < BOT_COUNT:
            return bid
        if bid >= tinpet:
            return BOT_COUNT + (bid - tinpet)     # Tinpet M/F originais (120/121)
        if bid >= n:
            return BOT_COUNT                      # vaga vazia: graficos do Tinpet (so enchimento)
        return bots[bid].get("graphics_from", DEFAULT_GFX_FROM)

    # "graphics_from_parts": {"legs": 89} = o esqueleto (linha de moldes) dessa peca vem de outro bot nativo
    # (ex.: perna de peca unica 64x64 do Tankar, molde 30); o resto segue graphics_from (2026-11-23)
    PART_TABLE = {"PREVIEW_HEAD": "head", "PREVIEW_RIGHT_ARM": "right_arm", "PREVIEW_LEFT_ARM": "left_arm",
                  "PREVIEW_LEGS": "legs"}
    gfx_at = {}
    for name, base, size in GFX_TABLES:
        at = alloc.take(rows * size)
        for bid in range(rows):
            row = source_row(bid)
            if bid < n and PART_TABLE.get(name) in bots[bid].get("graphics_from_parts", {}):
                row = bots[bid]["graphics_from_parts"][PART_TABLE[name]]
            src = base + row * size
            rom.data[at + bid * size:at + (bid + 1) * size] = original.data[src:src + size]
        if name == "PALETTE_FAMILY":
            for b in bots:
                if b["bot_id"] < BOT_COUNT and "palette_family" in b:
                    rom.data[at + b["bot_id"]] = b["palette_family"]
        gfx_at[name] = (base, at)
    port_graphics(rom, original, bots, gfx_at, alloc, log, use_art=use_art)
    if data_only:      # enderecos das tabelas no formato que o tools/decomp_lift_binary.py le
        for name, at in (("PART_STATS", stats_at), ("BOT_NAMES", bot_names_at), ("PART_NAMES", part_names_at)):
            log.append(f"{name}: 0 ponteiros -> 0x{GBA_BASE + at:08X}")
        for name, (_old, new) in gfx_at.items():
            log.append(f"{name}: 0 ponteiros -> 0x{GBA_BASE + new:08X}")
        log.append(f"tabelas 0x{TABLE_AREA:06X}-0x{alloc.next:06X}")
        return bytes(rom.data), log

    # ---- reapontamento ----
    repoint(rom, GBA_BASE + PART_STATS, GBA_BASE + stats_at, "PART_STATS", log)
    repoint(rom, GBA_BASE + BOT_NAMES, GBA_BASE + bot_names_at, "BOT_NAMES", log)
    repoint(rom, GBA_BASE + PART_NAMES, GBA_BASE + part_names_at, "PART_NAMES", log)
    for name, (old, new) in gfx_at.items():
        repoint(rom, GBA_BASE + old, GBA_BASE + new, name, log)

    # ---- constantes de quantidade de bots ----
    for pc in P.BOT_MAX_SITES:
        patch_imm(rom, pc, 0x77, n - 1)
    for pc in P.TINPET_CHECK_SITES + P.TINPET_SITES:
        patch_imm(rom, pc, 0x78, tinpet)
    for pc in P.SHOP_SCROLL_ADDS:
        patch_imm(rom, pc, 0x78, n)
    for pc in P.TINPET_F_SITES:
        patch_imm(rom, pc, 0x79, tinpet + 1)
    last_page = (n + 3) // 4 - 1
    for pc in P.PAGE_LAST_SITES:
        patch_imm(rom, pc, 0x1D, last_page)
    pages = last_page + 1
    if not 10 <= pages <= 99:
        raise SystemExit(f"{pages} paginas: o '/30' so cabe 2 digitos")
    tens, units = divmod(pages, 10)
    new = {0x4F1560: 0x60 + 2 * tens, 0x4F1561: 0x71, 0x4F1562: 0x60 + 2 * units, 0x4F1563: 0x71,
           0x4F1580: 0x61 + 2 * tens, 0x4F1581: 0x71, 0x4F1583: 0x61 + 2 * units}
    for at, (old, _) in P.PAGE_TOTAL_BYTES.items():
        if rom.data[at] != old:
            raise SystemExit(f"tilemap do '/30' diferente do esperado em 0x{at:06X}")
        rom.data[at] = new[at]
    log.append(f"constantes: {len(P.BOT_MAX_SITES)} x N-1, {len(P.SHOP_SCROLL_ADDS)} x N (loja), "
               f"{len(P.TINPET_CHECK_SITES)} Tinpet?, "
               f"{len(P.TINPET_SITES)} Tinpet, {len(P.TINPET_F_SITES)} Tinpet F, "
               f"{len(P.PAGE_LAST_SITES)} paginas ({last_page + 1})")

    # ---- inventario ----
    repoint(rom, P.INV_OLD, P.INV_NEW, "INVENTARIO", log)
    for pc in P.INV_STRIDE_SITES:
        hw = struct.unpack_from("<H", rom.data, pc)[0]
        if hw >> 11 != 0 or (hw >> 6) & 31 != 4:
            raise SystemExit(f"stride 0x{pc:06X}: esperava lsls #4, achei {hw:04X}")
        struct.pack_into("<H", rom.data, pc, (hw & ~(31 << 6)) | (5 << 6))
    for pc, old, new in P.INV_HALFWORD_PATCHES:
        patch_hw(rom, pc, old, new)
    for at, old, new in P.INV_LITERAL_PATCHES:
        patch_literal(rom, at, old, new)
    patch_starter(rom, log)

    repair_italic_font(rom, log)

    # ---- seletor de imagem das pecas: 7 -> 8 bits (256 vagas por molde) ----
    for pc, old, new in P.SELECTOR_8BIT_PATCH:
        patch_hw(rom, pc, old, new)
    log.append("seletor de pecas: 8 bits (0x45ECC)")

    # ---- lacos com contador de 1 byte com sinal (travam com N > 128) ----
    for pc, old, new in P.UNSIGNED_LOOP_PATCHES:
        patch_hw(rom, pc, old, new)
    log.append(f"lacos com contador sem sinal: {len(P.UNSIGNED_LOOP_PATCHES)}")

    # ---- loja: rolagem logo apos o vetor de quantidades; ultimo item da lista de venda ----
    for at in P.SHOP_SCROLL_LITERALS:
        cur = rom.u32(at)
        if cur not in (P.SHOP_SCROLL_BASE + 120, P.SHOP_SCROLL_BASE + n):
            raise SystemExit(f"literal da rolagem 0x{at:06X}: valor inesperado 0x{cur:X}")
        struct.pack_into("<I", rom.data, at, P.SHOP_SCROLL_BASE + n)
    patch_literal(rom, P.SHOP_ITEMS_LAST_LITERAL, P.SHOP_ITEMS_BASE + 119 * 8, P.SHOP_ITEMS_BASE + (n - 1) * 8)
    log.append(f"loja: rolagem em 0x{P.SHOP_SCROLL_BASE + n:08X} ({len(P.SHOP_SCROLL_LITERALS)} literais), "
               f"ultimo item em 0x{P.SHOP_ITEMS_BASE + (n - 1) * 8:08X}")

    # ---- lojas ----
    shop_base = rom.find(SHOP_TABLE_SIG)
    for spec in shops:
        shop, slot, bot = (int(x, 0) for x in spec.split(":"))
        if not (0 <= shop < 15 and 0 <= slot < 4 and 0 <= bot < n):
            raise SystemExit(f"--shop invalido: {spec}")
        rom.data[shop_base + shop * 4 + slot] = bot
        log.append(f"loja {shop} slot {slot} = bot {bot}")

    log.append(f"tabelas 0x{TABLE_AREA:06X}-0x{alloc.next:06X}")
    return bytes(rom.data), log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", action="append", default=[], help="SHOP:SLOT:BOT")
    ap.add_argument("--out", default=str(ROOT / "build" / "Medabots_expanded.gba"))
    ap.add_argument("--sem-shingata", action="store_true",
                    help="nao inclui os bots portados do Shingata (base expandida so com a ROM EU)")
    ap.add_argument("--sem-arte", action="store_true",
                    help="ignora o campo 'art' (desenhos locais); gera o mesmo que o Toolkit")
    ap.add_argument("--preco-teste", type=int, metavar="LIBRAS",
                    help="preco provisorio das pecas dos bots novos (ID >= 120) e dos bots postos na loja via --shop; nao altera os JSONs")
    args = ap.parse_args()
    bots = load_bots(with_shingata=not args.sem_shingata, with_art=not args.sem_arte)
    data, log = build_rom(bots, args.shop, args.preco_teste, use_art=not args.sem_arte)
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(data)
    log[-1] += f" -> {out}"
    print("\n".join(log))


if __name__ == "__main__":
    main()
