"""
decomp_expand.py - Gera uma arvore da descompilacao (rommerhacks/medabots-rokusho, branch `expansion` do clone em
build/scratch/decomp_rok) com MAIS Medabots, sem mover nada do jogo original.

Uso: python tools/decomp_expand.py --bots bots.json [--src build/scratch/decomp_rok] [--dst build/scratch/decomp_x]
     [--give-new]   (teste: New Game ja tem 1 de cada peca dos bots novos)
     depois, na arvore: make (alvo all; nao bate com a ROM original de proposito)

bots.json: lista de bots novos, ids 120, 121, ... em ordem:
  [{"name": "TESTBOT", "parts": ["HEAD NAME", "RARM NAME", "LARM NAME", "LEGS NAME"], "clone": 43}]
  `clone` = bot original cujos dados (stats, sprites, paleta, movimento, moldes de preview) sao copiados. Campos
  opcionais `stats` (4 listas de 16 bytes) substituem os stats copiados.

Como funciona (pc/research/DECOMP_C.md, "Expansao de Medabots"):
  - C: -DNUM_MEDABOTS=N (include/constants/medaparts.h). Tinpet = N/N+1 como no motor original.
  - inventario (4 x N x 2 B) sai da IWRAM 0x03004C40 (0x3C0 B, cheio) para a EWRAM 0x0202E000 (livre; mesmo lugar
    da expansao binaria antiga, conferido por varredura de RAM); o save passa a guardar byte a byte (cabe 240 bots).
  - as 10 tabelas por bot/peca ganham copias novas no FIM da ROM (asm/expansion.s), com os mesmos nomes; as
    originais viram <nome>_vanilla e ficam no lugar. Linhas: bots 0..119 (bytes originais), bots novos, depois o
    que vinha logo apos a tabela original (Tinpet 120/121 ou o que o codigo leia alem do fim). Ponteiros copiados
    crus continuam validos porque nada do original mudou de lugar.
"""
import argparse
import json
import re
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
# a expansao (tools/build.py) e montada sobre a propria Rokusho USA (perfil pc/versions/rokusho_us.json): nenhuma ROM
# europeia. Antes de qualquer import do medarom, que le os enderecos do perfil ao carregar.
__import__("os").environ.setdefault("MEDABOTS_VERSION", "rokusho_us")
from medarom import encode_text  # noqa: E402  (mesmo charset na USA: A=1..Z=0x1A, fim 0xFE)

ORIG = 120
# (rotulo, offset USA, bytes por bot, linhas originais, bytes extras copiados depois das linhas)
TABLES = [
    ("gMedapartData", 0x3B827C, 64, 120, 0x80),           # stats: 4 tipos x 16 B
    ("gMedabotNames", 0x3BA4D8, 4, 120, 8),               # ponteiro do nome (pela cabeca)
    ("gMedapartNames", 0x3BB9CC, 16, 120, 32),            # 4 ponteiros
    ("gMedabotPartSpriteTiles", 0x3B1888, 24, 122, 0),    # 6 ponteiros de sprite de batalha (120/121 = Tinpet)
    ("gMedabotSpritePalettes", 0x3BEA14, 1, 122, 0),      # familia de paleta
    ("gLegPartPoseSets", 0x3CABF8, 1, 122, 0),            # estilo de movimento (pernas)
    ("gHeadPartSpriteNodes", 0x7ED00, 16, 122, 0),        # moldes de preview / montagem
    ("gRightArmPartSpriteNodes", 0x7F4A0, 16, 122, 0),
    ("gLeftArmPartSpriteNodes", 0x7FC40, 16, 122, 0),
    ("gLegPartSpriteNodes", 0x803E0, 32, 122, 0),
]
INV_NEW = 0x0202E000
GBA_BASE = 0x08000000


PTRS = {}   # endereco ROM USA de uma palavra-ponteiro -> simbolo (config/data_ptrs/*.tsv da descompilacao)
RENAME = {}  # rotulo original -> rotulo_vanilla


def load_ptrs(src):
    for f in (src / "config/data_ptrs").glob("*.tsv"):
        for line in f.read_text().splitlines():
            if line and not line.startswith("#"):
                ad, sym = line.split("\t", 1)
                base = sym.split("+")[0].strip()
                if base in RENAME:
                    sym = sym.replace(base, RENAME[base], 1)
                PTRS[int(ad, 16) - 0x08000000] = sym


def incbin(off, n):
    """Bytes [off, off+n) do baserom; palavras que sao ponteiros (data_ptrs) saem como .4byte simbolo, para
    continuarem certas mesmo que o codigo mude de tamanho e empurre os dados."""
    out, cur = [], off
    for p in sorted(a for a in PTRS if off <= a < off + n):
        if p > cur:
            out.append(f'\t.incbin "baserom.gba", 0x{cur:X}, 0x{p - cur:X}\n')
        out.append(f"\t.4byte {PTRS[p]}\n")
        cur = p + 4
    if off + n > cur:
        out.append(f'\t.incbin "baserom.gba", 0x{cur:X}, 0x{off + n - cur:X}\n')
    return "".join(out)


def build_expansion_s(bots):
    out = ["@ Tabelas por Medabot ampliadas (tools/decomp_expand.py). Nao editar: gerado.\n", "\t.section .rodata\n"]
    strings = []
    for name, off, size, rows, extra in TABLES:
        out.append(f"\n\t.align 2\n\t.global {name}\n{name}:\n")
        out.append(incbin(off, ORIG * size))                 # bots originais 0..119
        for i, b in enumerate(bots):
            bid = ORIG + i
            if name == "gMedabotNames":
                out.append(f"\t.4byte sExpName{bid}\n")
            elif name == "gMedapartNames":
                out.append("".join(f"\t.4byte sExpPart{bid}_{k}\n" for k in range(4)))
            elif name == "gMedapartData" and b.get("stats"):
                for k in range(4):
                    out.append("\t.byte " + ", ".join(str(x) for x in b["stats"][k]) + "\n")
            else:
                out.append(incbin(off + b["clone"] * size, size))
        out.append(incbin(off + ORIG * size, (rows - ORIG) * size + extra))   # Tinpet / o que vinha depois
    for i, b in enumerate(bots):
        bid = ORIG + i
        strings.append((f"sExpName{bid}", b["name"]))
        for k in range(4):
            strings.append((f"sExpPart{bid}_{k}", b["parts"][k]))
    out.append("\n@ textos dos bots novos (charset do jogo, 0xFE = fim)\n")
    for lab, text in strings:
        out.append(f"{lab}:\n\t.byte " + ", ".join(f"0x{c:02X}" for c in encode_text(text)) + "\n")
    return "".join(out)


def filler_rows(name, off, size, pad):
    """Bots de enchimento (N sobe ate multiplo de 4): a lista de Medaparts mostra 4 por pagina e a ultima
    pagina le os 4 ids; sem enchimento os ids >= N caem no Tinpet e fora do inventario (o jogo reinicia).
    Stats zerados, nome em branco, graficos do Tinpet (linha 120 original); inventario fica zerado."""
    if not pad:
        return ""
    if name == "gMedapartData":
        return "\t.space %d\n" % (pad * size)
    if name == "gMedabotNames":
        return "\t.4byte sExpBlank\n" * pad
    if name == "gMedapartNames":
        return "\t.4byte sExpBlank\n" * (4 * pad)
    return incbin(off + ORIG * size, size) * pad


