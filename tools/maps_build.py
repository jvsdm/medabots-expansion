"""maps_build.py - Gera os dados de area a partir de data/maps (M1 do pc/research/MAPAS_EVENTOS_PLANO.md).

--verify: remonta cada segmento e cada grafico a partir dos arquivos e compara com o baserom.
--asm ARVORE: escreve ARVORE/asm/maps_area_data.s (incluido por data/data_083AB9D0.s no lugar dos blocos de
gAreaBgPalettes a gAreaSpriteSheetIds): tabelas de ponteiros por area com rotulos e os dados de cada area montados de
data/maps; o que nao e dado de area (ex.: gRoomExitMessages) continua .incbin. Com data/maps igual ao jogo, a ROM sai
identica (make compare).

Uso: python tools/maps_build.py --verify | --asm build/scratch/decomp_rok [--maps data/maps]
"""
import argparse
import json
import struct
from pathlib import Path

from maps_inventory import DEC
from maps_lift import COL_CHARS

ROOT = Path(__file__).resolve().parents[1]


def area_dir(maps, owner):
    return maps / f"area_{owner:03d}"


def n_areas(maps):
    """Areas em data/maps (area_000.. sem buraco). As 192 primeiras sao as do jogo; as outras sao novas (M4)."""
    n = 0
    while (maps / f"area_{n:03d}" / "area.json").exists():
        n += 1
    return n


def load_areas(maps):
    return [json.loads((maps / f"area_{i:03d}/area.json").read_text(encoding="utf-8")) for i in range(n_areas(maps))]


def segment_bytes(maps, kind, owner):
    """Bytes do segmento `kind` do dono `owner`, remontados dos arquivos da area."""
    d = area_dir(maps, owner)
    if kind == "collision":
        rows = (d / "collision.txt").read_text(encoding="utf-8").split()
        out = bytes(COL_CHARS.index(c) for r in rows for c in r)
        return out + bytes.fromhex((d / "collision.tail").read_text(encoding="utf-8").strip() or "")
    j = json.loads((d / f"{kind}.json").read_text(encoding="utf-8"))
    if "hex" in j:
        return bytes.fromhex(j["hex"])
    out = bytearray()
    if kind == "warps":
        for w in j["warps"]:
            out += bytes([w["x"], w["y"], w["to_area"], w["dir"], *w["unused"], w["to_x"], w["to_y"]])
    elif kind == "exits":
        for e in j["exits"]:
            out += bytes([e["x"], e["y"], e["mask"], e["value"]])
    elif kind == "npcs":
        for n in j["npcs"]:
            mask = sum(1 << b for b in n["phases"])
            out += bytes([n["x"], n["y"]]) + struct.pack("<H", n["kind"] << 12 | n["event"]) + \
                bytes([n["anim"], n["load_order"]]) + struct.pack("<H", mask)
    return bytes(out) + bytes.fromhex(j["tail"])


KIND = {"gAreaCollisionMaps": "collision", "gAreaTileAnims": "tileanim", "gAreaExits": "exits", "gAreaWarps": "warps",
        "gAreaSpriteSheetIds": "sprites", "gAreaNpcRecords": "npcs"}


def verify(maps):
    rom = (DEC / "baserom.gba").read_bytes()
    lay = json.loads((maps / "_layout.json").read_text(encoding="utf-8"))
    bad = n = 0
    for table, segs in lay["segments"].items():
        for s in segs:
            at, ln = int(s["at"], 16), s["len"]
            got = segment_bytes(maps, KIND[table], s["owner"])
            n += 1
            if got != rom[at:at + ln]:
                bad += 1
                if bad <= 5:
                    print(f"DIFERENTE: {table} area {s['owner']} em {s['at']} ({len(got)} vs {ln} B)")
    for name, g in lay["gfx"].items():
        at, ln = int(g["at"], 16), g["len"]
        f = maps / "gfx" / f"{name}.{'pal' if name.startswith('palette') else 'lz'}"
        n += 1
        if f.read_bytes() != rom[at:at + ln]:
            bad += 1
            print(f"DIFERENTE: grafico {name}")
    # tabelas inline e ponteiros: conferidos no M1 pela build (make compare)
    print(f"ida e volta: {n - bad}/{n} pedacos iguais ao baserom")
    return bad == 0


