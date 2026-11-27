"""maps_lift.py - Extrai as areas do jogo para arquivos (M0 do pc/research/MAPAS_EVENTOS_PLANO.md).

Le build/scratch/decomp_rok/baserom.gba (USA) e escreve data/maps/:
  area_NNN/area.json      tamanho, musica, tipo, lugar no mapa da cidade, ajustes de luta, grupos de encontro e as
                          referencias dos dados (graficos e blobs compartilhados por nome)
  area_NNN/collision.txt  colisao (um caractere por tile de 16 px: '.' = 0 chao, '#' = 1 parede, 2-9/a-z = acoes)
  area_NNN/warps.json, exits.json, npcs.json, sprites.json, tileanim.json
  gfx/<rotulo>.lz         graficos da area (tiles, tiles animados, tilemaps: LZ77 como no jogo) e paletas (.pal)
  _layout.json            ordem e posicao de cada segmento nos blocos do jogo (o gerador M1 reconstroi a ROM igual)

Ida e volta exata: cada dado apontado vira um segmento do endereco dele ate o proximo (ou ate a tabela); o que vem
depois do terminador fica em "tail" (hex). Areas que apontam o mesmo dado: o dono e a 1a area; as outras citam o dono.

Uso: python tools/maps_lift.py [--out data/maps] [--check]
  --check: so confere que os segmentos cobrem 100% dos blocos (nada sobra, nada sobrepoe) e nao grava.
"""
import argparse
import json
import shutil
import struct
from pathlib import Path

from codecs_gba import compressed_size
from maps_inventory import DEC, GBA, NAREAS, asm_blocks

ROOT = Path(__file__).resolve().parents[1]
# tabelas de ponteiros por area cujos dados ficam no mesmo bloco, antes da tabela seguinte (formato de cada registro)
DATA_TABLES = {
    "gAreaCollisionMaps": "collision",
    "gAreaTileAnims": "tileanim",
    "gAreaExits": "exits",
    "gAreaWarps": "warps",
    "gAreaSpriteSheetIds": "sprites",
    "gAreaNpcRecords": "npcs",
}
GFX_TABLES = {"gAreaBgTiles": ("tiles", 4), "gAreaAnimBgTiles": ("animtiles", 4), "gAreaBgTilemaps": ("tilemaps", 12),
              "gAreaBgPalettes": ("palette", 4)}
PALETTE_BYTES = 0xD0 * 2        # gAreaBgPalettes: 0xD0 cores
COL_CHARS = ".#23456789abcdefghijklmnopqrstuvwxyz"


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def records(seg, size, end_at_ff=True):
    """Registros de `size` bytes ate o primeiro com 1o byte 0xFF (terminador). Devolve (registros, tail hex)."""
    out, i = [], 0
    while i + size <= len(seg) and not (end_at_ff and seg[i] == 0xFF):
        out.append(seg[i:i + size])
        i += size
    return out, seg[i:].hex()


