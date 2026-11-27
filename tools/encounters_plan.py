"""encounters_plan.py - Encontros fixos dos bots novos (Shingata, Navi...), distribuidos pelas areas por semelhanca.

Cada bot novo ganha UM grupo de luta proprio, fixo (o bot sempre inteiro, da para farmar as 4 pecas): copia de um grupo
de encontro aleatorio do jogo onde aparece o bot "parecido" (o base), com esse inimigo trocado pelo bot novo. O grupo
entra na lista extra das areas onde o base aparece (EXP_ENCOUNTER_EXTRA: num encontro aleatorio, PERCENT% de chance de
a luta vir da lista extra da area). Mensagem, medalha, nivel e companhia vem do grupo do jogo: a dificuldade e a da area.

Base de cada bot novo:
  - Navi: o bot do jogo em que ele ja e baseado (graphics_source.clone_for_missing_graphics), se esse bot aparece em
    encontro aleatorio; senao, como os outros;
  - os outros: o bot do jogo (entre os 63 que aparecem em encontro aleatorio) mais parecido: mesmo tipo de perna (+3),
    mesma medalha (medal_compat das pernas, +2), mesma tecnica na cabeca / braco dir. / braco esq. (+1 cada).
Areas: ate MAX_AREAS das areas onde o base aparece, preferindo a vaga de maior peso (40/30/20/10%) e as areas com menos
extras; no maximo AREA_CAP bots por area (cheia: vai para o proximo bot do jogo mais parecido), para dar para farmar. Saida: data/encounters_new.json (chaves dos bots, nao ids: os ids mudam com a lista). Editavel.

Uso: python tools/encounters_plan.py [--bot-ids build/scratch/decomp_hpNN/bot_ids.json]
"""
import argparse
import glob
import json
import struct
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASEROM = ROOT / "build/scratch/decomp_rok/baserom.gba"
AREAS, NAREAS = 0x3BF090, 192          # gAreaRandomEncounters (USA): 192 areas x 4 grupos (40/30/20/10%)
SETUPS, NSETUPS = 0x3C1A00, 246        # gEncounterSetups (USA)
WEIGHTS = (40, 30, 20, 10)
PERCENT = 40
MAX_AREAS = 2
AREA_CAP = 8           # no maximo 8 bots extras por area: com 40% de chance de extra, cada um sai em ~5% das lutas
SLOTS = ("head", "right_arm", "left_arm", "legs")


def group_records(rom, g):
    p = struct.unpack_from("<I", rom, SETUPS + 4 * g)[0] - 0x08000000
    return p, [rom[p + 4 + 12 * k] for k in range(rom[p + 2])]


def stats(j):
    s = {sl: j["parts"][sl]["stats"] for sl in SLOTS}
    return (s["legs"].get("leg_type"), s["legs"].get("medal_compat"),
            s["head"].get("technique"), s["right_arm"].get("technique"), s["left_arm"].get("technique"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot-ids", help="bot_ids.json de uma build (default: a decomp_hp mais nova)")
    a = ap.parse_args()
    ids_file = Path(a.bot_ids) if a.bot_ids else max(ROOT.glob("build/scratch/decomp_hp*/bot_ids.json"),
                                                     key=lambda f: f.stat().st_mtime)
    ids = json.loads(ids_file.read_text(encoding="utf-8"))
    rom = BASEROM.read_bytes()

    # onde cada bot do jogo aparece em encontro aleatorio: (peso, area, grupo, registro)
    where = defaultdict(list)
    for area in range(NAREAS):
        for slot, g in enumerate(rom[AREAS + 4 * area:AREAS + 4 * area + 4]):
            if g:
                for k, b in enumerate(group_records(rom, g)[1]):
                    where[b].append((WEIGHTS[slot], area, g, k))
    core = {}
    for f in sorted(glob.glob(str(ROOT / "data/bots/*.json"))):
        bid = int(Path(f).stem[:3])
        if bid < 120 and bid in where:
            core[bid] = stats(json.loads(Path(f).read_text(encoding="utf-8")))

    new = []   # (chave, json)
    for key in sorted(ids, key=ids.get):
        pack, name = key.split("/", 1)
        if pack == "core":
            continue
        if pack == "navi":
            path = next(iter(glob.glob(str(ROOT / f"data/navi/bots/*_{name}.json"))), None)
        else:
            path = next(iter(glob.glob(str(ROOT / f"data/bots/*_{name}.json"))), None)
        if path:
            new.append((key, json.loads(Path(path).read_text(encoding="utf-8"))))

    load = defaultdict(int)
    out = []
    for key, j in new:
        clone = (j.get("graphics_source") or {}).get("clone_for_missing_graphics")
        st = stats(j)

        def score(b):
            c = core[b]
            return (3 * (c[0] == st[0]) + 2 * (c[1] == st[1]) + (c[2] == st[2]) + (c[3] == st[3]) + (c[4] == st[4]),
                    -len(where[b]), -b)
        bases = sorted(core, key=score, reverse=True)
        if key.startswith("navi/") and clone in core:
            bases.remove(clone)
            bases.insert(0, clone)
        for base in bases:
            spots = sorted((w for w in where[base] if load[w[1]] < AREA_CAP), key=lambda w: (-w[0], load[w[1]], w[1]))
            if spots:
                break
        why = ("Navi: bot base do desenho" if key.startswith("navi/") and base == clone
               else f"semelhanca {score(base)[0]}/8 (perna, medalha, tecnicas)")
        areas, seen = [], set()
        for w, area, g, k in spots:
            if area not in seen:
                seen.add(area)
                areas.append(area)
            if len(areas) == MAX_AREAS:
                break
        w, area, g, k = spots[0]
        for ar in areas:
            load[ar] += 1
        out.append({"bot": key, "base": base, "why": why, "from_group": g, "record": k, "areas": areas})
    doc = {"_doc": __doc__.strip().split("\n\n")[0] + " Gerado por tools/encounters_plan.py; pode editar a mao "
           "(bot, from_group = grupo do jogo copiado, record = inimigo trocado, areas).",
           "percent": PERCENT, "groups": out}
    dst = ROOT / "data/encounters_new.json"
    if dst.exists():    # entradas feitas a mao ("manual": true, ex.: bots do Core no pos-jogo) ficam
        out += [e for e in json.loads(dst.read_text(encoding="utf-8"))["groups"] if e.get("manual")]
    doc["_doc"] += (" Campos opcionais: levels = nivel da medalha de cada inimigo, min_phase = fase da historia a partir "
                    "da qual o grupo entra no sorteio, manual = o planejador mantem a entrada.")
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    per_area = defaultdict(int)
    for e in out:
        for ar in e["areas"]:
            per_area[ar] += 1
    print(f"{dst}: {len(out)} bots novos em {len(per_area)} areas (max {max(per_area.values())} por area)")


if __name__ == "__main__":
    main()