# Regioes trocadas pelo asm gerado (enderecos USA fixos: o gerador roda de novo depois de instalado). Cada uma: rotulos
# do jogo que ficam nela (na ordem), tabelas de ponteiros por area e o arquivo gerado.
REGION_A = [("gAreaMapSizes", 0x3F8B74), ("gAreaBgTiles", 0x3F8CF4), ("gAreaAnimBgTiles", 0x3F8FF4),
            ("gAreaBgTilemaps", 0x3F92F4), ("gAreaBgPalettes", 0x3F9BF4), ("gAreaCollisionMaps", 0x4045A8), ("gAreaTileAnims", 0x4096F4),
            ("gAreaExits", 0x40FAF4), ("gRoomExitMessages", 0x411D54), ("gAreaWarps", 0x413114),
            ("gAreaSpriteSheetIds", 0x413514)]
REGION_A_END = 0x414394
REGION_B = [("gData_08480000", 0x480000), ("gAreaNpcRecords", 0x4837A0)]
REGION_B_START, REGION_B_END = 0x47ED40, 0x483AA0
REGIONS = {"area": ("asm/maps_area_data.s", REGION_A[0][1], REGION_A_END, REGION_A),
           "npc": ("asm/maps_npc_data.s", REGION_B_START, REGION_B_END, REGION_B)}
SEG_LABEL = {"collision": "Collision", "tileanim": "TileAnim", "exits": "Exits", "warps": "Warps", "sprites": "Sprites",
             "npcs": "Npcs"}
NL, TAB = chr(10), chr(9)


def byte_lines(data):
    return "".join(TAB + ".byte " + ", ".join(str(v) for v in data[i:i + 16]) + NL for i in range(0, len(data), 16))