def clone_rows(name, off, size, clones, first):
    """Linhas de bots clonados (ids first..): dados do bot `clone`, nomes proprios (sExpName<id>/sExpPart<id>_k)."""
    out = []
    for i, b in enumerate(clones):
        bid = first + i
        if b.get("filler"):          # vaga vazia (id 255: 0xFF e "nenhum" no jogo)
            out.append(filler_rows(name, off, size, 1))
            continue
        if name == "gMedabotNames":
            out.append(f"\t.4byte sExpName{bid}\n")
        elif name == "gMedapartNames":
            out.append("".join(f"\t.4byte sExpPart{bid}_{k}\n" for k in range(4)))
        elif name == "gMedapartData" and b.get("stats"):
            out.append("".join("\t.byte " + ", ".join(str(x) for x in b["stats"][k]) + "\n" for k in range(4)))
        elif b.get("rows_asm") and name in b["rows_asm"]:    # bot do Navi com mini proprio (decomp_navi, aba Art)
            out.append(b["rows_asm"][name])
        elif b.get("rows") and name in b["rows"]:
            out.append("\t.4byte " + ", ".join(f"0x{w:08X}" for w in b["rows"][name]) + "\n")
        else:
            out.append(incbin(off + b["clone"] * size, size))
    return "".join(out)


def clone_strings(clones, first):
    out = []
    for i, b in enumerate(clones):
        bid = first + i
        if b.get("filler"):
            continue
        for lab, text in [(f"sExpName{bid}", b["name"])] + [(f"sExpPart{bid}_{k}", b["parts"][k]) for k in range(4)]:
            out.append(f"{lab}:\n\t.byte " + ", ".join(f"0x{c:02X}" for c in encode_text(text)) + "\n")
    return "".join(out)


def form_rows(name, off, size, forms, first):
    """Linhas das formas de Medachange (ids N+2.., logo depois do Tinpet N/N+1): so desenho; nomes e stats do dono."""
    out = []
    for f in forms:
        if f.get("rows_asm") and name in f["rows_asm"]:   # forma de bot proprio: nomes/mini/paleta do dono
            out.append(f["rows_asm"][name])
            continue
        bid = first + f["owner"] if f["owner"] is not None else f["own_bot"]
        if name == "gMedabotNames":
            out.append(f"\t.4byte sExpName{bid}\n")
        elif name == "gMedapartNames":
            out.append("".join(f"\t.4byte sExpPart{bid}_{k}\n" for k in range(4)))
        elif name == "gMedapartData":
            out.append("".join("\t.byte " + ", ".join(str(x) for x in f["stats"][k]) + "\n" for k in range(4)))
        elif name == "gLegPartPoseSets":
            # toda forma anima como perna inteirica (conjunto 2: rodas/tanque/hover/voador pulam juntos, sem passada);
            # com o conjunto do dono (bipede 3, multi 1) a forma "abria" nos passos. O bonus vem da perna de verdade.
            out.append("\t.byte 2\n")
        elif name in f["rows"]:
            out.append("\t.4byte " + ", ".join(f"0x{w:08X}" for w in f["rows"][name]) + "\n")
        else:
            out.append(incbin(off + f["clone"] * size, size))
    return "".join(out)


def json_rows(L, name, ids, bin_json):
    """Linhas do bloco binario com o JSON (data/bots/NNN_*.json) mandando: stats sempre do JSON; nomes do JSON quando
    diferem do que a fonte tem (se iguais, reaproveita o ponteiro da fonte e a ROM nao muda)."""
    slots = ("head", "right_arm", "left_arm", "legs")
    if name == "gMedapartData":
        return "".join("\t.byte " + ", ".join(str(v) for v in bin_json[b]["parts"][s]["stats"].values()) + "\n"
                       for b in ids for s in slots)
    if name == "gMedabotNames":
        src = dict(zip(ids, L.bot_names_ids(ids)))
        return "".join(L.rows_ids(name, [b]) if encode_text(bin_json[b]["name"])[:-1] == src[b]
                       else f"\t.4byte sBinName{b}\n" for b in ids)
    if name == "gMedapartNames":
        src = dict(zip(ids, L.part_names_ids(ids)))
        out = []
        for b in ids:
            rows = L.rows_ids(name, [b]).splitlines()
            for k, s in enumerate(slots):
                if encode_text(bin_json[b]["parts"][s]["name"])[:-1] == src[b][k]:
                    out.append(rows[k] + "\n")
                else:
                    out.append(f"\t.4byte sBinPart{b}_{k}\n")
        return "".join(out)
    return L.rows_ids(name, ids)


def bin_strings(L, ids, bin_json):
    """Textos dos nomes editados no JSON (os iguais a fonte nao geram texto)."""
    out = []
    names = dict(zip(ids, L.bot_names_ids(ids)))
    parts = dict(zip(ids, L.part_names_ids(ids)))
    for b in ids:
        d = bin_json[b]
        if encode_text(d["name"])[:-1] != names[b]:
            out.append((f"sBinName{b}", d["name"]))
        for k, s in enumerate(("head", "right_arm", "left_arm", "legs")):
            if encode_text(d["parts"][s]["name"])[:-1] != parts[b][k]:
                out.append((f"sBinPart{b}_{k}", d["parts"][s]["name"]))
    return "".join(f"{lab}:\n\t.byte " + ", ".join(f"0x{c:02X}" for c in encode_text(t)) + "\n" for lab, t in out)


def build_expansion_s_binary(L, count, pad=0, clones=(), forms=(), bin_ids=None, bin_json=None):
    """Como build_expansion_s, mas os bots 120.. vem da expansao binaria (decomp_lift_binary.Lifter), seguidos
    dos clones de --bots (se houver) e do enchimento."""
    out = ["@ Tabelas por Medabot ampliadas a partir da expansao binaria (tools/decomp_expand.py --from-binary).\n",
           "\t.section .rodata\n"]
    for name, off, size, rows, extra in TABLES:
        out.append(f"\n\t.align 2\n\t.global {name}\n{name}:\n")
        out.append(incbin(off, ORIG * size))
        if bin_ids is not None:
            out.append(json_rows(L, name, bin_ids, bin_json))
        else:
            out.append(L.rows(name, ORIG, count))
        out.append(clone_rows(name, off, size, clones, ORIG + count))
        out.append(filler_rows(name, off, size, pad))
        out.append(incbin(off + ORIG * size, (rows - ORIG) * size + extra))
        if forms:   # o bloco acima e exatamente o Tinpet (2 linhas): a forma k fica no id N + 2 + k
            assert (rows - ORIG) * size + extra == 2 * size, name
            out.append(form_rows(name, off, size, forms, ORIG + count))
    out.append("\nsExpBlank:\n\t.byte 0xFE\n")
    out.append(clone_strings(clones, ORIG + count))
    if bin_ids is not None:
        out.append(bin_strings(L, bin_ids, bin_json))
    molds = L.molds()
    for _, _, text in molds:
        out.append(text)
    a, b = L.region
    out.append(f"\n\t.align 2\n\t.global gExpBin\ngExpBin:   @ area nova da EU expandida 0x{a:X}-0x{b:X}, crua\n"
               f'\t.incbin "expansion_eu.bin"\n')
    return "".join(out), molds


SHOP_STOCK, SHOPS = 0x483E50, 15          # gShopStock (USA): 4 ids de 1 byte por loja, 0xFF = fim
SETUPS, NSETUPS = 0x3C1A00, 246           # gEncounterSetups (USA): ponteiros para grupos de 0x28 B


