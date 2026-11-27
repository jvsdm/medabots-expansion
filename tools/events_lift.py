"""events_lift.py - Extrai os roteiros de evento do jogo para data/events/ (M2 do pc/research/MAPAS_EVENTOS_PLANO.md).

gMapScripts (0x764CB0, 0x20000 B) e um bloco em bancos de 16 KB, como no Game Boy (read_map_script_byte em
src/field/map_script.c): os 4 primeiros bytes dao (offsets, bancos) + 0x4000; no banco 1 ficam a tabela de inicio de
cada roteiro (u16, valor - 0x4000 = posicao no banco) e a tabela do banco de cada roteiro (u8).

Saida:
  data/events/NNNN.json   {"id", "bank", "start", "script": "NNNN.evt" (o roteiro em texto, do inicio ate o proximo
                          roteiro do banco; o fim pode ter enchimento), "shared_with": id do 1o roteiro com o mesmo
                          inicio, se for o caso}
  data/events/NNNN.evt    o roteiro em texto (tools/events_text.py)
  data/events/_opcodes.json  tabela de opcodes
  data/events/_blob.json  o que nao e roteiro: banco 0, cabecalho, trechos livres (hex por endereco)
Ida e volta: tools/events_build.py --verify.

Uso: python tools/events_lift.py [--out data/events]
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEC = Path(__import__("os").environ.get("MEDABOTS_DECOMP") or __import__("paths").DECOMP)  # ver maps_inventory
BLOB_AT, BLOB_LEN, BANK = 0x764CB0, 0x20000, 0x4000


def header(blob):
    offs = (blob[0] | blob[1] << 8) - 0x4000
    banks = (blob[2] | blob[3] << 8) - 0x4000
    n = (banks - offs) // 2
    h = BANK
    starts = [(blob[h + offs + 2 * i] | blob[h + offs + 2 * i + 1] << 8) - 0x4000 for i in range(n)]
    bnk = [blob[h + banks + i] for i in range(n)]
    return offs, banks, starts, bnk


def lift(out):
    rom = (DEC / "baserom.gba").read_bytes()
    blob = rom[BLOB_AT:BLOB_AT + BLOB_LEN]
    offs, banks, starts, bnk = header(blob)
    n = len(starts)
    hdr_end = BANK + banks + n                        # fim do cabecalho (banco 1)
    pos = [b * BANK + s for s, b in zip(starts, bnk)]
    distinct = sorted(set(pos))
    first = {}
    for i, p in enumerate(pos):
        first.setdefault(p, i)
    seg = {}
    for k, p in enumerate(distinct):
        bank_end = (p // BANK + 1) * BANK
        nxt = distinct[k + 1] if k + 1 < len(distinct) and distinct[k + 1] < bank_end else bank_end
        seg[p] = (p, nxt)
    covered = sorted(seg.values())
    rest, cur = [], 0
    for a, e in covered:
        if a > cur:
            rest.append((cur, a))
        cur = max(cur, e)
    if cur < BLOB_LEN:
        rest.append((cur, BLOB_LEN))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for i, p in enumerate(pos):
        doc = {"id": i, "bank": bnk[i], "start": starts[i]}
        if first[p] != i:
            doc["shared_with"] = first[p]
        else:
            a, e = seg[p]
            doc["bytes"] = blob[a:e].hex()
        (out / f"{i:04d}.json").write_text(json.dumps(doc) + "\n", encoding="utf-8")
    (out / "_blob.json").write_text(json.dumps({
        "at": hex(BLOB_AT), "len": BLOB_LEN, "count": n, "offsets": offs, "banks": banks, "header_end": hdr_end,
        "rest": {hex(a): blob[a:e].hex() for a, e in rest}}, indent=1) + "\n", encoding="utf-8")
    from events_text import convert, gen_opcodes
    gen_opcodes(out)
    convert(out)                                    # hex -> texto (NNNN.evt)
    shared = sum(1 for i, p in enumerate(pos) if first[p] != i)
    print(f"{n} roteiros ({shared} compartilham inicio), bancos {sorted(set(bnk))}, "
          f"{len(rest)} trechos fora de roteiro ({sum(e - a for a, e in rest)} B) -> {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/events"))
    lift(Path(ap.parse_args().out))


if __name__ == "__main__":
    main()