def emit_region(maps, region):
    """asm de uma regiao, montado de data/maps: rotulos do jogo, tabelas de ponteiros por area (com rotulos) e os
    dados de cada area; o resto continua .incbin. Rotulo que cai no meio de um dado divide o dado ali."""
    from maps_inventory import NAREAS      # tamanho original das tabelas (as areas novas vem depois, mesmo rotulo)
    _, start, end, labels = REGIONS[region]
    addr = dict(labels)
    lay = json.loads((maps / "_layout.json").read_text(encoding="utf-8"))
    areas = load_areas(maps)
    items = []    # (endereco original, tamanho original, texto | bytes, rotulo do dado)
    if "gAreaMapSizes" in addr:
        items.append((addr["gAreaMapSizes"], 2 * NAREAS, byte_lines(bytes(
            [v for a in areas for v in a["size_8px"]] + [0, 0] * (len(areas) % 2))), None))   # alinhado a 4
        pieces = gfx_pieces(maps)

        def g(v):     # nome de grafico de data/maps/gfx ou endereco cru dentro do bloco de graficos
            return f"sAreaGfx_{v}" if not v.startswith("0x") else gfx_symbol(pieces, int(v, 16) - 0x08000000)
        for table, key in (("gAreaBgTiles", "tiles"), ("gAreaAnimBgTiles", "animtiles")):
            items.append((addr[table], 4 * NAREAS, "".join(f"{TAB}.4byte {g(a[key])}{NL}" for a in areas), None))
        items.append((addr["gAreaBgTilemaps"], 12 * NAREAS, "".join(
            f"{TAB}.4byte {g(a['tilemaps'])}, {g(a['tilemaps_unused'][0])}, {g(a['tilemaps_unused'][1])}{NL}"
            for a in areas), None))
    if "gAreaBgPalettes" in addr:
        items.append((addr["gAreaBgPalettes"], 4 * NAREAS, "".join(
            f"{TAB}.4byte sAreaGfx_{a['palette']}{NL}" for a in areas), None))
    for table, kind in KIND.items():
        for sg in lay["segments"][table]:
            at = int(sg["at"], 16)
            if start <= at < end:
                items.append((at, sg["len"], segment_bytes(maps, kind, sg["owner"]),
                              f"sArea{SEG_LABEL[kind]}{sg['owner']:03d}"))
        if table in addr:
            items.append((addr[table], 4 * NAREAS, "".join(
                f"{TAB}.4byte sArea{SEG_LABEL[kind]}{int(a[kind].split('_')[1]):03d}{NL}" for a in areas), None))
    items.sort(key=lambda x: x[0])
    marks = sorted(labels, key=lambda x: x[1])
    out = [f"{TAB}.section .rodata{NL}{NL}@ gerado por tools/maps_build.py a partir de data/maps (nao editar){NL}"]
    cur = start

    def label(name):
        out.append(f"{TAB}.global {name}{NL}{name}:{NL}")

    rom = (DEC / "baserom.gba").read_bytes()
    base = f"sMapsRegion_{region}"     # a regiao guarda as posicoes do jogo: endereco X = base + (X - start)
    out.append(f"{base}:{NL}")

    def incbin(a, b):
        """Trecho do baserom; palavra que aponta para dentro da regiao (ex.: os 202 ponteiros de gRoomExitMessages
        para as falas no bloco de gAreaExits) vira .4byte relativo, porque a regiao muda de lugar na build expandida
        (o .tsv dessa faixa sai no install). Conferido: sao os mesmos 394 ponteiros que o .tsv do jogo realocava."""
        p = a
        for w in range((a + 3) // 4 * 4, b - 3, 4):
            v = struct.unpack_from("<I", rom, w)[0]
            if 0x08000000 + start <= v < 0x08000000 + end:
                if w > p:
                    out.append(f'{TAB}.incbin "baserom.gba", 0x{p:X}, 0x{w - p:X}{NL}')
                out.append(f"{TAB}.4byte {base}+0x{v - 0x08000000 - start:X}{NL}")
                p = w + 4
        if b > p:
            out.append(f'{TAB}.incbin "baserom.gba", 0x{p:X}, 0x{b - p:X}{NL}')

    def gap(to):
        nonlocal cur
        while marks and cur <= marks[0][1] < to:      # rotulo do jogo dentro de um trecho .incbin
            n, at = marks.pop(0)
            if at > cur:
                incbin(cur, at)
                cur = at
            label(n)
        if to > cur:
            incbin(cur, to)
            cur = to

    grown = []    # dado que cresceu (ex.: NPC a mais na area): vai para o fim da regiao, o lugar antigo fica sem uso
    for at, ln, body, seglab in items:
        if at < cur:
            raise SystemExit(f"sobreposicao em 0x{at:X} (atual 0x{cur:X})")
        if not isinstance(body, str) and len(body) > ln:
            grown.append((seglab, body))
            continue
        gap(at)
        while marks and marks[0][1] == at:
            label(marks.pop(0)[0])
        if isinstance(body, str):
            out.append(body)
            cur = at + ln
            continue
        out.append(f"{seglab}:{NL}")
        data, pos = body, at
        while marks and pos < marks[0][1] < at + len(body):   # rotulo do jogo no meio do dado: divide
            n, m = marks.pop(0)
            out.append(byte_lines(data[:m - pos]))
            label(n)
            data, pos = data[m - pos:], m
        out.append(byte_lines(data))
        cur = at + len(body)
    gap(end)
    if marks:
        raise SystemExit(f"rotulos nao couberam na regiao: {marks}")
    # dado proprio que o jogo nao tinha (area nova, ou area que deixou de compartilhar o de outra): no fim da regiao
    extra = False
    for seglab, body in grown:
        extra = True
        out.append(f"{TAB}.align 2{NL}{seglab}:{NL}")
        out.append(byte_lines(body))
    for table, kind in KIND.items():
        if table not in addr:
            continue
        had = {sg["owner"] for sg in lay["segments"][table]}
        for a in areas:
            if a[kind] == f"area_{a['id']:03d}" and a["id"] not in had:
                extra = True
                out.append(f"{TAB}.align 2{NL}sArea{SEG_LABEL[kind]}{a['id']:03d}:{NL}")
                out.append(byte_lines(segment_bytes(maps, kind, a["id"])))
    if region == "area":
        # graficos novos (ex.: tilemap pintado no WPF, tools/wpf_maps_to_files.py): os que o jogo nao tinha
        for f in sorted((maps / "gfx").iterdir()):
            if f.stem not in lay["gfx"]:
                extra = True
                out.append(f'{TAB}.align 2{NL}{TAB}.global sAreaGfx_{f.stem}{NL}sAreaGfx_{f.stem}:{NL}'
                           f'{TAB}.incbin "graphics/maps/{f.name}"{NL}')
    if extra or len(areas) > NAREAS:
        out.append(f"{TAB}.align 2{NL}")      # o objeto seguinte no ld_script espera endereco alinhado
    return "".join(out)


def _drop_ptrs(tsv, lo, hi):
    lines = [l for l in tsv.read_text(encoding="utf-8").split(NL)
             if not l or l.startswith("#") or not lo <= int(l.split(TAB)[0], 16) - 0x08000000 < hi]
    tsv.write_text(NL.join(lines), encoding="utf-8")


def install(tree, region, text):
    """Grava o asm gerado e, na 1a vez, tira a regiao dos blocos de dados (.s), do .tsv de ponteiros e poe o objeto no
    ld_script (entre os pedacos do bloco, na ordem dos enderecos)."""
    fname, start, end, _ = REGIONS[region]
    (tree / fname).write_text(text, encoding="utf-8")
    ld = tree / "ld_script.ld"
    obj = "build/" + fname.replace(".s", ".o") + "(.rodata);"
    t = ld.read_text(encoding="utf-8")
    if obj in t:
        if region == "area":       # instalada antes, com a regiao comecando em gAreaBgPalettes: tira o resto do bloco
            ds = tree / "data/data_083AB9D0.s"
            lines = ds.read_text(encoding="utf-8").split(NL)
            if f"{TAB}.global gAreaMapSizes" in lines:
                ds.write_text(NL.join(lines[:lines.index(f"{TAB}.global gAreaMapSizes")]) + NL, encoding="utf-8")
                _drop_ptrs(tree / "config/data_ptrs/data_data_083AB9D0.tsv", start, 0x10000000)
        return
    if region == "area":
        ds = tree / "data/data_083AB9D0.s"
        lines = ds.read_text(encoding="utf-8").split(NL)
        i0 = lines.index(f"{TAB}.global gAreaMapSizes")
        i1 = lines.index(f"{TAB}.global gSpriteSheetVariantTables")
        ds.write_text(NL.join(lines[:i0]) + NL, encoding="utf-8")
        (tree / "data/data_08414394.s").write_text(NL.join([f"{TAB}.section .rodata", ""] + lines[i1:]),
                                                     encoding="utf-8")
        tsv = tree / "config/data_ptrs/data_data_083AB9D0.tsv"
        rest = [l for l in tsv.read_text(encoding="utf-8").split(NL)
                if l and not l.startswith("#") and int(l.split(TAB)[0], 16) - 0x08000000 >= end]
        _drop_ptrs(tsv, start, 0x10000000)
        (tree / "config/data_ptrs/data_data_08414394.tsv").write_text(
            NL.join(["# ROM address of a pointer word in the stub, and the symbol it points to"] + rest) + NL,
            encoding="utf-8")
        a = "build/data/data_083AB9D0.o(.rodata);"
        t = t.replace(a, a + f"{NL}        {obj}{NL}        build/data/data_08414394.o(.rodata);", 1)
    else:   # npc: fim de gFieldEffectObjTiles (data_08414394.s) e comeco de data_08480000.s
        ds = tree / "data/data_08414394.s"
        s = ds.read_text(encoding="utf-8")
        old = '.incbin "baserom.gba", 0x47ECC0, 0x1340'
        assert old in s, "gFieldEffectObjTiles nao esta como esperado"
        ds.write_text(s.replace(old, f'.incbin "baserom.gba", 0x47ECC0, 0x{start - 0x47ECC0:X}'), encoding="utf-8")
        d2 = tree / "data/data_08480000.s"
        lines = d2.read_text(encoding="utf-8").split(NL)
        i1 = lines.index(f"{TAB}.global gMenuDigitPalette")
        d2.write_text(NL.join([f"{TAB}.section .rodata", ""] + lines[i1:]), encoding="utf-8")
        _drop_ptrs(tree / "config/data_ptrs/data_data_08414394.tsv", start, end)
        _drop_ptrs(tree / "config/data_ptrs/data_data_08480000.tsv", start, end)
        a = "build/data/data_08480000.o(.rodata);"
        t = t.replace(a, f"{obj}{NL}        {a}", 1)
    ld.write_text(t, encoding="utf-8")



# Tabelas de um valor por area (enderecos USA fixos, tamanho do bloco do jogo): viram linhas .byte dentro do bloco de
# dados (tools/scripts/label_data.py da decomp aceita .byte/.2byte); o resto do bloco continua .incbin.
# Com areas novas (mais de 192) a tabela nao cabe no bloco: ela inteira vai para asm/maps_area_tables.s com o rotulo do
# jogo (o codigo le dali) e o lugar antigo fica com as 192 do jogo sob sOrig_<rotulo>, porque ponteiros do jogo para
# dados depois da tabela usam esse rotulo + deslocamento (ex.: gAreaRandomEncounters+0x300.. = os grupos de luta).
TABLES_ASM = "asm/maps_area_tables.s"
INLINE = [("gAreaBattleSettings", 0x3BEA90, 0x600, "battle_settings"),
          ("gAreaRandomEncounters", 0x3BF090, 0x2970, "encounter_groups"), ("gAreaTypes", 0x3D29EB, 0xC0, "type"),
          ("gAreaSongs", 0x47EB80, 0xC0, "song"), ("gAreaTownMapPlace", 0x483CE0, 0xC0, "town_map_place")]


def install_inline(tree, maps):
    from maps_inventory import NAREAS
    areas = load_areas(maps)
    stubs = list((tree / "data").glob("*.s"))
    moved = []
    for label, at, size, key in INLINE:
        vals = []
        for a in areas[:NAREAS]:
            v = a[key]
            vals += v if isinstance(v, list) else [v]
        table = bytes(vals)
        extra = []
        for a in areas[NAREAS:]:
            v = a[key]
            extra += v if isinstance(v, list) else [v]
        here = f"sOrig_{label}" if extra else label
        f = next(x for x in stubs if any(f"{NL}{n}:{NL}" in x.read_text(encoding="utf-8")
                                         for n in (label, f"sOrig_{label}")))
        lines = f.read_text(encoding="utf-8").split(NL)
        name = label if f"{label}:" in lines else f"sOrig_{label}"
        if name != here:              # troca o rotulo no bloco e nos ponteiros rotulo+deslocamento
            lines[lines.index(f"{name}:")] = f"{here}:"
            lines[lines.index(f"{TAB}.global {name}")] = f"{TAB}.global {here}"
            for tsv in (tree / "config/data_ptrs").glob("*.tsv"):
                t = tsv.read_text(encoding="utf-8")
                if f"{TAB}{name}+" in t:
                    tsv.write_text(t.replace(f"{TAB}{name}+", f"{TAB}{here}+"), encoding="utf-8")
        if extra:
            moved.append(f"{TAB}.align 2{NL}{TAB}.global {label}{NL}{label}:{NL}" + byte_lines(table + bytes(extra)))
        i = lines.index(f"{here}:") + 1
        j = i
        while j < len(lines) and lines[j].lstrip().startswith((".byte", ".2byte")):   # geradas antes
            j += 1
        if j < len(lines) and lines[j].lstrip().startswith(".incbin") and (j == i or f"0x{at + len(table):X}," in lines[j]):
            j += 1   # o .incbin original (1a vez) ou o resto do bloco
        new = byte_lines(table).rstrip(NL).split(NL)
        if size > len(table):
            new.append(f'{TAB}.incbin "baserom.gba", 0x{at + len(table):X}, 0x{size - len(table):X}')
        lines[i:j] = new
        f.write_text(NL.join(lines), encoding="utf-8")
    # tabelas das areas novas (vazio sem area nova; o objeto entra no ld_script uma vez)
    (tree / TABLES_ASM).write_text(f"{TAB}.section .rodata{NL}{NL}@ gerado por tools/maps_build.py (areas novas){NL}"
                                   + "".join(moved) + (f"{TAB}.align 2{NL}" if moved else ""), encoding="utf-8")
    ld = tree / "ld_script.ld"
    obj = "build/" + TABLES_ASM.replace(".s", ".o") + "(.rodata);"
    t = ld.read_text(encoding="utf-8")
    if obj not in t:
        a = "build/" + REGIONS["npc"][0].replace(".s", ".o") + "(.rodata);"
        ld.write_text(t.replace(a, f"{a}{NL}        {obj}", 1), encoding="utf-8")


# Graficos de area (tiles, tiles animados, tilemaps: LZ77; paletas): blobs dentro do bloco gVehicleIconBlankTiles de
# graphics/graphics_08590000.s. Cada blob vira `.incbin "graphics/maps/<nome>"` (copia de data/maps/gfx) com rotulo
# sAreaGfx_<nome>; os trechos de outros graficos entre eles ganham rotulo sAreaGfxGap_<endereco> e os ponteiros do jogo
# para o bloco (config/data_ptrs) passam a ser rotulo+deslocamento do pedaco: tudo se move junto se um blob mudar.
GFX_BLOCK = ("gVehicleIconBlankTiles", 0x5FAA98, 0x16A218)


def gfx_pieces(maps):
    lay = json.loads((maps / "_layout.json").read_text(encoding="utf-8"))
    _, b0, bn = GFX_BLOCK
    blobs = sorted((int(g["at"], 16), g["len"], name) for name, g in lay["gfx"].items())
    pieces, cur = [], b0
    for at, ln, name in blobs:
        assert at >= cur, f"graficos sobrepostos em 0x{at:X}"
        if at > cur:
            pieces.append((cur, at - cur, None))
        pieces.append((at, ln, name))
        cur = at + ln
    if cur < b0 + bn:
        pieces.append((cur, b0 + bn - cur, None))
    return pieces


def gfx_symbol(pieces, off):
    """Rotulo+deslocamento do pedaco que contem `off`."""
    for at, ln, name in pieces:
        if at <= off < at + ln:
            lab = f"sAreaGfx_{name}" if name else f"sAreaGfxGap_{at:06X}"
            return lab if off == at else f"{lab}+0x{off - at:X}"
    raise SystemExit(f"0x{off:X} fora do bloco de graficos")


def install_gfx(tree, maps):
    lbl, b0, bn = GFX_BLOCK
    pieces = gfx_pieces(maps)
    gdir = tree / "graphics/maps"
    gdir.mkdir(exist_ok=True)
    for f in (maps / "gfx").iterdir():
        (gdir / f.name).write_bytes(f.read_bytes())
    ext = {n: ("pal" if n.startswith("palette") else "lz") for _, _, n in pieces if n}
    lines_new = []
    for at, ln, name in pieces:
        if name:
            lines_new += [f"{TAB}.global sAreaGfx_{name}", f"sAreaGfx_{name}:",
                          f'{TAB}.incbin "graphics/maps/{name}.{ext[name]}"   @ 0x{at:X}, 0x{ln:X}']
        else:
            if at != b0:
                lines_new += [f"{TAB}.global sAreaGfxGap_{at:06X}", f"sAreaGfxGap_{at:06X}:"]
            lines_new.append(f'{TAB}.incbin "baserom.gba", 0x{at:X}, 0x{ln:X}')
    st = tree / "graphics/graphics_08590000.s"
    lines = st.read_text(encoding="utf-8").split(NL)
    i = lines.index(f"{lbl}:") + 1
    j = i
    while j < len(lines) and (lines[j].lstrip().startswith(".incbin") and (j == i or "graphics/maps/" in lines[j]
                              or lines[j - 1].startswith(("sAreaGfx_", "sAreaGfxGap_")))
                              or lines[j].startswith(("sAreaGfx_", "sAreaGfxGap_"))
                              or lines[j].strip() in {f".global {x}" for x in []}
                              or lines[j].lstrip().startswith(".global sAreaGfx")):
        j += 1
    lines[i:j] = lines_new
    st.write_text(NL.join(lines), encoding="utf-8")
    # ponteiros do jogo para o bloco: rotulo do pedaco
    for tsv in (tree / "config/data_ptrs").glob("*.tsv"):
        t = tsv.read_text(encoding="utf-8").split(NL)
        changed = False
        for k, l in enumerate(t):
            if not l or l.startswith("#"):
                continue
            ad, sym = l.split(TAB)[:2]
            if sym.split("+")[0].strip() == lbl:
                off = b0 + (int(sym.split("+")[1], 16) if "+" in sym else 0)
                t[k] = f"{ad}{TAB}{gfx_symbol(pieces, off)}"
                changed = True
        if changed:
            tsv.write_text(NL.join(t), encoding="utf-8")


def install_all(tree, maps):
    for region in REGIONS:
        install(tree, region, emit_region(maps, region))
    install_inline(tree, maps)
    install_gfx(tree, maps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", default=str(ROOT / "data/maps"))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--asm", help="arvore da decomp onde gerar os asm (asm/maps_*.s)")
    a = ap.parse_args()
    if a.verify:
        raise SystemExit(0 if verify(Path(a.maps)) else 1)
    if a.asm:
        install_all(Path(a.asm), Path(a.maps))
        print(f"{a.asm}: " + ", ".join(REGIONS[r][0] for r in REGIONS))
        return
    ap.print_help()


if __name__ == "__main__":
    main()