def lift(out_dir, check):
    rom = (DEC / "baserom.gba").read_bytes()
    blocks = asm_blocks()
    labels = {lab: (s, e) for s, e, lab, _ in blocks if lab}
    sizes = [tuple(rom[labels["gAreaMapSizes"][0] + 2 * i:labels["gAreaMapSizes"][0] + 2 * i + 2]) for i in range(NAREAS)]
    layout = {"segments": {}, "gfx": {}}
    areas = [{"id": i, "size_8px": list(sizes[i])} for i in range(NAREAS)]
    files = {}   # caminho relativo -> conteudo (str ou bytes)

    # --- dados no mesmo bloco das tabelas: segmentos ---
    covered = []
    for table, kind in DATA_TABLES.items():
        t0 = labels[table][0]
        ptrs = [u32(rom, t0 + 4 * i) - GBA for i in range(NAREAS)]
        targets = sorted(set(ptrs))
        segs = []
        for k, p in enumerate(targets):
            end = targets[k + 1] if k + 1 < len(targets) else t0
            segs.append((p, end))
        covered += segs
        owner = {}
        for i, p in enumerate(ptrs):
            owner.setdefault(p, i)
        layout["segments"][table] = [{"at": hex(s), "len": e - s, "owner": owner[s]} for s, e in segs]
        for s, e in segs:
            seg = rom[s:e]
            i = owner[s]
            base = f"area_{i:03d}"
            if kind == "collision":
                w, h = sizes[i][0] // 2, sizes[i][1] // 2
                grid = seg[:w * h]
                rows = ["".join(COL_CHARS[v] if v < len(COL_CHARS) else "?" for v in grid[y * w:(y + 1) * w])
                        for y in range(h)]
                assert all("?" not in r for r in rows), f"colisao com valor fora da tabela na area {i}"
                files[f"{base}/collision.txt"] = "\n".join(rows) + "\n"
                files[f"{base}/collision.tail"] = seg[w * h:].hex()
            elif kind == "warps":
                recs, tail = records(seg, 8)
                files[f"{base}/warps.json"] = {"warps": [{"x": r[0], "y": r[1], "to_area": r[2], "dir": r[3],
                                                          "unused": [r[4], r[5]], "to_x": r[6], "to_y": r[7]}
                                                         for r in recs], "tail": tail}
            elif kind == "exits":
                recs, tail = records(seg, 4)
                files[f"{base}/exits.json"] = {"exits": [{"x": r[0], "y": r[1], "mask": r[2], "value": r[3]}
                                                         for r in recs], "tail": tail}
            elif kind == "npcs":
                recs, tail = records(seg, 8)
                files[f"{base}/npcs.json"] = {"npcs": [{"x": r[0], "y": r[1],
                                                        "kind": struct.unpack_from("<H", r, 2)[0] >> 12,
                                                        "event": struct.unpack_from("<H", r, 2)[0] & 0xFFF,
                                                        "anim": r[4], "load_order": r[5],
                                                        "phases": [b for b in range(16)
                                                                   if struct.unpack_from("<H", r, 6)[0] >> b & 1]}
                                                       for r in recs], "tail": tail}
            else:   # sprites, tileanim: bytes por enquanto (formato a decifrar no M1)
                files[f"{base}/{kind}.json"] = {"hex": seg.hex()}
        for i, p in enumerate(ptrs):
            areas[i][kind] = f"area_{owner[p]:03d}"

    # --- graficos: blobs no bloco grande de graphics/ ---
    for table, (kind, stride) in GFX_TABLES.items():
        t0 = labels[table][0]
        ptrs = [u32(rom, t0 + stride * i) for i in range(NAREAS)]
        for i, p in enumerate(ptrs):
            if not p:
                areas[i][kind] = None
                continue
            off = p - GBA
            name = f"{kind}_{off:06X}"
            if name not in layout["gfx"]:
                n = PALETTE_BYTES if kind == "palette" else compressed_size(rom, off)
                layout["gfx"][name] = {"at": hex(off), "len": n}
                files[f"gfx/{name}.{'pal' if kind == 'palette' else 'lz'}"] = rom[off:off + n]
            areas[i][kind] = name
        if stride == 12:   # AreaGfx: +4 e +8 nunca lidos no C; guardados para a ida e volta
            for i in range(NAREAS):
                areas[i]["tilemaps_unused"] = [hex(u32(rom, t0 + 12 * i + 4)), hex(u32(rom, t0 + 12 * i + 8))]

    # --- tabelas inline (um valor por area) ---
    inline = {"gAreaSongs": ("song", 1), "gAreaBattleSettings": ("battle_settings", 8), "gAreaTypes": ("type", 1),
              "gAreaTownMapPlace": ("town_map_place", 1)}
    for table, (key, n) in inline.items():
        t0 = labels[table][0]
        for i in range(NAREAS):
            v = rom[t0 + n * i:t0 + n * (i + 1)]
            areas[i][key] = v[0] if n == 1 else list(v)
    enc = labels["gAreaRandomEncounters"][0]
    for i in range(NAREAS):
        areas[i]["encounter_groups"] = list(rom[enc + 4 * i:enc + 4 * i + 4])

    # --- conferencia: os segmentos de dados cobrem os blocos sem buraco nem sobreposicao ---
    covered.sort()
    for (s1, e1), (s2, e2) in zip(covered, covered[1:]):
        assert e1 <= s2, f"segmentos sobrepostos em 0x{s2:X}"
    gaps = [(e1, s2) for (s1, e1), (s2, e2) in zip(covered, covered[1:]) if s2 > e1]
    tables = sorted(labels[t][0] for t in DATA_TABLES)
    real_gaps = [g for g in gaps if not any(g[0] <= t < g[1] for t in tables) and g[1] - g[0] > 0]
    # buraco legitimo: a propria tabela de ponteiros (4 x 192) e o que vem entre ela e o 1o dado da tabela seguinte
    print(f"areas {NAREAS}; segmentos {len(covered)}; buracos entre segmentos (fora tabelas): "
          f"{[(hex(a), b - a) for a, b in real_gaps][:8]}")
    print(f"graficos: {len(layout['gfx'])} blobs ({sum(v['len'] for v in layout['gfx'].values())} B)")
    if check:
        return
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for rel, content in files.items():
        f = out_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            f.write_bytes(content)
        elif isinstance(content, str):
            f.write_text(content, encoding="utf-8")
        else:
            f.write_text(json.dumps(content, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for a in areas:
        f = out_dir / f"area_{a['id']:03d}" / "area.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(a, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out_dir / "_layout.json").write_text(json.dumps(layout, indent=1) + "\n", encoding="utf-8")
    print(f"gravado em {out_dir}: {len(list(out_dir.rglob('*')))} arquivos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/maps"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    lift(Path(a.out), a.check)


if __name__ == "__main__":
    main()
