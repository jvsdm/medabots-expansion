"""maps_inventory.py - Inventario das tabelas por area da decomp (M0 do pc/research/MAPAS_EVENTOS_PLANO.md).

Le os .s de build/scratch/decomp_rok (rotulos + .incbin do baserom) e o baserom.gba (USA) e, para cada tabela de
ponteiros por area, mostra: entradas, ponteiros nulos, alvos distintos, compartilhamento, e em que bloco (rotulo do
.s) caem os dados apontados. Base para o extrator (tools/maps_lift.py) e o gerador (M1).

Uso: python tools/maps_inventory.py [--json saida.json]
"""
import argparse
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# arvore do decomp: MEDABOTS_DECOMP aponta para outra (ex.: a main original, para extrair os dados do jogo na instalacao)
import os
import sys as _sys
_sys.path.insert(0, str(ROOT / "tools"))
import paths as _paths  # noqa: E402
DEC = Path(os.environ.get("MEDABOTS_DECOMP") or _paths.DECOMP)
GBA = 0x08000000
NAREAS = 192
# tabela -> bytes por entrada (ponteiros: 4; AreaGfx: 12 com o ponteiro no +0)
POINTER_TABLES = {"gAreaBgTiles": 4, "gAreaAnimBgTiles": 4, "gAreaBgTilemaps": 12, "gAreaBgPalettes": 4,
                  "gAreaCollisionMaps": 4, "gAreaTileAnims": 4, "gAreaExits": 4, "gAreaWarps": 4,
                  "gAreaSpriteSheetIds": 4, "gAreaNpcRecords": 4}
INLINE_TABLES = {"gAreaMapSizes": 2, "gAreaSongs": 1, "gAreaBattleSettings": 8, "gAreaTypes": 1,
                 "gAreaTownMapPlace": 1}


def asm_blocks():
    """[(inicio, fim, rotulo, arquivo)] dos .incbin "baserom.gba" dos .s (rotulo = o .global logo antes)."""
    out = []
    for f in sorted(p for d in ("data", "asm", "graphics", "sound") for p in (DEC / d).rglob("*.s")
                    if not p.name.startswith("maps_")):     # gerados por tools/maps_build.py (regioes pelos enderecos fixos)
        label = None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*([A-Za-z_]\w*):", line)
            if m:
                label = m.group(1)
            m = re.search(r'\.incbin\s+"baserom\.gba",\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+)', line)
            if m:
                a, n = int(m.group(1), 16), int(m.group(2), 16)
                out.append((a, a + n, label, f.name))
    # regiao A ja trocada pelo asm gerado (tools/maps_build.py): os blocos do jogo base pelos enderecos fixos
    from maps_build import REGIONS
    have = {lab for _, _, lab, _ in out}
    for fname, _, rend, labs in REGIONS.values():
        for k, (lab, at) in enumerate(labs):
            if lab not in have:
                end = labs[k + 1][1] if k + 1 < len(labs) else rend
                out.append((at, end, lab, Path(fname).name))
    return sorted(out)


def where(blocks, off):
    for a, e, lab, f in blocks:
        if a <= off < e:
            return lab, f, a
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    rom = (DEC / "baserom.gba").read_bytes()
    blocks = asm_blocks()
    labels = {lab: (s, e) for s, e, lab, _ in blocks if lab}
    report = {}
    for name, stride in POINTER_TABLES.items():
        start = labels[name][0]
        ptrs = [struct.unpack_from("<I", rom, start + stride * i)[0] for i in range(NAREAS)]
        nonnull = [p - GBA for p in ptrs if p]
        dist = sorted(set(nonnull))
        homes = {}
        for p in dist:
            lab, f, _ = where(blocks, p)
            homes.setdefault(f"{lab} ({f})", 0)
            homes[f"{lab} ({f})"] += 1
        report[name] = {"table_at": hex(start), "entries": NAREAS, "null": NAREAS - len(nonnull),
                        "distinct_targets": len(dist), "shared": len(nonnull) - len(dist),
                        "target_range": [hex(dist[0]), hex(dist[-1])] if dist else None, "homes": homes}
    for name, stride in INLINE_TABLES.items():
        s, e = labels[name]
        report[name] = {"table_at": hex(s), "bytes": e - s, "per_area": stride, "areas_fit": (e - s) // stride}
    for k, v in report.items():
        print(k, json.dumps(v, ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
