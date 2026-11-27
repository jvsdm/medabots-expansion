"""characters_build.py - Personagens novos do projeto (adversarios depois dos 96 do jogo).

O byte 0 de uma luta (gEncounterSetups) escolhe o personagem: nome (gOpponentNames, terminado em FE), fala de antes
(gOpponentPreBattleMessages) e de depois da luta (gOpponentAfterBattleMessages, terminadas em FF 04). As tres tabelas
do jogo tem 96 entradas (0..95). Como no battles_build, o rotulo antigo vira sOrig_<nome> (no .s e nos ponteiros
rotulo+deslocamento do .tsv) e a build monta tabelas novas em asm/characters_project.s: as 96 do jogo (simbolos do
.tsv) + as do projeto, na ordem dos ids.

Retrato opcional: gPortraitTiles[id][0] (expressao 0, formato "Le" do jogo, src/engine/decompress.c) e
gPortraitPalettes[id] (32 bytes) passam a apontar para os arquivos dados (a linha do .tsv troca de simbolo); as outras
expressoes ficam como estao (na versao japonesa tambem so a 0 tem desenho).

Folha do campo opcional ("field_sheet"): gFieldSpriteTiles[id] (LZ77, 0x900 bytes) e gFieldSpritePalettes[id] (32 bytes)
passam a apontar para os arquivos dados. E a folha que o conjunto de sprites da area (sprites.json) carrega; com a
entrada nula o jogo carrega a folha 1 no lugar (src/field/area_graphics.c), e a U tem nulas as que so a J usa (ex.: 97,
o Koishimaru). A linha do .tsv e criada se nao existir.

data/story/characters_new.json: {"characters": [{"id": 96, "name": "...", "pre": "...", "after": "...",
                                                  "portrait": {"tiles": "...le", "palette": "...pal"},
                                                  "field_sheet": {"id": 97, "tiles": "...lz", "palette": "...pal"}}, ...]}
Texto como em data/story/text (tools/text_build.py): | nova linha, || nova caixa, <FB 00 RR 00> retrato RR.

Retratos em falas do jogo (data/story/text_portraits.json, [{"bank", "id", "from", "to"}]): troca o RR de cada
<FB 00 RR 00> de "from" para "to" dentro da fala (ate a fala seguinte do banco), na copia do baserom da arvore.

Uso: python tools/characters_build.py --check
"""
import argparse
import json
from pathlib import Path

from text_build import encode

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/story/characters_new.json"
GAME = 96
NAME_MAX = 0x12          # copy_bytes(gOpponentNames[...], textBuf, 0x12) em prebattle.c / action_phase.c
TABLES = (("gOpponentNames", 0x3C3F38), ("gOpponentPreBattleMessages", 0x3C2BBC),
          ("gOpponentAfterBattleMessages", 0x3C3984))
TEXT_PORTRAITS = ROOT / "data/story/text_portraits.json"
TEXT_BANKS = 0x47E45C    # sOrig_gTextBankTables (USA): 16 ponteiros para as tabelas de cada banco
PORTRAIT_TILES, PORTRAIT_PALS, PORTRAITS = 0x3AFD08, 0x3B15C8, 176   # 9 expressoes por personagem
SHEET_TILES, SHEET_PALS, SHEETS = 0x3F80F4, 0x3F8634, 336            # gFieldSpriteTiles / gFieldSpritePalettes
NL, TAB = chr(10), chr(9)


J_PORTRAIT_TILES, J_PORTRAIT_PALS = 0x3ACE50, 0x3AE710   # Medarot 2 Core Kuwagata (J): 36 B por personagem / 4 B
J_SHEET_TILES, J_SHEET_PALS = 0x3F2CBC, 0x3F31FC         # gFieldSpriteTiles / gFieldSpritePalettes da J


def _j_ptr(rom, at):
    import struct
    return struct.unpack_from("<I", rom, at)[0] - 0x08000000


def _portrait_source(p):
    """Retrato (bloco 'Le' + paleta de 32 B): {"from": "core_kuwagata_j", "char": N, "tiles_len": B} le da ROM de quem
    constroi; {"tiles": arquivo, "palette": arquivo} le arquivos do projeto (desenho proprio)."""
    if "from" in p:
        from roms import rom_bytes
        rom = rom_bytes(p["from"])
        t = _j_ptr(rom, J_PORTRAIT_TILES + 36 * p["char"])
        c = _j_ptr(rom, J_PORTRAIT_PALS + 4 * p["char"])
        return rom[t:t + p["tiles_len"]], rom[c:c + 32]
    return (ROOT / p["tiles"]).read_bytes(), (ROOT / p["palette"]).read_bytes()


def _sheet_source(fs):
    """Folha do campo (LZ77 de 0x900 B + paleta): {"from": "core_kuwagata_j", "sheet": N} le da ROM; senao arquivos."""
    if "from" in fs:
        from roms import rom_bytes
        from codecs_gba import compressed_size
        rom = rom_bytes(fs["from"])
        t = _j_ptr(rom, J_SHEET_TILES + 4 * fs["sheet"])
        c = _j_ptr(rom, J_SHEET_PALS + 4 * fs["sheet"])
        return rom[t:t + compressed_size(rom, t)], rom[c:c + 32]
    return (ROOT / fs["tiles"]).read_bytes(), (ROOT / fs["palette"]).read_bytes()


