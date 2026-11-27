"""decomp_layout.py - Grava <rom>.layout.json ao lado de uma ROM da decomp, para o WPF (Medabots-Romhacking-Toolkit)
ler as tabelas pelos simbolos da build em vez das assinaturas de codigo (pc/research/EXPANSAO_MODULAR.md, passo 4).

Como o mapeamento sai (sem lista escrita a mao):
  1. as assinaturas do proprio toolkit (git/Medabots-Romhacking-Toolkit/src/Medabots.Rom/Layout/*.cs: padrao de codigo,
     ldr, delta) rodam sobre a ROM original do Rokusho USA (baserom da decomp_rok) -> endereco de cada tabela;
  2. cada endereco vira simbolo + deslocamento pelo .map da build original (decomp_rok, que bate com a baserom);
  3. na arvore alvo, o mesmo simbolo + deslocamento pelo .map dela. As tabelas que a expansao substitui mantem o nome
     (a original vira <nome>_vanilla), entao o WPF passa a ler as ampliadas.
Tambem grava BotCount / TinpetId (NUM_MEDABOTS do Makefile), que o toolkit le de um cmp de 8 bits que nao serve
acima de 255 bots.
Uso: python tools/decomp_layout.py <arvore>   (le <arvore>/medabots_rokusho.map; grava medabots_rokusho.layout.json)
"""
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import paths  # noqa: E402
TOOLKIT_LAYOUT = paths.TOOLKIT / "src/Medabots.Rom/Layout"
REF = paths.DECOMP_ORIGINAL
GBA = 0x08000000
CODE_END = 0x0E0000
SIG = re.compile(r'new\("(\w+)",\s*"([0-9A-F? ]+)",\s*(\d+),\s*(-?0x[0-9A-Fa-f]+|-?\d+)\)')
DERIVED = re.compile(r'new\("(\w+)",\s*"(\w+)",\s*(-?0x[0-9A-Fa-f]+|-?\d+)\)')


def signatures():
    sigs, derived = [], []
    for f in sorted(TOOLKIT_LAYOUT.glob("*.cs")):
        t = f.read_text(encoding="utf-8")
        for name, pat, ldr, delta in SIG.findall(t):
            sigs.append((name, [None if b == "??" else int(b, 16) for b in pat.split()], int(ldr), int(delta, 0)))
        for name, base, delta in DERIVED.findall(t):
            derived.append((name, base, int(delta, 0)))
    return sigs, derived


# MedabotsRomTextProfiles.cs, "Medabots Rokusho Version (U)": enderecos na ROM original (a decomp_rok bate com ela)
PROFILE_USA = {"TextPointerTableOffset": 0x47E45C, "StarterOffset": 0x7840C0, "BattlePointerTableOffset": 0x3C1A00,
               "EventTableOffset": 0x768CB0}
PROFILE_COUNTS = {"BattleCount": 0xF6, "EventCount": 0x8F0}


def find_unique(code, pat):
    anchor = next(i for i, b in enumerate(pat) if b is not None)
    found = -1
    for i in range(0, len(code) - len(pat) + 1, 2):
        if code[i + anchor] != pat[anchor]:
            continue
        if all(b is None or code[i + j] == b for j, b in enumerate(pat)):
            if found >= 0:
                return -1
            found = i
    return found


def resolve(rom):
    """Mesma regra do RomLayout.Resolve do toolkit (primeira assinatura que acha, achado unico)."""
    sigs, derived = signatures()
    code = rom[:CODE_END]
    tables = {}
    for name, pat, ldr, delta in sigs:
        if name in tables:
            continue
        m = find_unique(code, pat)
        if m < 0:
            continue
        at = m + ldr
        ins = struct.unpack_from("<H", rom, at)[0]
        lit = ((at + 4) & ~3) + (ins & 0xFF) * 4
        tables[name] = struct.unpack_from("<I", rom, lit)[0] - GBA + delta
    for name, base, delta in derived:
        if name not in tables and base in tables:
            tables[name] = tables[base] + delta
    return tables


def symbols(map_path):
    out = {}
    for m in re.finditer(r"^\s+0x([0-9a-f]{8})\s+(\w+)\s*$", map_path.read_text(encoding="utf-8", errors="replace"),
                         re.M):
        a = int(m.group(1), 16)
        if 0x08000000 <= a < 0x0A000000:
            out.setdefault(m.group(2), a - GBA)
    return out


def main():
    tree = Path(sys.argv[1])
    ref_rom = (REF / "baserom.gba").read_bytes()
    ref_syms = symbols(REF / "medabots_rokusho.map")
    by_addr = sorted((a, s) for s, a in ref_syms.items())
    syms = symbols(tree / "medabots_rokusho.map")
    out, missing = {}, []
    for name, off in sorted(resolve(ref_rom).items()):
        # simbolo da build original que contem o endereco (o de endereco mais alto <= off)
        cand = [(a, s) for a, s in by_addr if a <= off]
        if not cand:
            missing.append(name)
            continue
        a, s = cand[-1]
        if s not in syms:
            missing.append(f"{name} ({s} nao existe na arvore)")
            continue
        out[name] = {"offset": syms[s] + off - a, "symbol": s, "delta": off - a}
    # enderecos do perfil de texto do toolkit (MedabotsRomTextProfiles, Rokusho USA): texto, inicial, lutas, eventos.
    # Sem eles o WPF lia esses blocos nos enderecos fixos da ROM original (lixo -> "not a valid GBA ROM address").
    addresses, miss2 = {}, []
    for name, off in PROFILE_USA.items():
        cand = [(a, s) for a, s in by_addr if a <= off]
        if not cand or cand[-1][1] not in syms:
            miss2.append(name)
            continue
        a, s = cand[-1]
        addresses[name] = syms[s] + off - a
    rom_len = (tree / "medabots_rokusho.gba").stat().st_size if (tree / "medabots_rokusho.gba").exists() else None
    if "gToolkitTextSpace" in syms:   # bloco de 64 KB reservado pela build (decomp_expand) para o texto do WPF
        addresses["TextDumpOffset"] = syms["gToolkitTextSpace"]
    elif rom_len:   # build antiga: depois do fim da ROM (o gravador de texto do toolkit recusa; so leitura)
        addresses["TextDumpOffset"] = (rom_len + 0xFF) & ~0xFF
    addresses.update(PROFILE_COUNTS)
    # bancos de fala: 16 do jogo + os do projeto (asm/text_project.s, tools/text_build.py); o WPF le todos
    tp = tree / "asm/text_project.s"
    if tp.exists():
        body = tp.read_text(encoding="utf-8").split("gTextBankTables:", 1)[1]
        addresses["TextBankCount"] = len(re.findall(r"^\s*\.4byte\b", body.split(":", 1)[0], re.M))
    else:
        addresses["TextBankCount"] = 16
    if miss2:
        missing += [f"perfil:{m}" for m in miss2]
    mk = (tree / "Makefile").read_text(encoding="utf-8", errors="replace")
    n = re.search(r"-DNUM_MEDABOTS=(\d+)", mk)
    n = int(n.group(1)) if n else 120
    doc = {"source": "decomp (tools/decomp_layout.py)", "bot_count": n, "tinpet_id": n,
           "tables": {k: v["offset"] for k, v in out.items()},
           "addresses": addresses,
           "symbols": {k: f"{v['symbol']}+0x{v['delta']:X}" if v["delta"] else v["symbol"] for k, v in out.items()}}
    dst = tree / "medabots_rokusho.layout.json"
    dst.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"{dst}: {len(out)} tabelas, {n} bots" + (f"; sem simbolo: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
