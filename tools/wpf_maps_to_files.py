"""wpf_maps_to_files.py - Edicoes de mapa do WPF (Modo Decomp) viram arquivos de data/maps (M5 do
pc/research/MAPAS_EVENTOS_PLANO.md).

O editor de mapa do WPF grava colisao, NPCs, warps e tiles pintados no projeto (data/wpf/project.medahack.json, fase 4) como a lista
inteira da area. Aqui eles vao para data/maps/area_NNN (collision.txt, npcs.json, warps.json), a fonte que a build le,
e saem do projeto. Se a area usava dado de outra (compartilhado), passa a ter o seu. Roda no comeco de cada build
(tools/decomp_build.py); pode rodar a mao.

Uso: python tools/wpf_maps_to_files.py [--project data/wpf/project.medahack.json] [--maps data/maps] [--dry-run]
"""
import argparse
import base64
import json
import shutil
import struct
from pathlib import Path

from codecs_gba import lz77_store

ROOT = Path(__file__).resolve().parents[1]
COL_CHARS = None


def own(maps, a, kind, files):
    """A area passa a ter o proprio dado `kind` (copia do dono atual, se for outra area)."""
    me = f"area_{a['id']:03d}"
    if a[kind] != me:
        for f in files:
            src = maps / a[kind] / f
            if src.exists():
                shutil.copy2(src, maps / me / f)
        a[kind] = me


