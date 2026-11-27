"""acha_fala.py - Acha uma cena pelo texto da fala: que fala é (banco/id), que roteiro a mostra e onde ele é disparado.

Uso: python tools/acha_fala.py "Phantom Renegade"          procura nas falas (sem diferenciar maiúsculas)
     python tools/acha_fala.py --fala 0 79                 mostra uma fala e quem a usa
     python tools/acha_fala.py --roteiro 144               quem dispara o roteiro 144 (NPC/gatilho, warp, outro roteiro)

Lê as falas do jogo da build mais nova (build/scratch/decomp_hpNN/base, endereço da gTextBankTables pelo .map) e as
falas do projeto de data/story/text/bank_NN.json. Os roteiros vêm de data/events/*.evt e os gatilhos de
data/maps/area_NNN/npcs.json e warps.json. Não altera nada.

Na fala: | = nova linha, || = nova caixa, <FB 00 0D 02> = retrato (quem fala), <NOME:0> = nome guardado (jogador etc.).
"""
import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from medarom import ENCODING  # noqa: E402

EVENTS = ROOT / "data/events"
MAPS = ROOT / "data/maps"
TEXT = ROOT / "data/story/text"
CATALOG = __import__("paths").TOOLKIT / "src/Medabots.Rom/medabots.catalog.json"


def newest_build():
    hps = sorted((int(m.group(1)), d) for d in (ROOT / "build/scratch").glob("decomp_hp*")
                 if (m := re.fullmatch(r"decomp_hp(\d+)", d.name)) and (d / "base/medabots_rokusho.gba").exists())
    if not hps:
        raise SystemExit("nenhuma build em build/scratch/decomp_hpNN/base (rode tools/decomp_build.py)")
    return hps[-1][1] / "base"


def decode(b):
    s, k = "", 0
    while k < len(b):
        c = b[k]
        if c == 0xFB:
            s += "<%s>" % b[k:k + 4].hex(" ").upper()
            k += 4
            continue
        if c == 0xF9:                      # nome guardado (jogador, medalha...): F9 + número
            s += "<NOME:%d>" % b[k + 1]
            k += 2
            continue
        if c == 0xFF:
            break
        s += "|" if c == 0xFD else "||" if c == 0xFC else (ENCODING[c] if c < len(ENCODING) else "<%02X>" % c)
        k += 1
    return s


def game_messages():
    base = newest_build()
    rom = (base / "medabots_rokusho.gba").read_bytes()
    mapf = next(base.glob("*.map"))
    m = re.search(r"0x([0-9a-f]+)\s+gTextBankTables\b", mapf.read_text(encoding="utf-8", errors="replace"))
    table = int(m.group(1), 16) - 0x08000000
    msgs = {}
    for bank in range(16):
        tab = struct.unpack_from("<I", rom, table + 4 * bank)[0] - 0x08000000
        nxt = struct.unpack_from("<I", rom, table + 4 * (bank + 1))[0] - 0x08000000 if bank < 15 else None
        i = 0
        while True:
            at = tab + 4 * i
            if nxt is not None and at >= nxt:
                break
            p = struct.unpack_from("<I", rom, at)[0]
            if not 0x08000000 <= p < 0x08000000 + len(rom) or (nxt is None and i > 600):
                break
            p -= 0x08000000
            end = rom.index(b"\xFF", p)
            while rom[end - 3] == 0xFB if end >= 3 else False:  # FF dentro de um retrato: segue
                end = rom.index(b"\xFF", end + 1)
            msgs[(bank, i)] = decode(rom[p:end + 2])
            i += 1
    return msgs, base.parent.name


def project_messages():
    out = {}
    for f in sorted(TEXT.glob("bank_*.json")) if TEXT.exists() else []:
        d = json.loads(f.read_text(encoding="utf-8"))
        for i, s in enumerate(d["messages"]):
            out[(d["bank"], i)] = s + "   [projeto: " + f.relative_to(ROOT).as_posix() + "]"
    return out


def area_names():
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8"))["maps"]
    except (OSError, KeyError, ValueError):
        return []


def scripts_showing(bank, mid):
    pat = re.compile(rf"\bbank={bank}, id={mid}\b")
    for f in sorted(EVENTS.glob("*.evt")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                yield int(f.stem), n, line.strip()


def callers(script_id):
    names = area_names()
    out = []
    for a in sorted(MAPS.glob("area_*")):
        aid = int(a.name[5:])
        nm = names[aid] if aid < len(names) else "?"
        npcs = a / "npcs.json"
        if npcs.exists():
            for npc in json.loads(npcs.read_text(encoding="utf-8")).get("npcs", []):
                if npc.get("event") == script_id:
                    kind = "gatilho invisível no chão" if npc.get("anim") == 255 else f"NPC (sprite {npc.get('anim')})"
                    out.append(f"área {aid:03d} {nm}: {kind} em ({npc['x']},{npc['y']}), kind {npc.get('kind')}, "
                               f"fases {npc.get('phases')}  [{npcs.relative_to(ROOT).as_posix()}]")
    pat = re.compile(rf"\b(Goto_Event event|Add_Event_Permanently event_id|Set_Event_Variable event_id)={script_id}\b")
    for f in sorted(EVENTS.glob("*.evt")):
        if int(f.stem) == script_id:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line):
                out.append(f"roteiro {int(f.stem)} linha {n}: {line.strip()}")
    return out


def warps_in(script_id):
    names = area_names()
    text = (EVENTS / f"{script_id:04d}.evt").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"Warp_[AB] map_id=(\d+).*?x=(\d+), y=(\d+)", text):
        aid = int(m.group(1))
        out.append(f"teleporta para a área {aid:03d} {names[aid] if aid < len(names) else '?'} ({m.group(2)},{m.group(3)})")
    return out


def report_message(key, text):
    print(f"\nfala banco {key[0]}, id {key[1]}:\n  {text}")
    for sid, n, line in scripts_showing(*key):
        print(f"  mostrada no roteiro {sid} (data/events/{sid:04d}.evt linha {n})")
        for c in callers(sid):
            print(f"    disparado por: {c}")
        for w in warps_in(sid):
            print(f"    {w}")


def main():
    ap = argparse.ArgumentParser(description="acha cena pelo texto da fala")
    ap.add_argument("texto", nargs="?")
    ap.add_argument("--fala", nargs=2, type=int, metavar=("BANCO", "ID"))
    ap.add_argument("--roteiro", type=int)
    a = ap.parse_args()
    if a.roteiro is not None:
        print(f"roteiro {a.roteiro} (data/events/{a.roteiro:04d}.evt):")
        for c in callers(a.roteiro) or ["(ninguém dispara: só roda se outro roteiro pular para ele)"]:
            print("  disparado por:", c)
        for w in warps_in(a.roteiro):
            print("  " + w)
        return
    msgs, build = game_messages()
    msgs.update(project_messages())
    print(f"(falas do jogo lidas de {build})")
    if a.fala:
        key = tuple(a.fala)
        if key not in msgs:
            raise SystemExit(f"não há fala banco {key[0]} id {key[1]}")
        report_message(key, msgs[key])
        return
    if not a.texto:
        ap.error("diga o texto, --fala BANCO ID ou --roteiro ID")
    hits = [(k, v) for k, v in sorted(msgs.items()) if a.texto.lower() in v.lower()]
    print(f"{len(hits)} fala(s) com {a.texto!r}")
    for k, v in hits[:30]:
        report_message(k, v)
    if len(hits) > 30:
        print(f"\n... e mais {len(hits) - 30}; refine o texto")


if __name__ == "__main__":
    main()