def load(path=DATA):
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))["characters"]
    want = list(range(GAME, GAME + len(rows)))
    if [r["id"] for r in rows] != want:
        raise SystemExit(f"personagens do projeto precisam ser {want} (sem buraco), veio {[r['id'] for r in rows]}")
    out = []
    for r in rows:
        name = encode(r["name"], f"personagem {r['id']} nome")[:-2] + b"\xFE"
        if len(name) > NAME_MAX:
            raise SystemExit(f"personagem {r['id']}: nome com {len(name) - 1} letras (max {NAME_MAX - 1})")
        pre = encode(r["pre"], f"personagem {r['id']} pre")[:-2] + b"\xFF\x04"
        after = encode(r["after"], f"personagem {r['id']} after")[:-2] + b"\xFF\x04"
        por = None
        if r.get("portrait"):
            if r["id"] >= PORTRAITS:
                raise SystemExit(f"personagem {r['id']}: a tabela de retratos tem {PORTRAITS} entradas")
            tiles, pal = _portrait_source(r["portrait"])
            if tiles[:2] != b"Le" or len(pal) != 32:
                raise SystemExit(f"personagem {r['id']}: retrato precisa de bloco 'Le' e paleta de 32 bytes")
            por = (tiles, pal)
        out.append((r["id"], name, pre, after, por))
    return out


def load_sheets(path=DATA):
    """Folhas do campo dos personagens do projeto: [(id da folha, tiles LZ77, paleta)]."""
    if not path.exists():
        return []
    out = []
    for r in json.loads(path.read_text(encoding="utf-8"))["characters"]:
        fs = r.get("field_sheet")
        if not fs:
            continue
        if not 0 <= fs["id"] < SHEETS:
            raise SystemExit(f"personagem {r['id']}: folha {fs['id']} fora da tabela (0..{SHEETS - 1})")
        tiles, pal = _sheet_source(fs)
        if tiles[0] != 0x10 or int.from_bytes(tiles[1:4], "little") != 0x900 or len(pal) != 32:
            raise SystemExit(f"personagem {r['id']}: folha precisa de LZ77 de 0x900 bytes e paleta de 32 bytes")
        out.append((fs["id"], tiles, pal))
    if len({i for i, *_ in out}) != len(out):
        raise SystemExit("duas folhas do campo com o mesmo id")
    return out


def patch_text_portraits(rom, path=TEXT_PORTRAITS):
    """Aplica data/story/text_portraits.json em `rom` (bytearray da base USA); devolve quantos bytes trocou."""
    if not path.exists():
        return 0
    import struct
    n = 0
    for r in json.loads(path.read_text(encoding="utf-8"))["portraits"]:
        bank = struct.unpack_from("<I", rom, TEXT_BANKS + 4 * r["bank"])[0] - 0x08000000
        ptrs = []
        o = bank
        while rom[o + 3] == 0x08:
            ptrs.append(struct.unpack_from("<I", rom, o)[0] - 0x08000000)
            o += 4
        start = ptrs[r["id"]]
        end = min((p for p in ptrs if p > start), default=start + 0x400)
        old, new = bytes([0xFB, 0, r["from"], 0]), bytes([0xFB, 0, r["to"], 0])
        hits = rom[start:end].count(old)
        if not hits and new not in rom[start:end]:
            raise SystemExit(f"fala {r['bank']}/{r['id']}: sem retrato {r['from']} para trocar")
        rom[start:end] = rom[start:end].replace(old, new)
        n += hits
    return n


def count(path=DATA):
    """Quantos personagens existem com os do projeto (para o battles_build validar o byte 0 das lutas)."""
    return GAME + len(load(path))


def _rename(tree, label):
    stub = next(s for s in (tree / "data").glob("*.s") if f"{label}:" in s.read_text(encoding="utf-8"))
    s = stub.read_text(encoding="utf-8")
    if f"{NL}{label}:" in s:
        stub.write_text(s.replace(f"{TAB}.global {label}{NL}{label}:", f"{TAB}.global sOrig_{label}{NL}sOrig_{label}:"),
                        encoding="utf-8")
        for t in (tree / "config/data_ptrs").glob("*.tsv"):
            x = t.read_text(encoding="utf-8")
            y = x.replace(f"{TAB}{label}+", f"{TAB}sOrig_{label}+").replace(f"{TAB}{label}{NL}", f"{TAB}sOrig_{label}{NL}")
            if y != x:
                t.write_text(y, encoding="utf-8")


