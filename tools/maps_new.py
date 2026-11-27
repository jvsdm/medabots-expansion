"""maps_new.py - Cria uma area nova em data/maps copiando outra (M4 do pc/research/MAPAS_EVENTOS_PLANO.md).

A area nova pega o proximo id livre (192, 193...; area_id e u8, entao ate 255) e copia da origem o tamanho, os graficos
(por nome, compartilhados), a musica, os encontros e os dados (colisao, warps, saidas, NPCs, sprites, animacao). Os
dados viram dela (dono = ela mesma): editar a area nova nao mexe na de origem. O gerador (tools/maps_build.py) poe as
areas novas no fim de cada tabela e de cada regiao.

Uso: python tools/maps_new.py --from 30 [--name "Loja nova"] [--no-npcs] [--maps data/maps]
Saida: o id da area nova.
"""
import argparse
import json
import shutil
from pathlib import Path

from maps_build import n_areas

ROOT = Path(__file__).resolve().parents[1]
KINDS = ["collision", "tileanim", "exits", "warps", "sprites", "npcs"]
FILES = {"collision": ["collision.txt", "collision.tail"], "tileanim": ["tileanim.json"], "exits": ["exits.json"],
         "warps": ["warps.json"], "sprites": ["sprites.json"], "npcs": ["npcs.json"]}


def new_area(maps, src, name=None, npcs=True):
    nid = n_areas(maps)
    if nid > 255:
        raise SystemExit("area_id e u8: ja sao 256 areas")
    sdir = maps / f"area_{src:03d}"
    a = json.loads((sdir / "area.json").read_text(encoding="utf-8"))
    ddir = maps / f"area_{nid:03d}"
    ddir.mkdir()
    for kind in KINDS:
        owner = maps / a[kind]                 # dado pode ser de outra area (compartilhado)
        for f in FILES[kind]:
            shutil.copy2(owner / f, ddir / f)
        a[kind] = f"area_{nid:03d}"
    if not npcs:
        j = json.loads((ddir / "npcs.json").read_text(encoding="utf-8"))
        j["npcs"] = []
        (ddir / "npcs.json").write_text(json.dumps(j, indent=1) + "\n", encoding="utf-8")
    a["id"] = nid
    a["copied_from"] = src
    if name:
        a["name"] = name
    (ddir / "area.json").write_text(json.dumps(a, indent=1) + "\n", encoding="utf-8")
    return nid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", type=int, required=True)
    ap.add_argument("--name")
    ap.add_argument("--no-npcs", action="store_true")
    ap.add_argument("--maps", default=str(ROOT / "data/maps"))
    a = ap.parse_args()
    nid = new_area(Path(a.maps), a.src, a.name, not a.no_npcs)
    print(f"area nova: {nid} (area_{nid:03d}, copia da {a.src})")


if __name__ == "__main__":
    main()
