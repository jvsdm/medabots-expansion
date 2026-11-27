"""
gen_signatures.py - Gera assinaturas de codigo para o Toolkit localizar cada tabela em qualquer versao.

Referencia: Rokusho (E), cujos offsets sao os de MedabotsRomSchema.cs. Para cada tabela:
  1. acha literal pools no codigo cujo valor L fica em [T-0x100, T] (T = offset da tabela);
  2. para cada `ldr rX, [pc]` que le esse pool, monta uma janela de bytes com curingas
     (imm do ldr-literal, branches, BL);
  3. so aceita a assinatura se ela casa exatamente 1 vez em CADA ROM de validacao;
  4. resolve a tabela em cada ROM (literal lido + delta T-L) e exige que as assinaturas concordem.

Saidas:
  git/Medabots-Romhacking-Toolkit/src/Medabots.Rom/Layout/RomTableSignatures.cs  (gerado)
  data/layout_by_version.md                              (tabelas resolvidas por versao)
"""
import re
import struct
from pathlib import Path
from medarom import ROOT

SCHEMA = ROOT / "git" / "Medabots-Romhacking-Toolkit" / "src" / "Medabots.Rom" / "Projects" / "MedabotsRomSchema.cs"
OUT_CS = ROOT / "git" / "Medabots-Romhacking-Toolkit" / "src" / "Medabots.Rom" / "Layout" / "RomTableSignatures.cs"
OUT_MD = ROOT / "data" / "layout_by_version.md"
REFERENCE = "Medabots - Rokusho (Europe).gba"
VALIDATION = ["Medabots - Rokusho (Europe).gba", "Medabots - Metabee (Europe).gba", "Medabots - Rokusho (USA).gba"]
CODE_END = 0x0A0000
GBA = 0x08000000
SKIP = {"HeaderOffset", "BattleBotOffset", "EventBankTableOffset"}   # nao sao tabelas em ROM
MAX_DELTA = 0x100
WINDOWS = ((12, 12), (16, 16), (20, 20), (8, 10))
MAX_SIGS = 3
# Tabelas sem leitura direta no codigo: offset fixo em relacao a uma vizinha resolvida
# (blocos contiguos dimensionados por constantes iguais em todas as versoes).
DERIVED = {
    "MapDimensionsInMetaTilesTableOffset": "MapTilesetGraphicsPointerTableOffset",   # 192 mapas x 2 B antes
    "MapTilesetPalettePointerTableOffset": "MapLayerTilemapPointerTableOffset",      # 192 x 3 camadas x 4 B depois
    "SharedPartDetailTileSheetAOffset": "SharedPartDetailTileSheetEOffset",
    "SharedPartDetailTileSheetBOffset": "SharedPartDetailTileSheetEOffset",
    "SharedPartDetailTileSheetCOffset": "SharedPartDetailTileSheetEOffset",
    "SharedPartDetailTileSheetDOffset": "SharedPartDetailTileSheetEOffset",
}


def u16(d, o):
    return struct.unpack_from("<H", d, o)[0]


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def mask_window(d, start, end):
    """Lista de bytes (None = curinga). Mascaram-se imm de ldr-literal, branches e BL."""
    out, pc = [], start
    while pc < end:
        lo, hi = d[pc], d[pc + 1]
        if 0xF0 <= hi <= 0xF7 and pc + 3 < end and d[pc + 3] >= 0xF8:
            out += [None, None, None, None]          # BL
            pc += 4
            continue
        if hi >= 0xF8 or hi >> 3 == 0b01001 or 0xD0 <= hi <= 0xE7:
            out += [None, hi if hi < 0xF8 else None]   # 2a metade de BL / ldr [pc] / branch
        else:
            out += [lo, hi]
        pc += 2
    return out


def to_regex(mask):
    return re.compile(b"".join(b"." if b is None else re.escape(bytes([b])) for b in mask), re.S)


def ldr_sites(d, pool):
    sites = []
    for pc in range(max(0, pool - 1020), pool, 2):
        hw = u16(d, pc)
        if hw >> 11 == 0b01001 and ((pc + 4) & ~3) + (hw & 0xFF) * 4 == pool:
            sites.append(pc)
    return sites


def read_literal(d, ldr_pc):
    hw = u16(d, ldr_pc)
    return u32(d, ((ldr_pc + 4) & ~3) + (hw & 0xFF) * 4)