def install(tree, path=DATA):
    """asm/characters_project.s com as tabelas novas; sem personagem do projeto, nada muda na arvore."""
    base = tree / "baserom.gba"
    if base.exists() and TEXT_PORTRAITS.exists():
        rom = bytearray(base.read_bytes())
        k = patch_text_portraits(rom)
        base.write_bytes(bytes(rom))
        print(f"  retratos trocados em falas do jogo: {k}")
    rows = load(path)
    out = tree / "asm/characters_project.s"
    if not rows:
        if out.exists():
            out.unlink()
        return 0
    tsvs = list((tree / "config/data_ptrs").glob("*.tsv"))
    a = [f"{TAB}.section .rodata", "", "@ gerado por tools/characters_build.py de data/story/characters_new.json (nao editar)"]
    for k, (label, at) in enumerate(TABLES):
        tsv = next(t for t in tsvs if f"{at + 0x08000000:08X}{TAB}" in t.read_text(encoding="utf-8"))
        ptr = {int(l.split(TAB)[0], 16) - 0x08000000: l.split(TAB)[1]
               for l in tsv.read_text(encoding="utf-8").split(NL) if l and not l.startswith("#")}
        game = [ptr[at + 4 * i] for i in range(GAME)]
        _rename(tree, label)
        game = [g if not (g == label or g.startswith(label + "+")) else "sOrig_" + g for g in game]
        a += [f"{TAB}.align 2", f"{TAB}.global {label}", f"{label}:"]
        a += [f"{TAB}.4byte {g}" for g in game] + [f"{TAB}.4byte sProjectChar{k}_{r[0]}" for r in rows]
        for r in rows:
            a += [f"sProjectChar{k}_{r[0]}:", f"{TAB}.byte " + ", ".join(str(v) for v in r[1 + k])]
    # retratos: a linha do .tsv de gPortraitTiles[id][0] e gPortraitPalettes[id] passa a apontar para os dados novos
    for cid, *_, por in rows:
        if not por:
            continue
        a += [f"{TAB}.align 2", f"{TAB}.global sProjectPortraitPal{cid}", f"sProjectPortraitPal{cid}:",
              f"{TAB}.byte " + ", ".join(str(v) for v in por[1]),
              f"{TAB}.global sProjectPortraitTiles{cid}", f"sProjectPortraitTiles{cid}:",
              f"{TAB}.byte " + ", ".join(str(v) for v in por[0])]
        for at, sym in ((PORTRAIT_TILES + cid * 9 * 4, f"sProjectPortraitTiles{cid}"),
                        (PORTRAIT_PALS + cid * 4, f"sProjectPortraitPal{cid}")):
            key = f"{at + 0x08000000:08X}{TAB}"
            t = next(t for t in tsvs if key in t.read_text(encoding="utf-8"))
            lines = t.read_text(encoding="utf-8").split(NL)
            lines = [f"{key}{sym}" if l.startswith(key) else l for l in lines]
            t.write_text(NL.join(lines), encoding="utf-8")
    # folhas do campo: a linha do .tsv de gFieldSpriteTiles[id] / gFieldSpritePalettes[id] (criada se a entrada era nula)
    for sid, tiles, pal in load_sheets(path):
        a += [f"{TAB}.align 2", f"{TAB}.global sProjectFieldSheetPal{sid}", f"sProjectFieldSheetPal{sid}:",
              f"{TAB}.byte " + ", ".join(str(v) for v in pal),
              f"{TAB}.align 2", f"{TAB}.global sProjectFieldSheetTiles{sid}", f"sProjectFieldSheetTiles{sid}:",
              f"{TAB}.byte " + ", ".join(str(v) for v in tiles)]
        stub = next(s for s in (tree / "data").glob("*.s") if "gFieldSpriteTiles:" in s.read_text(encoding="utf-8"))
        t = tree / "config/data_ptrs" / f"data_{stub.stem}.tsv"
        lines = [l for l in t.read_text(encoding="utf-8").split(NL) if l]
        for at, sym in ((SHEET_TILES + sid * 4, f"sProjectFieldSheetTiles{sid}"),
                        (SHEET_PALS + sid * 4, f"sProjectFieldSheetPal{sid}")):
            key = f"{at + 0x08000000:08X}{TAB}"
            lines = [l for l in lines if not l.startswith(key)]
            lines.append(f"{key}{sym}")
        head = [l for l in lines if l.startswith("#")]
        body = sorted((l for l in lines if not l.startswith("#")), key=lambda l: int(l.split(TAB)[0], 16))
        t.write_text(NL.join(head + body) + NL, encoding="utf-8")
    a.append(f"{TAB}.align 2")
    out.write_text(NL.join(a) + NL, encoding="utf-8")
    ld = tree / "ld_script.ld"
    t = ld.read_text(encoding="utf-8")
    obj = "build/asm/characters_project.o(.rodata);"
    if obj not in t:
        anchor = "build/asm/maps_area_tables.o(.rodata);"
        assert anchor in t, "ld_script sem maps_area_tables (rode tools/maps_build.py --asm antes)"
        ld.write_text(t.replace(anchor, f"{anchor}{NL}        {obj}", 1), encoding="utf-8")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.parse_args()
    rows = load()
    print(f"{len(rows)} personagens do projeto: " + ", ".join(f"{i} {json.loads(DATA.read_text(encoding='utf-8'))['characters'][n]['name']}"
                                                         for n, (i, *_r) in enumerate(rows)))


if __name__ == "__main__":
    main()
