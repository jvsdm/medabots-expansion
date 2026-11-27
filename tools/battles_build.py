"""battles_build.py - Lutas novas do projeto (times de Robattle depois das 246 do jogo).

O jogo le a luta N em gEncounterSetups[N] (ponteiro para 0x28 bytes copiados para gBattleWork; src/battle/prebattle.c).
A tabela original (246 ponteiros, USA 0x3C1A00) entra na arvore como .incbin com ponteiros realocados pelo .tsv; para
nao deslocar nada, ela vira sOrig_gEncounterSetups e a build monta uma gEncounterSetups nova em asm/battles_project.s:
as 246 entradas do jogo (o simbolo de cada uma vem do .tsv) + as do projeto, na ordem dos ids.

data/story/battles_new.json: {"battles": [{"id": 246, "name": "...", "from": "core_kuwagata_j"}, ...]} (ver record_bytes:
de onde vem os 0x28 bytes; "hex" tambem vale)
ids seguidos a partir de 246 (sem buraco). Byte 0 = personagem (nome e falas de antes/depois da luta, gOpponentNames
tem 96 entradas: 0..95, mais as de data/story/characters_new.json), byte 2 = quantos bots (1..3), +4.. = 3 registros de 0xC (cabeca, braco dir., braco esq.,
pernas, medalha, nivel, ...). Os ids de luta cabem em 1 byte no roteiro (Start_Battle), entao no maximo 255.

Uso: python tools/battles_build.py --check
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/story/battles_new.json"
TABLE_AT = 0x3C1A00          # gEncounterSetups (USA)
GAME = 246
NL, TAB = chr(10), chr(9)


J_SETUPS = 0x3BD83C       # gEncounterSetups da Medarot 2 Core Kuwagata (J): 253 ponteiros


def record_bytes(r):
    """Os 0x28 bytes da luta. "from": "core_kuwagata_j" = a luta de mesmo id (ou "group") da versao japonesa;
    "from": "rokusho_us" + "group" = um grupo do jogo como base. "char" e "levels" trocam o personagem (+0) e o nivel
    da medalha de cada inimigo (+5). "hex" = bytes escritos a mao. Os bytes do jogo vem da ROM de quem constroi."""
    if "hex" in r:
        return bytes.fromhex(r["hex"])
    import struct
    from roms import rom_bytes
    src = r["from"]
    rom = rom_bytes(src)
    table = J_SETUPS if src == "core_kuwagata_j" else TABLE_AT
    g = r.get("group", r["id"])
    p = struct.unpack_from("<I", rom, table + 4 * g)[0] - 0x08000000
    b = bytearray(rom[p:p + 0x28])
    if "char" in r:
        b[0] = r["char"]
    for k, lv in enumerate(r.get("levels", [])[:b[2]]):
        b[4 + 12 * k + 5] = lv
    return bytes(b)


def load(path=DATA):
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))["battles"]
    want = list(range(GAME, GAME + len(rows)))
    got = [r["id"] for r in rows]
    if got != want:
        raise SystemExit(f"lutas do projeto precisam ser {want} (sem buraco), veio {got}")
    if want and want[-1] > 255:
        raise SystemExit("luta passa de 255 (Start_Battle guarda 1 byte)")
    import characters_build
    names = characters_build.count()
    out = []
    for r in rows:
        b = record_bytes(r)
        if len(b) != 0x28:
            raise SystemExit(f"luta {r['id']}: precisa de 0x28 bytes, veio {len(b):#x}")
        if b[0] >= names:
            raise SystemExit(f"luta {r['id']}: personagem {b[0]} fora de gOpponentNames (0..{names - 1}; "
                             "personagens novos em data/story/characters_new.json)")
        if not 1 <= b[2] <= 3:
            raise SystemExit(f"luta {r['id']}: quantidade de bots {b[2]} (1..3)")
        out.append((r["id"], b))
    return out


def install(tree, path=DATA):
    """asm/battles_project.s com a gEncounterSetups nova; sem lutas do projeto, nada muda na arvore."""
    rows = load(path)
    out = tree / "asm/battles_project.s"
    if not rows:
        if out.exists():
            out.unlink()
        return 0
    tsv = next(t for t in (tree / "config/data_ptrs").glob("*.tsv") if f"{TABLE_AT + 0x08000000:08X}{TAB}" in
               t.read_text(encoding="utf-8"))
    ptr = {int(l.split(TAB)[0], 16) - 0x08000000: l.split(TAB)[1] for l in tsv.read_text(encoding="utf-8").split(NL)
           if l and not l.startswith("#")}
    game = [ptr[TABLE_AT + 4 * i] for i in range(GAME)]
    stub = next(s for s in (tree / "data").glob("*.s") if "gEncounterSetups:" in s.read_text(encoding="utf-8"))
    s = stub.read_text(encoding="utf-8")
    if f"{NL}gEncounterSetups:" in s:
        stub.write_text(s.replace(f"{TAB}.global gEncounterSetups{NL}gEncounterSetups:",
                                  f"{TAB}.global sOrig_gEncounterSetups{NL}sOrig_gEncounterSetups:"), encoding="utf-8")
        for t in (tree / "config/data_ptrs").glob("*.tsv"):
            x = t.read_text(encoding="utf-8")
            if f"{TAB}gEncounterSetups+" in x or x.endswith(f"{TAB}gEncounterSetups") or f"{TAB}gEncounterSetups{NL}" in x:
                x = x.replace(f"{TAB}gEncounterSetups+", f"{TAB}sOrig_gEncounterSetups+")
                x = x.replace(f"{TAB}gEncounterSetups{NL}", f"{TAB}sOrig_gEncounterSetups{NL}")
                t.write_text(x, encoding="utf-8")
    a = [f"{TAB}.section .rodata", "", "@ gerado por tools/battles_build.py a partir de data/story/battles_new.json (nao editar)",
         f"{TAB}.align 2", f"{TAB}.global gEncounterSetups", "gEncounterSetups:"]
    a += [f"{TAB}.4byte {g}" for g in game] + [f"{TAB}.4byte sProjectBattle{i}" for i, _ in rows]
    for i, b in rows:
        a += [f"sProjectBattle{i}:", f"{TAB}.byte " + ", ".join(str(v) for v in b)]
    a.append(f"{TAB}.align 2")
    out.write_text(NL.join(a) + NL, encoding="utf-8")
    ld = tree / "ld_script.ld"
    t = ld.read_text(encoding="utf-8")
    obj = "build/asm/battles_project.o(.rodata);"
    if obj not in t:
        anchor = "build/asm/maps_area_tables.o(.rodata);"
        assert anchor in t, "ld_script sem maps_area_tables (rode tools/maps_build.py --asm antes)"
        t = t.replace(anchor, f"{anchor}{NL}        {obj}", 1)
        ld.write_text(t, encoding="utf-8")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    rows = load()
    print(f"{len(rows)} lutas do projeto: " + ", ".join(str(i) for i, _ in rows))


if __name__ == "__main__":
    main()