def main():
    tables = [(n, int(v, 16)) for n, v in
              re.findall(r"public const int (\w+Offset) = (0x[0-9A-Fa-f]+);", SCHEMA.read_text(encoding="utf-8"))
              if n not in SKIP]
    roms = {name: (ROOT / name).read_bytes() for name in VALIDATION}
    ref = roms[REFERENCE]
    # Tabelas que o Toolkit acha por assinatura de DADOS (quebra em ROM expandida): resolver pelo codigo
    part_sig = bytes([0x0F, 0x22, 0x02, 0x00, 0x23, 0x15, 0x08, 0x01, 0x08, 0x00])
    tables.append(("PartTableOffset", ref.find(part_sig)))

    pools = {}
    for o in range(0, CODE_END, 4):
        v = u32(ref, o)
        if GBA <= v < GBA + 0x800000:
            pools.setdefault(v - GBA, []).append(o)

    results, cs_entries = {}, []
    for name, T in tables:
        candidates = sorted(((T - L, o) for L, os_ in pools.items() if 0 <= T - L < MAX_DELTA for o in os_))
        sigs = []
        for delta, pool in candidates:
            for site in ldr_sites(ref, pool):
                for before, after in WINDOWS:
                    mask = mask_window(ref, site - before, site + after)
                    rx = to_regex(mask)
                    hits = {}
                    for rname, d in roms.items():
                        m = [x.start() for x in rx.finditer(d[:CODE_END + 0x40000]) if x.start() % 2 == 0]
                        if len(m) != 1:
                            break
                        hits[rname] = read_literal(d, m[0] + before) - GBA + delta
                    else:
                        if hits[REFERENCE] == T:
                            sigs.append((mask, before, delta, hits))
                            break
                if len(sigs) >= MAX_SIGS:
                    break
            if len(sigs) >= MAX_SIGS:
                break
        agree = sigs and all(s[3] == sigs[0][3] for s in sigs)
        results[name] = (T, sigs[0][3] if sigs else None, len(sigs), agree)
        for mask, before, delta, _ in sigs:
            pattern = " ".join("??" if b is None else f"{b:02X}" for b in mask)
            cs_entries.append(f'        new("{name[:-len("Offset")]}", "{pattern}", {before}, 0x{delta:X}),')

    derived_cs = []
    for name, base in DERIVED.items():
        T, B = dict(tables)[name], dict(tables)[base]
        bh = results[base][1]
        hits = {r: bh[r] + (T - B) for r in VALIDATION}
        # valida: conteudo (32 B) igual ao da referencia, exceto em tabelas de ponteiros
        ok = all(roms[r][hits[r]:hits[r] + 32] == ref[T:T + 32] for r in VALIDATION) or "Pointer" in name
        results[name] = (T, hits, 1, ok)
        derived_cs.append(f'        new("{name[:-len("Offset")]}", "{base[:-len("Offset")]}", {T - B}),')

    OUT_CS.parent.mkdir(exist_ok=True)
    OUT_CS.write_text(
        "// <auto-generated> by tools/gen_signatures.py from the Rokusho (E) reference ROM. Do not edit.\n"
        "namespace Medabots.Rom.Layout;\n\n"
        "internal static class RomTableSignatures\n{\n"
        "    // (table, code pattern with ?? wildcards, offset of the `ldr rX, [pc]` inside the pattern,\n"
        "    //  delta added to the loaded literal to reach the table start)\n"
        "    public static readonly RomTableSignature[] All =\n    [\n"
        + "\n".join(cs_entries) + "\n    ];\n\n"
        "    // (table, base table, byte offset from the base table) for tables never read directly by code\n"
        "    public static readonly RomDerivedTable[] Derived =\n    [\n"
        + "\n".join(derived_cs) + "\n    ];\n}\n", encoding="utf-8")

    lines = ["# Tabelas resolvidas por assinatura de codigo\n",
             "| tabela | Rokusho E (schema) | " + " | ".join(VALIDATION[1:]) + " | assinaturas | concordam |",
             "|---|---|" + "---|" * (len(VALIDATION) - 1) + "---|---|"]
    missing = []
    for name, (T, hits, n, agree) in results.items():
        if not hits:
            missing.append(name)
            lines.append(f"| {name} | 0x{T:06X} | " + " | ".join("-" for _ in VALIDATION[1:]) + " | 0 | - |")
            continue
        cols = " | ".join(f"0x{hits[r]:06X} ({hits[r] - T:+#x})" for r in VALIDATION[1:])
        lines.append(f"| {name} | 0x{T:06X} | {cols} | {n} | {'sim' if agree else '**NAO**'} |")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nsem assinatura: {missing}")


if __name__ == "__main__":
    main()
