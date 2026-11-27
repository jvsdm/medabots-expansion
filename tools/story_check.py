"""story_check.py - Checagem da storyline (M7 do pc/research/MAPAS_EVENTOS_PLANO.md).

Le data/maps, data/events e data/story e acha o que quebraria o jogo ou ficou solto:
  erros   warp (warps.json ou Warp_A/Warp_B de roteiro) para area que nao existe; NPC ou Goto_Event para roteiro que nao
          existe; fala (Show_Message_A/B) com banco ou id fora das tabelas; roteiro que nao monta
  avisos  roteiro novo (id >= 2288) sem NPC nem Goto_Event chamando; area nova (id >= 192) sem warp chegando;
          evento novo removido/readicionado (flag) que nenhum NPC usa
Nomes opcionais em data/story/flags.json: {"events": {"2288": "nome"}, "phases": {"0": "nome"}, "areas": {"192": "..."}}.

Uso: python tools/story_check.py [--quiet]     codigo de saida 1 se houver erro (tools/decomp_build.py para a build)
"""
import argparse
import json
import struct
from pathlib import Path

from events_text import GOTO, decode, load_ops, script_bytes, parse

ROOT = Path(__file__).resolve().parents[1]
import paths  # noqa: E402
DEC = paths.DECOMP
GAME_AREAS, GAME_EVENTS = 192, 2288
TEXT_TABLE_AT, GAME_BANKS = 0x47E45C, 16


def game_text_sizes():
    """Quantas falas tem cada banco do jogo (tabela de ponteiros ate o primeiro 0) e a tabela gTextTable (bank < 0)."""
    rom = (DEC / "baserom.gba").read_bytes()
    sizes = []
    for b in range(GAME_BANKS):
        t = struct.unpack_from("<I", rom, TEXT_TABLE_AT + 4 * b)[0] - 0x08000000
        n = 0
        while struct.unpack_from("<I", rom, t + 4 * n)[0] != 0 and n < 0x1000:
            n += 1
        sizes.append(n)
    return sizes


def check(maps=ROOT / "data/maps", events=ROOT / "data/events", story=ROOT / "data/story"):
    errs, warns = [], []
    names = json.loads((story / "flags.json").read_text(encoding="utf-8")) if (story / "flags.json").exists() else {}
    ev_name = lambda i: f"roteiro {i}" + (f" ({names['events'][str(i)]})" if str(i) in names.get("events", {}) else "")
    nareas = 0
    while (maps / f"area_{nareas:03d}/area.json").exists():
        nareas += 1
    nev = 0
    while (events / f"{nev:04d}.json").exists():
        nev += 1
    text = game_text_sizes()
    tdir = story / "text"
    if tdir.exists():
        for f in sorted(tdir.glob("bank_*.json")):
            text.append(len(json.loads(f.read_text(encoding="utf-8"))["messages"]))
    # areas: warps e NPCs
    called = {}
    arrive = set()
    for i in range(nareas):
        a = json.loads((maps / f"area_{i:03d}/area.json").read_text(encoding="utf-8"))
        for w in json.loads((maps / a["warps"] / "warps.json").read_text(encoding="utf-8"))["warps"]:
            if w["to_area"] >= nareas:
                errs.append(f"area {i}: warp em ({w['x']},{w['y']}) para a area {w['to_area']}, que nao existe")
            arrive.add(w["to_area"])
        for n in json.loads((maps / a["npcs"] / "npcs.json").read_text(encoding="utf-8"))["npcs"]:
            called.setdefault(n["event"], []).append(f"NPC da area {i}")
            if n["event"] >= nev and n["kind"] in (0, 4, 6, 8):
                errs.append(f"area {i}: NPC em ({n['x']},{n['y']}) chama o roteiro {n['event']}, que nao existe")
    # roteiros
    ops, by_name = load_ops(events)
    flags_touched = set()
    for i in range(nev):
        d = json.loads((events / f"{i:04d}.json").read_text(encoding="utf-8"))
        if "shared_with" in d:
            continue
        try:
            data = script_bytes(events, d, ops, by_name)
        except SystemExit as e:
            errs.append(f"{ev_name(i)}: nao monta ({e})")
            continue
        for off, (sz, op, vals, tgt) in sorted(parse(data, ops).items()):
            o = ops.get(op, {})
            nm = o.get("name", "")
            if op == GOTO:
                called.setdefault(vals[0], []).append(f"Goto_Event do {i}")
                if vals[0] >= nev:
                    errs.append(f"{ev_name(i)}: Goto_Event para o roteiro {vals[0]}, que nao existe")
            elif nm in ("Warp_A", "Warp_B") and vals[0] >= nareas:
                errs.append(f"{ev_name(i)}: {nm} para a area {vals[0]}, que nao existe")
            elif nm in ("Warp_A", "Warp_B"):
                arrive.add(vals[0])
            elif nm in ("Show_Message_A", "Show_Message_B"):
                bank, mid = vals[0] - 2, vals[1]
                size = text[bank] if 0 <= bank < len(text) else None
                if bank >= 0 and (size is None or mid >= size):
                    errs.append(f"{ev_name(i)}: {nm} bank={bank}, id={mid}: fala nao existe"
                                + ("" if size is None else f" (o banco tem {size})"))
            elif nm in ("Add_Event_Permanently", "Remove_Event_Permanently", "Remove_Event_Now"):
                flags_touched.add(vals[0])
                if vals[0] >= 3000:       # o jogo ja tem um (roteiro 157, 29908): aviso nos do jogo, erro nos novos
                    (errs if i >= GAME_EVENTS else warns).append(
                        f"{ev_name(i)}: {nm} {vals[0]}: flag so existe ate o id 2999"
                        + (" (ja no jogo original)" if i < GAME_EVENTS else ""))
    for i in range(GAME_EVENTS, nev):
        if i not in called:
            warns.append(f"{ev_name(i)}: nenhum NPC nem Goto_Event chama")
    for i in range(GAME_AREAS, nareas):
        if i not in arrive:
            warns.append(f"area {i}: nenhum warp chega nela")
    for f in sorted(flags_touched):
        if GAME_EVENTS <= f < 3000 and f not in called:
            warns.append(f"flag do evento {f} mexida por roteiro, mas nenhum NPC usa esse evento")
    return errs, warns, {"areas": nareas, "roteiros": nev, "bancos de fala": len(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="so erros e avisos")
    a = ap.parse_args()
    errs, warns, stats = check()
    if not a.quiet:
        print("storyline: " + ", ".join(f"{v} {k}" for k, v in stats.items()))
    for e in errs:
        print("ERRO:", e)
    for w in warns:
        print("aviso:", w)
    if not a.quiet or errs or warns:
        print(f"{len(errs)} erros, {len(warns)} avisos")
    raise SystemExit(1 if errs else 0)


if __name__ == "__main__":
    main()
