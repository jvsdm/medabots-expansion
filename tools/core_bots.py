"""core_bots.py - Gera data/bots/000..119 (os 120 Medabots do jogo base) da Rokusho USA de quem usa o projeto.

O tools/build.py monta a expansao com os bots 0..N-1 e precisa dos 120 do jogo como JSON (atributos e nomes das
pecas); esses bots continuam com as tabelas do proprio jogo na descompilacao, entao os JSON so completam a lista.
Os nomes de arquivo (NNN_nome.json) vem de data/core_bots.txt. Os bots 120.. (Shingata, arte propria) sao do projeto.

Uso: python tools/core_bots.py [--force]
"""
import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MEDABOTS_VERSION", "rokusho_us")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from medarom import (Rom, BOT_COUNT, PART_KINDS, PART_SIZE, PART_STATS, BOT_NAMES,  # noqa: E402
                     PART_NAMES, PALETTE_FAMILY, part_fields)

OUT = ROOT / "data/bots"


def names():
    out = {}
    for line in (ROOT / "data/core_bots.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            i, n = line.split(" ", 1)
            out[int(i)] = n
    return out


def generate(force=False):
    rom = Rom()
    slugs = names()
    OUT.mkdir(parents=True, exist_ok=True)
    wrote = 0
    for bot in range(BOT_COUNT):
        path = OUT / f"{bot:03d}_{slugs[bot]}.json"
        if path.exists() and not force:
            continue
        parts = {}
        for k, kind in enumerate(PART_KINDS):
            pid = bot * 4 + k
            raw = bytes(rom.data[PART_STATS + pid * PART_SIZE:PART_STATS + (pid + 1) * PART_SIZE])
            parts[kind] = {"part_id": pid, "name": rom.text(rom.ptr_at(PART_NAMES, pid)),
                           "stats": dict(zip(part_fields(kind), raw))}
        doc = {"bot_id": bot, "name": rom.text(rom.ptr_at(BOT_NAMES, bot)),
               "palette_family": rom.data[PALETTE_FAMILY + bot], "parts": parts}
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        wrote += 1
    return wrote


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    print(f"data/bots: {generate(a.force)} bots do jogo gerados da Rokusho USA")


if __name__ == "__main__":
    main()