def add_area(maps, p):
    """Uma MapAddition do WPF (MapExpander.AddMap/AddBlankMap do Toolkit) como pasta nova de data/maps."""
    from maps_new import new_area
    from codecs_gba import lz77_decompress
    keep = p.get("copyWarpsAndPeople", False) and not p.get("blank")
    nid = new_area(maps, p["sourceMapId"], npcs=keep)
    d = maps / f"area_{nid:03d}"
    a = json.loads((d / "area.json").read_text(encoding="utf-8"))
    if not keep:
        j = json.loads((d / "warps.json").read_text(encoding="utf-8"))
        j["warps"] = []
        (d / "warps.json").write_text(json.dumps(j, indent=1) + "\n", encoding="utf-8")
    if p.get("blank"):
        w, h = p["width"], p["height"]
        if not (2 <= w <= 64 and 2 <= h <= 64 and w % 2 == 0 and h % 2 == 0):
            raise SystemExit(f"area vazia {w}x{h}: 2 a 64 tiles, numeros pares")
        a["size_8px"] = [w, h]
        cw, ch = w // 2, h // 2      # colisao: parede (1) na borda, chao (0) dentro (conferido no jogo; o Toolkit inverte)
        rows = ["".join(COL_CHARS[1 if x in (0, cw - 1) or y in (0, ch - 1) else 0] for x in range(cw)) for y in range(ch)]
        (d / "collision.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
        (d / "collision.tail").write_text("", encoding="utf-8")
        j = json.loads((d / "exits.json").read_text(encoding="utf-8"))
        j["exits"] = []
        (d / "exits.json").write_text(json.dumps(j, indent=1) + "\n", encoding="utf-8")
        if p.get("blankTileset"):
            tiles = 896
            (maps / "gfx" / f"tiles_a{nid:03d}_blank.lz").write_bytes(lz77_store(bytes(tiles * 32)))
            (maps / "gfx" / f"palette_a{nid:03d}_blank.pal").write_bytes(bytes(0x200))
            a["tiles"], a["palette"] = f"tiles_a{nid:03d}_blank", f"palette_a{nid:03d}_blank"
        else:
            tiles = len(lz77_decompress((maps / "gfx" / f"{a['tiles']}.lz").read_bytes(), 0)[0]) // 32
        layer = bytearray(16 + w * h * 2)
        struct.pack_into("<H", layer, 0, w)
        struct.pack_into("<H", layer, 4, h)
        struct.pack_into("<H", layer, 8, tiles)
        name = f"tilemaps_a{nid:03d}_blank"
        (maps / "gfx" / f"{name}.lz").write_bytes(lz77_store(bytes(layer)))
        a["tilemaps"], a["tilemaps_unused"] = name, [name, name]
    (d / "area.json").write_text(json.dumps(a, indent=1) + "\n", encoding="utf-8")
    return nid


def convert(project, maps, dry=False):
    global COL_CHARS
    from maps_lift import COL_CHARS as cc
    COL_CHARS = cc
    if not project.exists():
        return []
    doc = json.loads(project.read_text(encoding="utf-8-sig"))
    done = []
    areas, orig = {}, {}

    def area(mid):
        if mid not in areas:
            areas[mid] = json.loads((maps / f"area_{mid:03d}/area.json").read_text(encoding="utf-8"))
            orig[mid] = json.dumps(areas[mid])
        return areas[mid]

    # areas novas do WPF (Map > New map), antes das outras edicoes (que podem editar a area nova): proximo id livre
    for p in doc.get("mapAdditions", []):
        if dry:
            done.append(f"area nova (copia da {p['sourceMapId']})")
            continue
        nid = add_area(maps, p)
        done.append(f"area nova {nid}: " + (f"vazia {p['width']}x{p['height']}" if p.get("blank") else
                                           f"copia da {p['sourceMapId']}"))
    for p in doc.get("mapCollisionPatches", []):
        mid, a = p["mapId"], area(p["mapId"])
        data = base64.b64decode(p["colorAttributeBytesBase64"])
        w, h = a["size_8px"][0] // 2, a["size_8px"][1] // 2
        if len(data) < w * h:
            raise SystemExit(f"area {mid}: colisao com {len(data)} B, a grade tem {w}x{h}")
        if not dry:
            own(maps, a, "collision", ["collision.txt", "collision.tail"])
            d = maps / a["collision"]
            rows = ["".join(COL_CHARS[v] for v in data[y * w:(y + 1) * w]) for y in range(h)]
            (d / "collision.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
            if len(data) > w * h:
                (d / "collision.tail").write_text(data[w * h:].hex() + "\n", encoding="utf-8")
        done.append(f"area {mid}: colisao")
    for p in doc.get("mapEntitySpawnPatches", []):
        mid, a = p["mapId"], area(p["mapId"])
        npcs = [{"x": r["tileX"], "y": r["tileY"], "kind": r["recordKindAndEventId"] >> 12,
                 "event": r["recordKindAndEventId"] & 0xFFF, "anim": r["spriteAndFacingPacked"],
                 "load_order": r["spawnGroupIndex"],
                 "phases": [b for b in range(16) if r["chapterVisibilityMask"] >> b & 1]} for r in p["records"]]
        if not dry:
            own(maps, a, "npcs", ["npcs.json"])
            f = maps / a["npcs"] / "npcs.json"
            j = json.loads(f.read_text(encoding="utf-8"))
            j["npcs"] = npcs
            f.write_text(json.dumps(j, indent=1) + "\n", encoding="utf-8")
        done.append(f"area {mid}: {len(npcs)} NPCs")
    for p in doc.get("mapWarpPatches", []):
        mid, a = p["mapId"], area(p["mapId"])
        warps = [{"x": r["tileX"], "y": r["tileY"], "to_area": r["destinationMapId"],
                  "dir": r["arrivalFacingAndTransitionKind"], "unused": [r["unknown4"], r["unknown5"]],
                  "to_x": r["destinationTileX"], "to_y": r["destinationTileY"]} for r in p["records"]]
        if not dry:
            own(maps, a, "warps", ["warps.json"])
            f = maps / a["warps"] / "warps.json"
            j = json.loads(f.read_text(encoding="utf-8"))
            j["warps"] = warps
            f.write_text(json.dumps(j, indent=1) + "\n", encoding="utf-8")
        done.append(f"area {mid}: {len(warps)} warps")
    # tiles pintados: a camada inteira (cabecalho + entradas) vira um tilemap LZ77 novo em data/maps/gfx; a area aponta
    # para ele (camada 0 = "tilemaps", 1 e 2 = "tilemaps_unused"[0/1], as 3 entradas da area em gAreaBgTilemaps)
    for p in doc.get("mapLayerPatches", []):
        mid, k, a = p["mapId"], p["layerIndex"], area(p["mapId"])
        raw = struct.pack("<6H", p["headerWidthInTiles"], p["headerOriginX"], p["headerHeightInTiles"],
                          p["headerOriginY"], p["headerOriginX2"], p["headerOriginY2"])
        raw += struct.pack(f"<{len(p['tileEntries'])}H", *p["tileEntries"])
        name = f"tilemaps_a{mid:03d}_l{k}"
        if not dry:
            (maps / "gfx" / f"{name}.lz").write_bytes(lz77_store(raw))
            if k == 0:
                a["tilemaps"] = name
            else:
                a["tilemaps_unused"][k - 1] = name
        done.append(f"area {mid}: camada {k} de tiles")
    if done and not dry:
        for mid, a in areas.items():
            if json.dumps(a) != orig[mid]:          # so quando a area passou a ter dado proprio
                (maps / f"area_{mid:03d}/area.json").write_text(json.dumps(a, indent=1) + "\n", encoding="utf-8")
        for k in ("mapAdditions", "mapCollisionPatches", "mapEntitySpawnPatches", "mapWarpPatches", "mapLayerPatches"):
            doc[k] = []
        project.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(ROOT / "data/wpf/project.medahack.json"))
    ap.add_argument("--maps", default=str(ROOT / "data/maps"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    done = convert(Path(a.project), Path(a.maps), a.dry_run)
    print(f"{len(done)} edicoes de mapa do WPF {'a mover' if a.dry_run else 'movidas'} para data/maps"
          + "".join(f"\n  {d}" for d in done))


if __name__ == "__main__":
    main()