def wide_tables(usa, a, dst):
    """Id de 16 bits: gShopStockWide (u16, fim 0xFFFF) e gEncounterPartHi (byte alto por grupo/registro).
    Com --test-shop-ids / --test-enemy-ids, poe ids > 255 nas lojas e nos inimigos (os bytes baixos dos grupos
    vao na copia do baserom desta arvore)."""
    stock = [0xFFFF if b == 0xFF else b for b in usa[SHOP_STOCK:SHOP_STOCK + 4 * SHOPS]]
    # mudancas de loja do projeto (data/story/shops.json): {"stock": [{"shop", "slot", "bot_id", "name"}]}
    shops_file = ROOT / "data/story/shops.json"
    if shops_file.exists():
        for e in json.loads(shops_file.read_text(encoding="utf-8"))["stock"]:
            if not (0 <= e["shop"] < SHOPS and 0 <= e["slot"] < 4):
                raise SystemExit(f"shops.json: loja {e['shop']} vaga {e['slot']} fora da tabela ({SHOPS} lojas x 4)")
            stock[4 * e["shop"] + e["slot"]] = e["bot_id"]
            print(f"  loja {e['shop']} vaga {e['slot']}: {e.get('name', e['bot_id'])}")
    if a.test_shop_ids:
        ids = [int(x) for x in a.test_shop_ids.split(",")][:3]
        for s in range(SHOPS):
            stock[4 * s + 1:4 * s + 1 + len(ids)] = ids
    hi = [0] * (256 * 3)        # 256 lutas: o id cabe em 1 byte no Start_Battle (as do projeto vem depois das 246)
    if a.test_enemy_ids:
        ids = [int(x) for x in a.test_enemy_ids.split(",")]
        rom = bytearray((dst / "baserom.gba").read_bytes())
        for g in range(NSETUPS):
            rec = struct.unpack_from("<I", rom, SETUPS + 4 * g)[0] - GBA_BASE
            for k in range(min(3, rom[rec + 2])):            # +2 = quantos inimigos o grupo tem
                pid = ids[k % len(ids)]
                rom[rec + 4 + 12 * k:rec + 8 + 12 * k] = bytes([pid & 0xFF] * 4)
                hi[g * 3 + k] = pid >> 8
        (dst / "baserom.gba").write_bytes(bytes(rom))
    out = ["\n\t.align 2\n\t.global gShopStockWide\ngShopStockWide:   @ estoque das lojas com ids de 16 bits\n"]
    out.append("\t.2byte " + ", ".join(f"0x{x:X}" for x in stock) + "\n")
    out.append("\n\t.global gEncounterPartHi\ngEncounterPartHi:   @ byte alto dos ids dos inimigos (grupo * 3 + registro)\n")
    for g in range(0, len(hi), 24):
        out.append("\t.byte " + ", ".join(str(x) for x in hi[g:g + 24]) + "\n")
    return "".join(out)


BIN_PACKS = {120: "m9"} | {i: "shingata" for i in range(121, 181)} | {181: "binario"}


def bin_key(f):
    """Arquivo data/bots/NNN_nome.json do bloco binario -> 'pacote/nome' na lista de bots."""
    bid = int(f.stem[:3])
    return f"{BIN_PACKS.get(bid, 'binario')}/{f.stem[4:]}"


def read_bot_list(path, bin_files, navi_json):
    """data/expansion_bots.txt -> (arquivos do bloco binario escolhidos, nomes do Navi escolhidos).
    Linhas: 'pacote/nome' ou 'pacote/*' inclui, '-pacote/nome' tira; '#' comenta. Pacotes: m9, shingata, binario
    (bloco da expansao binaria antiga, ids 120..181) e navi (tools/decomp_navi.py, navi_slug). Ordem dos ids: os do
    bloco binario primeiro, depois os do Navi, cada um na ordem original da fonte."""
    import decomp_navi
    keys = {bin_key(f): f for f in bin_files if int(f.stem[:3]) >= ORIG}
    keys.update({f"navi/{decomp_navi.navi_slug(x['name'])}": None for x in navi_json if x["navi_id"] < 150})
    chosen = set()
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        drop = line.startswith("-")
        pat = line.lstrip("-").strip()
        hits = ([k for k in keys if k.split("/")[0] == pat[:-2]] if pat.endswith("/*") else
                [pat] if pat in keys else [])
        if not hits:
            near = [k for k in keys if pat.split("/")[-1][:4] in k][:5]
            raise SystemExit(f"{path}:{n}: '{pat}' nao existe" + (f" (parecidos: {', '.join(near)})" if near else ""))
        chosen = chosen - set(hits) if drop else chosen | set(hits)
    bins = [f for f in bin_files if int(f.stem[:3]) < ORIG or bin_key(f) in chosen]
    navi = {k[5:] for k in chosen if k.startswith("navi/")}
    return bins, navi


SLOTS = ("head", "right_arm", "left_arm", "legs")
BASE_BOTS_FILE = ROOT / "data/anim/base_bots.json"


def part_overrides(bin_json, clones, first_navi):
    """[(id, {slot: {"anim": N, "emit": [dx, dy]}})] das pecas com ajuste de animacao: bots novos (campos "anim" e
    "emit" no JSON da peca) e bots do jogo base 0..119, que nao tem JSON (data/anim/base_bots.json,
    {"43": {"right_arm": {"anim": 60, "emit": [0, 4]}}})."""
    out = []
    if BASE_BOTS_FILE.exists():
        base = json.loads(BASE_BOTS_FILE.read_text(encoding="utf-8"))
        for k, v in base.items():
            if k.startswith("_"):
                continue
            if not (k.isdigit() and int(k) < ORIG) or set(v) - set(SLOTS):
                raise SystemExit(f"data/anim/base_bots.json: {k!r}: chave = id do bot 0..119 e pecas {SLOTS}")
            out.append((int(k), {sl: dict(x) for sl, x in v.items()}))
    out += [(bid, d["parts"]) for bid, d in bin_json.items()]
    out += [(first_navi + i, b["json"]["parts"]) for i, b in enumerate(clones) if b.get("json") is not None]
    return out


def emit_offset_table(n, bin_json, clones, first_navi):
    """gPartEmitOffset (EXP_EMIT_OFFSET): [(id * 4 + peca) * 2] = dx, dy dos efeitos que a peca dispara.
    Campo opcional "emit": [dx, dy] em cada peca do JSON; sem ele 0, 0 (posicao original do roteiro). Testado
    (2026-11-22, bot 217): um padrao automatico dy = -lift piorou (a arma desse bot fica no alto, onde o roteiro ja
    atira); o ajuste e por peca, olhando o cano no visualizador."""
    rows = [[0, 0] * 4 for _ in range(n + 2)]
    for bid, parts in part_overrides(bin_json, clones, first_navi):
        for k, sl in enumerate(SLOTS):
            if "emit" in parts.get(sl, {}):
                rows[bid][2 * k:2 * k + 2] = parts[sl]["emit"]
    for r in rows:
        assert all(-128 <= v <= 127 for v in r), r
    out = ["\n\t.align 2\n\t.global gPartEmitOffset\ngPartEmitOffset:   @ [id][peca] = dx, dy (tools/decomp_expand.py)\n"]
    out += ["\t.byte " + ", ".join(str(v & 0xFF) for v in r) + "\n" for r in rows]
    return "".join(out)


def part_effect_table(n, bin_json, clones, first_navi):
    """gPartNaviEffect (EXP_NAVI_EFFECTS): [(id * 4 + peca) * 2] = efeito extra do Navi da peca, quantidade.
    Campos opcionais "effect" (none/shock/vacuum/booster/scope/level_drain) e "effect_amount" na peca do JSON
    (Level Drain: niveis roubados). Na forma de Medachange vale o do Drive (gNaviDrives)."""
    import decomp_navi
    rows = [[0, 0] * 4 for _ in range(n + 2)]
    for bid, parts in part_overrides(bin_json, clones, first_navi):
        for k, sl in enumerate(SLOTS):
            p = parts.get(sl, {})
            if p.get("effect", "none") != "none":
                rows[bid][2 * k] = decomp_navi.EFFECTS.index(p["effect"])
                rows[bid][2 * k + 1] = max(0, min(255, p.get("effect_amount", 0)))
    out = ["\n\t.align 2\n\t.global gPartNaviEffect\ngPartNaviEffect:   @ [id][peca] = efeito, quantidade\n"]
    out += ["\t.byte " + ", ".join(map(str, r)) + "\n" for r in rows]
    return "".join(out)


