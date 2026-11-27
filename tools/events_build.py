"""events_build.py - Monta gMapScripts a partir de data/events (M2 do pc/research/MAPAS_EVENTOS_PLANO.md).

Cada roteiro fica no lugar original enquanto couber no espaco dele (bytes ate o proximo roteiro do banco); se crescer,
vai para um banco novo no fim do bloco (8, 9...; o banco e u8). As duas tabelas do cabecalho (inicio e banco de cada
roteiro) sao refeitas. Roteiro com "shared_with" aponta para o mesmo lugar do outro.

--verify: monta e compara com o bloco do jogo (ida e volta).
--asm ARVORE: grava ARVORE/graphics/maps/map_scripts.bin e troca o .incbin de gMapScripts no
              graphics/graphics_08590000.s por esse arquivo (uma vez).

Uso: python tools/events_build.py --verify | --asm build/scratch/decomp_rok [--events data/events]
"""
import argparse
import json
from pathlib import Path

from events_lift import BANK, BLOB_AT, BLOB_LEN, DEC, header
from events_text import load_ops, script_bytes

ROOT = Path(__file__).resolve().parents[1]
NL, TAB = chr(10), chr(9)


def build_blob(events):
    meta = json.loads((events / "_blob.json").read_text(encoding="utf-8"))
    n = meta["count"]
    while (events / f"{n:04d}.json").exists():      # roteiros novos (M4): ids depois dos do jogo
        n += 1
    docs = [json.loads((events / f"{i:04d}.json").read_text(encoding="utf-8")) for i in range(n)]
    blob = bytearray(BLOB_LEN)
    for a, h in meta["rest"].items():
        d = bytes.fromhex(h)
        blob[int(a, 16):int(a, 16) + len(d)] = d
    # cabecalho: com roteiros novos as duas tabelas crescem (banco 1, a partir de +0; 3 bytes por roteiro) e os
    # roteiros do banco 1 que ficavam logo depois delas vao para um banco novo
    offs, banks = meta["offsets"], meta["offsets"] + 2 * n
    hdr_end = BANK + banks + n
    if hdr_end > 2 * BANK:
        raise SystemExit(f"{n} roteiros: o cabecalho nao cabe no banco 1")
    for k, v in ((0, offs + 0x4000), (2, banks + 0x4000)):
        blob[k], blob[k + 1] = v & 0xFF, v >> 8
    # espaco original de cada roteiro: do inicio ate o proximo inicio do banco (ou o fim do banco)
    pos = sorted({d["bank"] * BANK + d["start"] for d in docs if "shared_with" not in d and "bank" in d})
    room = {}
    for k, p in enumerate(pos):
        end = (p // BANK + 1) * BANK
        nxt = pos[k + 1] if k + 1 < len(pos) and pos[k + 1] < end else end
        room[p] = nxt - p if p >= hdr_end else -1
    place = {}
    extra = bytearray()          # bancos novos (8+)
    ops, by_name = load_ops(events)
    for d in docs:
        if "shared_with" in d:
            continue
        data = script_bytes(events, d, ops, by_name)
        p = d["bank"] * BANK + d["start"] if "bank" in d else -1
        if len(data) <= room.get(p, -1):
            blob[p:p + len(data)] = data
            place[d["id"]] = (d["bank"], d["start"])
        else:
            if len(extra) % BANK + len(data) > BANK:
                extra += bytes(BANK - len(extra) % BANK)
            bank = BLOB_LEN // BANK + len(extra) // BANK
            place[d["id"]] = (bank, len(extra) % BANK)
            extra += data
    for d in docs:
        if "shared_with" in d:
            place[d["id"]] = place[d["shared_with"]]
    hb = BANK      # cabecalho no banco 1
    for i in range(n):
        bank, start = place[i]
        v = start + 0x4000
        blob[hb + offs + 2 * i] = v & 0xFF
        blob[hb + offs + 2 * i + 1] = v >> 8
        blob[hb + banks + i] = bank
    if extra:
        extra += bytes(-len(extra) % BANK)
    return bytes(blob) + bytes(extra)


def verify(events):
    rom = (DEC / "baserom.gba").read_bytes()
    got = build_blob(events)
    same = got == rom[BLOB_AT:BLOB_AT + BLOB_LEN]
    print(f"gMapScripts: {'igual ao jogo' if same else 'DIFERENTE'} ({len(got)} B)")
    return same


def install(tree, events):
    blob = build_blob(events)
    (tree / "graphics/maps").mkdir(parents=True, exist_ok=True)
    (tree / "graphics/maps/map_scripts.bin").write_bytes(blob)
    st = tree / "graphics/graphics_08590000.s"
    s = st.read_text(encoding="utf-8")
    new = f'{TAB}.incbin "graphics/maps/map_scripts.bin"   @ 0x{BLOB_AT:X}, 0x{BLOB_LEN:X}'
    for old in (f'{TAB}.incbin "baserom.gba", 0x{BLOB_AT:X}, 0x{BLOB_LEN:X}', f'{TAB}.incbin "graphics/maps/map_scripts.bin"'
                + NL):
        if old in s and new not in s:
            s = s.replace(old, new + (NL if old.endswith(NL) else ""), 1)
    st.write_text(s, encoding="utf-8")
    return len(blob)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=str(ROOT / "data/events"))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--asm")
    a = ap.parse_args()
    if a.verify:
        raise SystemExit(0 if verify(Path(a.events)) else 1)
    if a.asm:
        print(f"gMapScripts: {install(Path(a.asm), Path(a.events))} B")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