def part_anim_table(n, bin_json, clones, first_navi):
    """gPartAnimSkill (EXP_PART_ANIM): [id * 4 + peca] = roteiro de golpe (data/anim/seq) que a peca toca; 0xFF = o
    da sua tecnica. Campo opcional "anim": N em cada peca do JSON. Permite golpes novos (roteiros 60-79, 132-255)
    sem tecnica nova: a peca continua com tecnica/dano/nome dela, so a animacao muda."""
    import anim_seq
    seqs = anim_seq.load_all()
    rows = [[0xFF] * 4 for _ in range(n + 2)]
    for bid, parts in part_overrides(bin_json, clones, first_navi):
        for k, sl in enumerate(SLOTS):
            v = parts.get(sl, {}).get("anim")
            if v is None:
                continue
            if not (0 <= v < 255 and v in seqs):
                raise SystemExit(f"bot {bid} {sl}: anim {v} nao existe em data/anim/seq")
            rows[bid][k] = v
    out = ["\n\t.align 2\n\t.global gPartAnimSkill\ngPartAnimSkill:   @ [id][peca] = roteiro de golpe (0xFF = o da tecnica)\n"]
    out += ["\t.byte " + ", ".join(str(v) for v in r) + "\n" for r in rows]
    return "".join(out)


def expansion_flags(a):
    """Chaves de include/config/expansion.h ligadas por -D (pc/research/EXPANSAO_MODULAR.md)."""
    on = []
    if a.navi:
        on.append("EXP_NAVI_SPRITES")
        if not a.no_medachange:
            on.append("EXP_MEDACHANGE")
            if not a.no_navi_effects:
                on.append("EXP_NAVI_EFFECTS")
    if not getattr(a, "no_emit_offset", False):
        on.append("EXP_EMIT_OFFSET")
    if not getattr(a, "no_part_anim", False):
        on.append("EXP_PART_ANIM")
    if getattr(a, "custom_molds", False):
        on.append("EXP_CUSTOM_MOLDS")
    if getattr(a, "encounter_mix", False):
        on.append("EXP_ENCOUNTER_MIX")
    if getattr(a, "encounter_extra", False):
        on.append("EXP_ENCOUNTER_EXTRA")
    return "".join(f" -D{k}=1" for k in on)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bots", help="bots novos como clones (JSON); ou use --from-binary")
    ap.add_argument("--from-binary", help="ROM gerada por tools/build.py (Metabee EU expandida)")
    ap.add_argument("--binary-log", help="log do build.py dessa ROM (enderecos das tabelas novas)")
    ap.add_argument("--src", default=str(__import__("paths").DECOMP))
    ap.add_argument("--dst", default=str(ROOT / "build/scratch/decomp_x"))
    ap.add_argument("--give-new", action="store_true")
    ap.add_argument("--test-shop-ids", help="teste (N > 252): ids vendidos nas vagas 2-4 de toda loja, ex. 150,280,299")
    ap.add_argument("--test-enemy-ids", help="teste (N > 252): ids dos inimigos por registro de todo grupo, ex. 299,180,281")
    ap.add_argument("--always-encounter", action="store_true", help="teste: todo passo vira encontro (com --give-new)")
    ap.add_argument("--encounter-wildcard", action="store_true",
                    help="inimigo curinga (bot novo sorteado a cada luta) nos grupos de data/encounter_mix.json "
                         "(EXP_ENCOUNTER_MIX); para evento ou teste, desligado por padrao")
    ap.add_argument("--no-encounter-extra", action="store_true",
                    help="sem os encontros fixos dos bots novos (EXP_ENCOUNTER_EXTRA, data/encounters_new.json)")
    ap.add_argument("--navi", action="store_true",
                    help="com --from-binary: os bots do Medarot Navi (tools/decomp_navi.py) no lugar de --bots")
    ap.add_argument("--no-medachange", action="store_true",
                    help="com --navi: sem a Medachange (EXP_MEDACHANGE=0; os bots com forma ficam so na forma normal)")
    ap.add_argument("--no-emit-offset", action="store_true",
                    help="sem o ponto de emissao por peca (EXP_EMIT_OFFSET=0; efeitos de ataque no ponto fixo do roteiro)")
    ap.add_argument("--no-part-anim", action="store_true",
                    help="sem animacao de golpe por peca (EXP_PART_ANIM=0; cada peca toca o roteiro da sua tecnica)")
    ap.add_argument("--no-navi-effects", action="store_true",
                    help="com --navi: sem os efeitos extras dos Drives (Shock/Vacuum/Booster/Scope; EXP_NAVI_EFFECTS=0)")
    ap.add_argument("--bot-list", help="lista de bots (ex. data/expansion_bots.txt): quais bots do bloco binario e do "
                                       "Navi entram; substitui --binary-bots e --navi (pc/research/EXPANSAO_MODULAR.md)")
    ap.add_argument("--binary-bots", type=int,
                    help="com --from-binary: quantos bots da expansao binaria usar (a partir do 120; os do fim saem). "
                         "Ex.: 61 tira o Granbeetle 181 do build.py antigo (o do Navi entra pelo --navi)")
    a = ap.parse_args()
    clones = json.loads(Path(a.bots).read_text(encoding="utf-8")) if a.bots else []
    navi_asm = ""
    bin_files = sorted((ROOT / "data/bots").glob("*.json"))
    navi_select = None
    if a.bot_list:
        if a.binary_bots is not None or a.navi:
            ap.error("--bot-list ja diz os bots: sem --binary-bots / --navi")
        navi_all = json.loads((ROOT / "data/navi/navi_bots.json").read_text(encoding="utf-8"))
        bin_files, navi_select = read_bot_list(a.bot_list, bin_files, navi_all)
        a.navi = bool(navi_select)
        print(f"  lista {a.bot_list}: {len(bin_files) - ORIG} do bloco binario, {len(navi_select)} do Navi")
    elif a.binary_bots is not None:
        bin_files = [f for f in bin_files if int(f.stem[:3]) < ORIG + a.binary_bots]
    bin_ids = [int(f.stem[:3]) for f in bin_files if int(f.stem[:3]) >= ORIG]
    bin_json = {i: json.loads(f.read_text(encoding="utf-8")) for i, f in zip(bin_ids, bin_files[ORIG:])}
    exp_src = (a.from_binary, a.binary_log)
    if a.bot_list:
        # bloco binario montado agora, so com os bots escolhidos (renumerados a partir do 120): tools/build.py em
        # memoria le data/bots/*.json e a ROM do Shingata (graphics_source); sem exp_eu.gba pronto
        import build
        chosen = [json.loads(f.read_text(encoding="utf-8")) for f in bin_files]
        for i, b in enumerate(chosen):
            b["bot_id"] = i
        exp_bytes, exp_log = build.build_rom(chosen, data_only=True)
        exp_src = (exp_bytes, "\n".join(exp_log) + "\n")
        bin_json = {ORIG + k: chosen[ORIG + k] for k in range(len(bin_ids))}
        bin_ids = sorted(bin_json)
        a.from_binary = a.from_binary or "(memoria)"
    if (a.no_medachange or a.no_navi_effects) and not a.navi:
        ap.error("--no-medachange / --no-navi-effects so valem com bots do Navi")
    if a.navi:
        import decomp_navi
        assert (a.from_binary or a.bot_list) and not a.bots, "--navi vai com --from-binary (ou --bot-list) e sem --bots"
        ptrs = {}
        for f in (Path(a.src) / "config/data_ptrs").glob("*.tsv"):
            for line in f.read_text().splitlines():
                if line and not line.startswith("#"):
                    ad, sym = line.split("\t", 1)
                    ptrs[int(ad, 16) - GBA_BASE] = sym
        existing = {f.stem[4:].replace("_", " ").lower() for f in bin_files}
        navi_json = json.loads((ROOT / "data/navi/navi_bots.json").read_text(encoding="utf-8"))
        own_forms = [(bid, bj) for bid, bj in sorted(bin_json.items()) if bj.get("medachange")]
        # paletas de mini da build (3 do jogo + a extra dos bots novos, do bloco binario): mini de desenho proprio do Navi
        import mini_palette
        usa_rom = (Path(a.src) / "baserom.gba").read_bytes()
        exp_rom = exp_src[0] if isinstance(exp_src[0], (bytes, bytearray)) else (
            Path(exp_src[0]).read_bytes() if exp_src[0] and Path(str(exp_src[0])).exists() else None)
        mini_banks = mini_palette.palettes(usa_rom, 0x50DEF8, 3) + (
            mini_palette.palettes(exp_rom, mini_palette.MINI_PALETTES + 32 * mini_palette.EXTRA_BANK, 1) if exp_rom else [])
        clones, navi_asm, info = decomp_navi.plan(usa_rom, navi_json, existing,
                                                  ptrs, navi_select, own_forms, mini_banks)
        if own_forms:
            print(f"  formas de bots proprios: {[bj['name'] for _, bj in own_forms]}")
        navi_info = info
        print(f"  Navi: {len(clones)} bots, moldes novos {info['molds_new']}, {info['images']} imagens, "
              f"chao {info['ground']}, {info['pose_blocks']} blocos de movimento")
    if a.from_binary:
        count = len(bin_files) - ORIG   # bots 120.. do build.py (menos os tirados com --binary-bots)
        bots = None
    else:
        bots = clones
        count = len(bots)
    real = ORIG + count + (len(clones) if a.from_binary else 0)        # bots de verdade (sem enchimento)
    # sem bots de enchimento: o inventario por tipo e arredondado a 4 ids no C (MEDAPART_INV_STRIDE), entao a ultima
    # pagina da lista mostra as linhas sem bot como peca que nao se tem; o Tinpet fica logo depois (N / N+1).
    # Com id de 16 bits o 255 e um bot normal (nenhum 0xFF do jogo e id de peca).
    pad = 0
    n = real
    if n > 337:
        raise SystemExit("ate 337 bots: o save (EEPROM de 8 KB) nao cabe o inventario de mais")
    src, dst = Path(a.src), Path(a.dst)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("build", "build_modern", ".git", "*.elf", "*.map",
                                                            "*.sav", "medabots_rokusho.gba"))
    # dados de area de data/maps (tools/maps_build.py, plano de mapas M1): edicoes nas pastas de area entram na build
    if (ROOT / "data/maps/_layout.json").exists():
        import maps_build
        maps_build.install_all(dst, ROOT / "data/maps")
        print("  dados de area: data/maps (" + ", ".join(maps_build.REGIONS) + ")")
    if (ROOT / "data/events/_blob.json").exists():   # roteiros de evento (tools/events_build.py, plano M2)
        import events_build
        print(f"  roteiros de evento: data/events ({events_build.install(dst, ROOT / 'data/events')} B)")
    if (ROOT / "data/story/text").exists():                # falas novas do projeto (tools/text_build.py, plano M4)
        import text_build
        print(f"  falas do projeto: data/story/text ({text_build.install(dst)} B)")
    if (ROOT / "data/story/battles_new.json").exists():    # lutas novas do projeto (tools/battles_build.py)
        import battles_build
        print(f"  lutas do projeto: {battles_build.install(dst)} (data/story/battles_new.json)")
    if (ROOT / "data/story/characters_new.json").exists():  # personagens novos (tools/characters_build.py);
        import characters_build                                # depois do battles_build (sOrig_gEncounterSetups)
        print(f"  personagens do projeto: {characters_build.install(dst)} (data/story/characters_new.json)")
    # 1. tabelas originais viram <nome>_vanilla (no lugar)
    names = [t[0] for t in TABLES]
    names += ["gPoseKeyframeAngles", "gPoseKeyframeOffsets"]   # blocos vindos de data/anim/poses
    if a.navi:   # crescem para 64 moldes / 63 linhas (tools/decomp_navi.py)
        names += ["gMedabotSpriteNodeDescs"]
    for f in list(dst.glob("data/*.s")) + list(dst.glob("graphics/*.s")):
        t = f.read_text()
        new = t
        for nm in names:
            new = new.replace(f"\t.global {nm}\n{nm}:", f"\t.global {nm}_vanilla\n{nm}_vanilla:")
        if new != t:
            f.write_text(new)
    for f in dst.glob("config/data_ptrs/*.tsv"):
        t = f.read_text()
        new = t
        for nm in names:
            new = new.replace(f"\t{nm}\n", f"\t{nm}_vanilla\n").replace(f"\t{nm}+", f"\t{nm}_vanilla+")
        if new != t:
            f.write_text(new)
    # 2. tabelas novas no fim da ROM (ponteiros pelos simbolos de config/data_ptrs)
    RENAME.update({nm: nm + "_vanilla" for nm in names})
    load_ptrs(src)
    if a.from_binary:
        from decomp_lift_binary import Lifter
        usa = (src / "baserom.gba").read_bytes()
        L = Lifter(exp_src[0], exp_src[1], usa, dst)
        for f in (navi_info["form_rows"] if a.navi else ()):
            if f.get("own_bot") is not None:   # nomes, mini e paleta do mini da forma = os do bot dono
                f["rows_asm"] = {nm: L.rows_ids(nm, [f["own_bot"]]) for nm in
                                 ("gMedabotNames", "gMedapartNames", "gMedabotPartSpriteTiles", "gMedabotSpritePalettes")}
                fm = bin_json[f["own_bot"]].get("_form_mini")
                if fm:   # mini proprio da forma (medachange.mini, cortado em gfx_port.form_mini_components)
                    bank, blobs = fm
                    lab = f"sFormMini{f['own_bot']}"
                    f["rows_asm"]["gMedabotPartSpriteTiles"] = "\t.4byte " + ", ".join(
                        f"{lab}_{k}" for k in range(6)) + "\n"
                    f["rows_asm"]["gMedabotSpritePalettes"] = f"\t.byte {bank}\n"
                    f["mini_asm"] = "".join(f"\t.align 2\n{lab}_{k}:\n\t.byte " + ", ".join(f"0x{v:02X}" for v in blob)
                                            + "\n" for k, blob in enumerate(blobs))
                    print(f"  mini da forma de {f['own_bot']}: banco de paleta {bank}")
        text, molds = build_expansion_s_binary(L, count, pad, clones,
                                               navi_info["form_rows"] if a.navi else (), bin_ids, bin_json)
        text += navi_asm
        for f in (navi_info["form_rows"] if a.navi else ()):
            text += f.get("mini_asm", "")
        if a.navi:   # gNaviMedachange[id]: numero da forma de Medachange (1..) das pernas desse bot; 0 = nenhuma
            flags = [0] * (ORIG + count) + [b.get("form", 0) for b in clones] + [0, 0]
            for k, f in enumerate(navi_info["form_rows"]):   # forma de bot proprio: o numero vai no id do dono
                if f.get("own_bot") is not None:
                    flags[f["own_bot"]] = k + 1
            # bots da base com forma no Navi (ex.: o Granbeetle 181 do build.py) nao tem linhas de forma: use
            # --binary-bots 61 para o do Navi entrar no lugar
            if navi_info["skipped_forms"]:
                print("  aviso: sem Medachange para", navi_info["skipped_forms"], "(use --binary-bots)")
            text += "\t.global gNaviMedachange\ngNaviMedachange:\n"
            text += "".join("\t.byte " + ", ".join(map(str, flags[i:i + 32])) + "\n" for i in range(0, len(flags), 32))
            # gNaviFormMini[numero da forma]: 1 = mini proprio (forma de bot proprio com medachange.mini); [0] = nada
            fm = [0] + [1 if f.get("mini_asm") else 0 for f in navi_info["form_rows"]]
            text += "\t.global gNaviFormMini\ngNaviFormMini:\n"
            text += "".join("\t.byte " + ", ".join(map(str, fm[i:i + 32])) + "\n" for i in range(0, len(fm), 32))
        if not a.no_emit_offset:
            text += emit_offset_table(ORIG + count + len(clones), bin_json, clones, ORIG + count)
        if not a.no_part_anim:
            text += part_anim_table(ORIG + count + len(clones), bin_json, clones, ORIG + count)
        if a.navi and not a.no_navi_effects:
            text += part_effect_table(ORIG + count + len(clones), bin_json, clones, ORIG + count)
        (dst / "asm/expansion.s").write_text(text)
        (dst / "expansion_eu.bin").write_bytes(L.region_bytes())
        if ORIG + count + len(clones) > 252:
            text += wide_tables(usa, a, dst)
            (dst / "asm/expansion.s").write_text(text)
        # registro de cada molde recriado: o ponteiro da lista (config/data_ptrs) vai para gExpMold<d>
        tsv_hits = 0
        for d, rec_eu, _ in molds:
            us_rec = L.M.map(rec_eu)
            key = "%08X\t" % (GBA_BASE + us_rec)
            for f in dst.glob("config/data_ptrs/*.tsv"):
                t = f.read_text()
                lines = t.split("\n")
                for i, line in enumerate(lines):
                    if line.upper().startswith(key):
                        lines[i] = line.split("\t")[0] + f"\tgExpMold{d}"
                        tsv_hits += 1
                f.write_text("\n".join(lines))
        # trechos trocados no lugar (paleta do banco 3, total de paginas): na copia do baserom desta arvore
        rom = bytearray((dst / "baserom.gba").read_bytes()) if (dst / "baserom.gba").exists() else bytearray(usa)
        for uo, data, what in L.inplace():
            rom[uo:uo + len(data)] = data
            print(f"  no lugar: {what} (USA 0x{uo:X})")
        # total de paginas ("/46" da expansao binaria de 184): no mapa LZ, digito d = tile 0x160 + 2d (cima) e +1
        # (baixo), byte alto 0x71; reescreve os bytes baixos para n / 4 (2 digitos bastam: n <= 337)
        pages = (n + 3) // 4
        t, u = divmod(pages, 10)
        if 10 <= pages <= 99 and L.same_base and rom[0x4EFFC0:0x4EFFC4] == bytes([0x20, 0x70, 0x21, 0x70]) \
                and rom[0x4EFFE0:0x4EFFE4] == bytes([0x2B, 0x70, 0xF2, 0x2C]):
            # expansao montada sobre a USA: o "/30" original (tiles 0x20/0x21 e 0x2B/0x2C, paleta 7) vira os dois
            # digitos com o byte alto 0x71, como o build.py fazia na EU (o byte 0x4EFFE2 fica)
            rom[0x4EFFC1] = rom[0x4EFFC3] = rom[0x4EFFE1] = 0x71
        if 10 <= pages <= 99 and rom[0x4EFFC1] == 0x71 and rom[0x4EFFE1] == 0x71:
            rom[0x4EFFC0], rom[0x4EFFC2] = 0x60 + 2 * t, 0x60 + 2 * u
            rom[0x4EFFE0], rom[0x4EFFE3] = 0x61 + 2 * t, 0x61 + 2 * u
            print(f"  total de paginas da lista de Medaparts: {pages}")
        (dst / "baserom.gba").write_bytes(bytes(rom))
        names = [x.decode("latin-1") for x in L.bot_names_ids(bin_ids)]
        print(f"  moldes recriados: {len(molds)}; registros reapontados: {tsv_hits}; avisos: {len(L.bad)}")
        for w in L.bad[:15]:
            print("   aviso:", w)
        bots = [{"name": "?"}] * count
    else:
        text = build_expansion_s(bots)
        # tabelas por peca tambem sem a expansao binaria (nivel CORE): os bots do jogo ficam no padrao (0 / 0xFF)
        if not a.no_emit_offset:
            text += emit_offset_table(ORIG + count, {}, bots, ORIG + count)
        if not a.no_part_anim:
            text += part_anim_table(ORIG + count, {}, bots, ORIG + count)
        (dst / "asm/expansion.s").write_text(text)
    # roteiros de golpe (data/anim/seq): tabela nova no fim de expansion.s; a original vira _vanilla
    import anim_seq
    anim_seq.apply(dst, (src / "baserom.gba").read_bytes())
    # poses (data/anim/poses): com o Navi, Angles/Offsets ja vieram montados com os moldes dele (decomp_navi); sem ele
    # saem daqui com 63 linhas (as 49 do jogo + zeros). Ends e AnimIds sempre.
    import anim_poses
    anim_poses.apply(dst, blocks=not a.navi)
    import anim_effects   # efeitos de golpe novos a partir de PNG (data/anim/effects)
    anim_effects.apply(dst, (src / "baserom.gba").read_bytes())
    import anim_molds     # esqueleto: moldes do jogo editados (data/anim/molds.json), na copia do baserom.gba
    anim_molds.apply(dst)
    if True:     # id de cada bot da lista nesta build (o Move/Skeleton Editor desenham o bot escolhido)
        # sem expansao binaria (nivel CORE: so os 120 do jogo) nao ha bots novos; o jogo base vem de data/core_bots.txt
        ids = ({bin_key(f): ORIG + k for k, f in enumerate(f for f in bin_files if int(f.stem[:3]) >= ORIG)}
               if a.from_binary else {})
        if a.navi:
            import decomp_navi
            for j, c in enumerate(clones):
                ids["navi/" + (c["json"].get("slug") or decomp_navi.navi_slug(c["name"]))] = ORIG + count + j
        # jogo base no mesmo mapa (pacote "core"): o projeto e agnostico, o conteudo deve chamar bot por nome
        for line in (ROOT / "data/core_bots.txt").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                i, name = line.split(" ", 1)
                ids[f"core/{name}"] = int(i)
        ids = dict(sorted(ids.items(), key=lambda kv: kv[1]))
        (dst / "bot_ids.json").write_text(json.dumps(ids, indent=1) + "\n", encoding="utf-8")
        # constantes por nome (como SPECIES_* no pret): BOT_METABEE (core), BOT_NAVI_TYRRELLBEETLE, BOT_TINPET_M/F
        hdr = ["// Gerado por tools/decomp_expand.py (bot_ids.json): id de cada bot desta build. Use os nomes, nao os",
               "// numeros: a ordem muda com a lista de bots.", "#ifndef GUARD_CONSTANTS_BOTS_GENERATED_H",
               "#define GUARD_CONSTANTS_BOTS_GENERATED_H", ""]
        for key, v in ids.items():
            pack, name = key.split("/", 1)
            sym = ("BOT_" if pack == "core" else f"BOT_{pack.upper()}_") + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
            hdr.append(f"#define {sym} {v}")
        hdr += [f"#define BOT_TINPET_M {n}", f"#define BOT_TINPET_F {n + 1}", "", "#endif", ""]
        (dst / "include/constants/bots_generated.h").write_text("\n".join(hdr), encoding="utf-8")
        if a.navi:        # o preview do toolkit copia as linhas de movimento como o build (decomp_navi)
            (dst / "pose_rows.json").write_text(json.dumps(navi_info["pose_rows"], indent=1) + "\n", encoding="utf-8")
        # encontros fixos dos bots novos (EXP_ENCOUNTER_EXTRA; data/encounters_new.json, tools/encounters_plan.py):
        # cada bot novo da lista ganha um grupo proprio (copia de um grupo do jogo, com o inimigo `record` trocado por
        # ele, byte alto do id em fillerB) na lista extra das areas indicadas
        plan_file = ROOT / "data/encounters_new.json"
        if plan_file.exists() and not a.no_encounter_extra:
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            src_rom = (Path(a.src) / "baserom.gba").read_bytes()
            recs, per_area, skipped, phases = [], {}, 0, []
            for e in plan["groups"]:
                if e["bot"] not in ids:
                    skipped += 1
                    continue
                bid = ids[e["bot"]]
                p = struct.unpack_from("<I", src_rom, SETUPS + 4 * e["from_group"])[0] - GBA_BASE
                rec = bytearray(src_rom[p:p + 0x28])
                k = e["record"]
                rec[4 + 12 * k:8 + 12 * k] = bytes([bid & 0xFF] * 4)
                rec[4 + 12 * k + 11] = bid >> 8
                for j, lv in enumerate(e.get("levels", [])[:rec[2]]):   # nivel da medalha de cada inimigo (+5)
                    rec[4 + 12 * j + 5] = lv
                for ar in e["areas"]:
                    per_area.setdefault(ar, []).append(len(recs))
                recs.append(rec)
                phases.append(e.get("min_phase", 0))    # so entra no sorteio a partir desta fase da historia
            if recs:
                first, lst = [0], []
                for ar in range(256):          # todo area_id u8 (areas novas do M4 tambem)
                    lst += per_area.get(ar, [])
                    first.append(len(lst))
                t = (dst / "asm/expansion.s").read_text()
                t += ("\n@ encontros fixos dos bots novos (EXP_ENCOUNTER_EXTRA, data/encounters_new.json)\n\t.align 2\n"
                      "\t.global gExtraEncounterSetups\ngExtraEncounterSetups:\n")
                t += "".join("\t.byte " + ", ".join(str(v) for v in r) + "\n" for r in recs)
                t += "\t.align 1\n\t.global gAreaExtraFirst\ngAreaExtraFirst:\n"
                t += "".join("\t.2byte " + ", ".join(str(v) for v in first[i:i + 16]) + "\n" for i in range(0, len(first), 16))
                t += "\t.global gAreaExtraList\ngAreaExtraList:\n"
                t += "".join("\t.2byte " + ", ".join(str(v) for v in lst[i:i + 16]) + "\n" for i in range(0, len(lst), 16))
                t += f"\t.global gExtraEncounterPercent\ngExtraEncounterPercent:\n\t.byte {plan.get('percent', 40)}\n"
                t += "\t.global gExtraEncounterMinPhase\ngExtraEncounterMinPhase:\n"
                t += "".join("\t.byte " + ", ".join(str(v) for v in phases[i:i + 32]) + "\n" for i in range(0, len(phases), 32))
                (dst / "asm/expansion.s").write_text(t)
                a.encounter_extra = True
                print(f"  encontros fixos: {len(recs)} bots novos em {len(per_area)} areas ({plan.get('percent', 40)}% de "
                      f"chance de extra){f'; {skipped} fora da lista' if skipped else ''}")
        # bots novos nos encontros aleatorios (EXP_ENCOUNTER_MIX): nos grupos de data/encounter_mix.json (so encontro
        # aleatorio de mapa, nenhum evento) entra um inimigo curinga (fillerB 0xFF): menos de 3 inimigos = mais um,
        # copia do 1o (medalha, nivel, rotacao); 3 = o ultimo vira curinga. A cada luta o jogo sorteia um bot novo.
        mix_file = ROOT / "data/encounter_mix.json"
        wild = sorted(v for k, v in ids.items() if not k.startswith("core/"))
        if mix_file.exists() and wild and a.encounter_wildcard:
            groups = json.loads(mix_file.read_text(encoding="utf-8"))["groups"]
            rom = bytearray((dst / "baserom.gba").read_bytes())
            added = replaced = 0
            for g in groups:
                p = struct.unpack_from("<I", rom, SETUPS + 4 * g)[0] - GBA_BASE
                c = rom[p + 2]
                if c < 3:
                    rom[p + 4 + 12 * c:p + 16 + 12 * c] = rom[p + 4:p + 16]
                    rom[p + 4 + 12 * c + 11] = 0xFF
                    rom[p + 2] = c + 1
                    added += 1
                else:
                    rom[p + 4 + 12 * 2 + 11] = 0xFF
                    replaced += 1
            (dst / "baserom.gba").write_bytes(bytes(rom))
            t = (dst / "asm/expansion.s").read_text()
            t += ("\n@ bots que o inimigo curinga dos encontros aleatorios pode ser (EXP_ENCOUNTER_MIX)\n\t.align 2\n"
                  f"\t.global gEncounterWildCount\ngEncounterWildCount:\n\t.2byte {len(wild)}\n"
                  "\t.align 1\n\t.global gEncounterWildBots\ngEncounterWildBots:\n")
            t += "".join("\t.2byte " + ", ".join(str(v) for v in wild[i:i + 16]) + "\n" for i in range(0, len(wild), 16))
            (dst / "asm/expansion.s").write_text(t)
            a.encounter_mix = True
            print(f"  encontros: {len(groups)} grupos com curinga ({added} com inimigo a mais, {replaced} trocados); "
                  f"{len(wild)} bots novos sorteaveis")
        # espaco reservado para o texto editado no WPF (perfil de texto: TextDumpOffset, tools/decomp_layout.py). Zeros
        # (nao 0xFF): o alocador do toolkit (FreeSpaceAllocator) so usa o 0xFF do fim da ROM, entao nao pisa aqui.
        t = (dst / "asm/expansion.s").read_text()
        if "gToolkitTextSpace" not in t:
            t += ("\n@ texto editado no WPF (Medabots-Romhacking-Toolkit, MedabotsTextPatcher)\n\t.align 4\n"
                  "\t.global gToolkitTextSpace\ngToolkitTextSpace:\n\t.space 0x10000\n")
            (dst / "asm/expansion.s").write_text(t)
        # moldes proprios de um bot (data/anim/molds.json custom/use; EXP_CUSTOM_MOLDS): registros novos e o campo
        # custom nas entradas das linhas de peca desses bots
        mc = anim_molds.load()
        # pastas de arte: pedaco desenhado noutro tamanho = molde proprio (anim_molds.art_customs)
        art_dirs = {}
        for f in bin_files:
            if int(f.stem[:3]) >= ORIG and bin_key(f) in ids:
                art = json.loads(f.read_text(encoding="utf-8")).get("art")
                if art:
                    art_dirs[bin_key(f)] = ROOT / art
        for line in anim_molds.art_customs(art_dirs, (dst / "baserom.gba").read_bytes(), mc["custom"], mc["use"]):
            print("  arte:", line)
        for f in (navi_info.get("form_rows", ()) if a.navi else ()):   # perna da forma de bot proprio
            if f.get("own_bot") is not None:
                if f["custom"] in mc["custom"]:
                    raise SystemExit(f"molde proprio {f['custom']} da forma ja usado em molds.json")
                mc["custom"][f["custom"]] = {"base": ("core", f["node"])}
                if f.get("picture"):
                    mc["custom"][f["custom"]]["picture"] = str(ROOT / f["picture"])
                print(f"  forma de {f['own_bot']}: perna = molde {f['node']} com o molde proprio {f['custom']}"
                      + (f" ({f['picture']})" if f.get("picture") else ""))
        if mc["custom"] or mc["use"]:
            if not a.navi:
                raise SystemExit("moldes proprios precisam de EXP_NAVI_SPRITES: ponha ao menos um bot do Navi na "
                                 "lista (pendente: tabelas do Navi vazias numa build sem Navi)")
            text = (dst / "asm/expansion.s").read_text()
            base = (dst / "baserom.gba").read_bytes()
            text = anim_molds.patch_node_tables(text, mc["use"], ids, base)
            text += anim_molds.custom_asm(mc["custom"], base, navi_info.get("records"), lambda o: incbin(o, 4))
            (dst / "asm/expansion.s").write_text(text)
            a.custom_molds = True
            print(f"  moldes proprios: {len(mc['custom'])}; bots que usam: {sorted(mc['use'])}")
            (dst / "custom_molds.json").write_text(json.dumps(
                {"custom": {str(c): dict(f, base=f"{f['base'][0]}:{f['base'][1]}") for c, f in mc["custom"].items()},
                 "use": {b: {p: {str(n): c for n, c in ns.items()} for p, ns in ps.items()}
                         for b, ps in mc["use"].items()}}, indent=1) + "\n", encoding="utf-8")
    ld =(dst / "ld_script.ld").read_text()
    ld = ld.replace("        build/data/free_087F3270.o(.rodata);\n",
                    "        build/data/free_087F3270.o(.rodata);\n        build/asm/expansion.o(.rodata);\n")
    (dst / "ld_script.ld").write_text(ld)
    if n > 252:
        # id de 16 bits: TeamSlot/BattleBot/GameWork crescem; vao para a EWRAM livre (0x0202A000-0x0202DFFF), com os
        # apelidos que apontam para dentro do GameWork (textBuf, runningSpriteSlot: +4 depois dos shown* de 16 bits)
        sy = (dst / "symbols.ld").read_text()
        for name, old, new in [("gGameWork", "0x03000440", "0x0202A000"), ("gTextArgBuffer", "0x030004DE", "0x0202A0A2"),
                               ("gEffectSpriteSlot", "0x0300056F", "0x0202A133"), ("gTeamSlots", "0x030017A0", "0x0202A200"),
                               ("gBattleBots", "0x03000590", "0x0202A400")]:
            lines = sy.split("\n")
            hit = [i for i, l in enumerate(lines) if re.match(rf"\s*{name}\s*=", l)]
            assert len(hit) == 1 and old.lower() in lines[hit[0]].lower(), (name, hit)
            lines[hit[0]] = re.sub(r"0x[0-9A-Fa-f]+", new, lines[hit[0]], count=1)
            sy = "\n".join(lines)
        (dst / "symbols.ld").write_text(sy)
        # dado cru que aponta para dentro do GameWork antigo: gTextBufferPtrs (USA 0xABBFC), os 4 buffers de texto
        # 0x030004DE + 0x14*n (dinheiro/numeros/nomes nas falas, copy_string_to_text_buffer). Sem isto o texto ia para
        # a IWRAM antiga e a fala lia o buffer novo (erro ao receber o dinheiro da mae no cap. 0). Varredura dos
        # incbin por ponteiros para GameWork/BattleBots/TeamSlots antigos: so esta tabela. Varredura da ROM montada
        # inteira (2026-11-21, pc/research/DECOMP_C.md): nenhum outro ponteiro; o unico tamanho fixo era o memzero
        # 0x13C do GameWork em field_update.c (corrigido no C com sizeof).
        rp = dst / "baserom.gba"
        rom2 = bytearray(rp.read_bytes())
        for k in range(4):
            old_ptr = struct.unpack_from("<I", rom2, 0xABBFC + 4 * k)[0]
            assert old_ptr == 0x030004DE + 0x14 * k, hex(old_ptr)
            struct.pack_into("<I", rom2, 0xABBFC + 4 * k, 0x0202A0A2 + 0x14 * k)
        rp.write_bytes(bytes(rom2))
        print("  gTextBufferPtrs -> 0x0202A0A2 (buffers de texto no GameWork novo)")
    # 3. inventario na EWRAM livre
    sy = (dst / "symbols.ld").read_text()
    sy = sy.replace("gMedapartInventory  = 0x03004C40;", f"gMedapartInventory  = 0x{INV_NEW:08X};")
    (dst / "symbols.ld").write_text(sy)
    # 4. NUM_MEDABOTS e teste
    mk = (dst / "Makefile").read_text()
    flags = (f"-DNUM_MEDABOTS={n}" + (" -DEXPANSION_GIVE_NEW" if a.give_new else "") +
             expansion_flags(a))
    mk = mk.replace("CPPFLAGS := -nostdinc", f"CPPFLAGS := {flags} -nostdinc")
    # WPF (passo 4): a cada build, <rom>.layout.json com os enderecos das tabelas pelo .map (tools/decomp_layout.py)
    tool = (ROOT / "tools/decomp_layout.py").as_posix()
    assert mk.count("all: $(ROM)\n") == 1
    mk = mk.replace("all: $(ROM)\n", "all: $(ROM) medabots_rokusho.layout.json\n\n"
                    "medabots_rokusho.layout.json: $(ROM)\n" + chr(9) + f"-python3 {tool} .\n")
    (dst / "Makefile").write_text(mk)
    if a.give_new:
        # Teste: ao abrir o menu de campo (B) pela 1a vez, ja depois da abertura, o jogo recebe 1 de cada peca dos
        # bots novos e monta o slot 0 do time pelo caminho da historia (Tinpet, Medalha, bot inicial), trocando
        # as pecas para o bot 120. O menu fica liberado mesmo antes do Medawatch da historia.
        w = dst / "src/field/field_walk.c"
        wt = w.read_text()
        old = "if (gFieldWork.medawatch_enabled) {"
        assert wt.count(old) == 1
        give = ("if (1) {   // EXPANSION_GIVE_NEW: menu sempre (tools/decomp_expand.py --give-new)\n"
                "                            if (gTeamSlots[0].state == 0) {\n"
                "                                u32 k, b;\n"
                f"                                for (b = 120; b < {real}; b++)\n"
                "                                    for (k = 0; k < 4; k++)\n"
                "                                        gMedapartInventory[k * MEDAPART_INV_STRIDE + b * 2] = 1;\n"
                "                                team_add_tinpet(0);\n"
                "                                medal_add_by_id(MEDAL_KUWAGATA);\n"
                "                                give_starter_medabot();\n"
                "                                gTeamSlots[0].head = 120;\n"
                "                                gTeamSlots[0].rightArm = 120;\n"
                "                                gTeamSlots[0].leftArm = 120;\n"
                "                                gTeamSlots[0].legs = 120;\n"
                "                                for (k = 0; k < 4; k++) {\n"
                "                                    gMedapartInventory[k * MEDAPART_INV_STRIDE + 0x2A * 2 + 1] = 0;\n"
                "                                    gMedapartInventory[k * MEDAPART_INV_STRIDE + 120 * 2 + 1] = 1;\n"
                "                                }\n"
                "                            }")
        wt = wt.replace(old, give)
        # teste: R no campo abre a loja 0 (switch_game_mode(3, loja), como o script Open_Shop)
        bkey = "} else if (KEYS_LO(gNewKeys) & B_BUTTON) {"
        assert wt.count(bkey) == 1
        wt = wt.replace(bkey, "} else if (KEYS_HI(gNewKeys) & R_BUTTON_HI) {   // EXPANSION_GIVE_NEW: loja 0\n"
                              "                        save_script_sprites();\n"
                              "                        switch_game_mode(3, 0);\n"
                              "                        done = 1;\n"
                              "                    " + bkey)
        wt = wt.replace('#include "global.h"\n', '#include "global.h"\n#include "constants/medals.h"\n', 1)
        w.write_text(wt)
        if a.always_encounter:   # teste: todo passo no campo vira encontro aleatorio (caminho real da luta)
            pw = dst / "src/field/player_walk.c"
            pt = pw.read_text()
            assert pt.count("check_random_encounter()) {") == 1
            pw.write_text(pt.replace("check_random_encounter()) {", "(check_random_encounter() || 1)) {"))
    print(f"arvore em {dst}: {n} Medabots ({len(bots)} novos: {', '.join(b['name'] for b in bots)})")


if __name__ == "__main__":
    main()
