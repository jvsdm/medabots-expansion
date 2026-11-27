"""anim_seq.py - Roteiros de golpe (sequencias de batalha) em JSON: data/anim/seq/NNN.json, fonte da verdade do gerador.

Formato do jogo (src/battle/battle_sequence.c): gBattleSeqScripts[animSkill] aponta para uma lista de s16. Cada
comando = opcode (0x00-0x3A, gBattleSeqCommands) + gBattleSeqOperandCounts[opcode] operandos. animSkill = tecnica
da peca (data[1], 0..59) ou Medaforce + 0x50 (80..131).
Rotulos: valores 0x80-0xFF (viram negativos no cast s8 de battle_sequence_run_command). goto/branch procuram, de
comando em comando, a entrada igual ao operando e seguem dali. Pular um rotulo avanca 1 + OperandCounts[rotulo]:
so os rotulos com contagem 0 servem (SAFE_LABELS); 0x9C, 0xA2... pulariam dezenas de entradas.

JSON (um por roteiro; um comando por linha):
  {"seq": 2, "name": "RIFLE", "ops": [["actor_pose", 0, 0, 1, 2, 0, 2, 1], ["label", 133], ["end"]]}
  {"seq": 23, "name": "...", "same_as": 21}   (o jogo aponta os dois para o mesmo roteiro)
Comandos: nomes de battle_seq_cmd_* sem o prefixo (OPS abaixo). Sem nome conhecido: ["op", N, ...].

Uso: python tools/anim_seq.py --export   (le a baserom original; nao sobrescreve sem --force)
     python tools/anim_seq.py --check    (monta os roteiros dos JSON e compara com a baserom: devem ser iguais)
"""
import argparse
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEQ_DIR = ROOT / "data/anim/seq"
GBA = 0x08000000
SEQ_TABLE, SEQ_COUNT_TABLE, SEQ_ORIG = 0x3CDFE4, 0x3CE1F4, 132    # Rokusho USA (decomp_rok baserom)

# (nome, operandos) por opcode: gBattleSeqCommands + gBattleSeqOperandCounts da ROM original
OPS = [("nop", 0), ("end", 0), ("goto", 1), ("branch", 4), ("test_missed", 0), ("test_reaction", 0),
       ("test_nullified", 0), ("test_absorbed", 0), ("actor_pose", 7), ("yield", 0), ("target_pose", 7),
       ("actor_dash", 1), ("wait_pose", 1), ("bg_effect", 8), ("wait_frames", 1), ("sound", 5), ("leg_sound", 5),
       ("actor_move", 3), ("test_evaded", 0), ("bg_effect_fixed", 8), ("actor_home", 0), ("camera_track", 5),
       ("wait_camera", 0), ("load_effect_gfx", 1), ("spawn_effect", 8), ("wait_sprite_x", 2), ("clear_sprites", 2),
       ("play_anim", 5), ("camera_track_all", 5), ("bg0_wide", 0), ("bg_sweep", 8), ("bg_effect_at", 8),
       ("bg_effect_end", 0), ("actor_pose_loop", 7), ("target_pose_loop", 7), ("bg_sweep_stop", 0), ("trail", 7),
       ("sprite_motion", 3), ("sprite_flip", 3), ("palette_fade", 5), ("backup_bot_palettes", 0),
       ("spawn_effect_wave", 8), ("backup_palette", 2), ("clear_trails", 0), ("bg_effect_keep", 8),
       ("spawn_orbit", 8), ("spawn_effect_set", 4), ("load_effect_gfx_ewram", 1), ("spawn_effect_tiles", 8),
       ("set_tile_anim", 2), ("load_skill_gfx", 0), ("load_effect_gfx_at", 2), ("scale_sprite", 6),
       ("spawn_ring", 4), ("armor_panel", 2), ("wait_armor_panel", 0), ("bg_effect_clear", 0),
       ("bg_effect_noflip", 8), ("show_rolls", 0)]
OPCODE = {n: i for i, (n, _) in enumerate(OPS)}


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def label_counts(rom):
    return rom[SEQ_COUNT_TABLE:SEQ_COUNT_TABLE + 0x100]


def safe_labels(rom):
    c = label_counts(rom)
    return [v for v in range(0x80, 0x100) if c[v] == 0]


def skill_names():
    h = __import__("paths").DECOMP / "include/constants/skills.h"
    names = []
    if h.exists():
        t = h.read_text(encoding="utf-8")
        body = t[t.index("SKILL_SWORD"):t.index("SKILL_COUNT")]
        names = [w.strip().rstrip(",")[6:] for w in body.split("\n") if w.strip().startswith("SKILL_")]
    return names


def decode(rom, start, end):
    """Comandos de start ate end (o fim e o comeco do proximo roteiro na ROM)."""
    counts = label_counts(rom)
    ops, o = [], start
    while o < end:
        v = struct.unpack_from("<h", rom, o)[0]
        if 0x80 <= v < 0x100:
            ops.append(["label", v])
            o += 2 * (1 + counts[v])
            continue
        if not 0 <= v < len(OPS):
            raise ValueError(f"opcode {v} em 0x{o:X}")
        name, n = OPS[v]
        assert counts[v] == n, (name, counts[v], n)
        ops.append([name] + list(struct.unpack_from(f"<{n}h", rom, o + 2)))
        o += 2 * (1 + n)
    if o != end:
        raise ValueError(f"roteiro 0x{start:X} passa do fim 0x{end:X}")
    return ops


def export(rom, force=False):
    SEQ_DIR.mkdir(parents=True, exist_ok=True)
    ptrs = [u32(rom, SEQ_TABLE + 4 * i) - GBA for i in range(SEQ_ORIG)]
    starts = sorted(set(ptrs))
    ends = {s: (starts[k + 1] if k + 1 < len(starts) else SEQ_TABLE) for k, s in enumerate(starts)}
    names = skill_names()
    first = {}
    wrote = 0
    for i, p in enumerate(ptrs):
        doc = {"seq": i, "name": seq_name(i, names)}
        if p in first:
            doc["same_as"] = first[p]
        else:
            first[p] = i
            doc["ops"] = decode(rom, p, ends[p])
        path = SEQ_DIR / f"{i:03d}.json"
        if path.exists() and not force:
            continue
        path.write_bytes((compact_json(doc) + "\n").encode("utf-8"))
        wrote += 1
    print(f"data/anim/seq: {wrote} gravados ({len(starts)} roteiros distintos)")


def seq_name(i, names):
    if i < len(names):
        return names[i]
    if i >= 0x50:
        return f"medaforce_{i - 0x50:02d}"
    return f"unused_{i:02d}"


def compact_json(doc):
    out = ["{"]
    items = list(doc.items())
    for k, (key, v) in enumerate(items):
        comma = "," if k < len(items) - 1 else ""
        if key == "ops":
            out.append(f' "ops": [')
            for j, op in enumerate(v):
                out.append("  " + json.dumps(op) + ("," if j < len(v) - 1 else ""))
            out.append(" ]" + comma)
        else:
            out.append(f' "{key}": {json.dumps(v)}{comma}')
    out.append("}")
    return "\n".join(out)


def load_all():
    docs = {}
    for f in sorted(SEQ_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[d["seq"]] = d
    if not docs:
        raise SystemExit("data/anim/seq vazio (python tools/anim_seq.py --export)")
    missing = [i for i in range(max(docs) + 1) if i not in docs]
    if missing:
        raise SystemExit(f"data/anim/seq: faltam roteiros {missing[:10]}")
    return docs


def encode(doc, rom):
    """Lista de s16 de um roteiro, validada (opcode, numero de operandos, rotulos usaveis e existentes)."""
    safe = set(safe_labels(rom))
    out, labels, targets = [], set(), set()
    for op in doc["ops"]:
        name, args = op[0], op[1:]
        if name == "label":
            (v,) = args
            if v not in safe:
                raise SystemExit(f"seq {doc['seq']}: rotulo {v} nao serve (use um de 0x80-0xFF com contagem 0)")
            labels.add(v)
            out.append(v)
            continue
        if name == "op":
            code, args = args[0], args[1:]
        else:
            if name not in OPCODE:
                raise SystemExit(f"seq {doc['seq']}: comando desconhecido {name!r}")
            code = OPCODE[name]
        if len(args) != OPS[code][1]:
            raise SystemExit(f"seq {doc['seq']}: {name} pede {OPS[code][1]} operandos, tem {len(args)}")
        if name == "goto":
            targets.add(args[0])
        elif name == "branch":
            targets.update(args)
        out.append(code)
        out += [((a + 0x8000) & 0xFFFF) - 0x8000 for a in args]
    if not targets <= labels:
        raise SystemExit(f"seq {doc['seq']}: goto/branch para rotulos que nao existem: {sorted(targets - labels)}")
    return out


def build_asm(docs, rom):
    """Texto de assembly: corpos + gBattleSeqScripts (tamanho = maior id + 1)."""
    lines, label_of = [], {}
    for i in sorted(docs):
        d = docs[i]
        if "same_as" in d:
            continue
        vals = encode(d, rom)
        lab = f"sBattleSeq{i:03d}"
        label_of[i] = lab
        lines.append(f"\t.align 1\n{lab}:   @ {d.get('name', '')}\n")
        for k in range(0, len(vals), 16):
            lines.append("\t.2byte " + ", ".join(str(v & 0xFFFF) for v in vals[k:k + 16]) + "\n")
    lines.append("\t.align 2\n\t.global gBattleSeqScripts\ngBattleSeqScripts:\n")
    for i in sorted(docs):
        j = i
        while "same_as" in docs[j]:
            j = docs[j]["same_as"]
        lines.append(f"\t.4byte {label_of[j]}\n")
    return "".join(lines)


def apply(dst, rom):
    """Na arvore gerada: gBattleSeqScripts original vira _vanilla (no lugar) e a tabela nova vai para expansion.s."""
    dst = Path(dst)
    hit = 0
    for f in dst.glob("data/*.s"):
        t = f.read_text()
        new = t.replace("\t.global gBattleSeqScripts\ngBattleSeqScripts:",
                        "\t.global gBattleSeqScripts_vanilla\ngBattleSeqScripts_vanilla:")
        if new != t:
            f.write_text(new)
            hit += 1
    assert hit == 1, "gBattleSeqScripts nao achado nos dados"
    docs = load_all()
    exp = dst / "asm/expansion.s"
    exp.write_text(exp.read_text() + "\n@ roteiros de golpe (tools/anim_seq.py, data/anim/seq)\n" + build_asm(docs, rom))
    print(f"  roteiros de golpe: {len(docs)} (data/anim/seq)")


def check(rom):
    """Os JSON montados dao exatamente os mesmos roteiros da ROM original (comparando lista a lista)."""
    docs = load_all()
    ptrs = [u32(rom, SEQ_TABLE + 4 * i) - GBA for i in range(SEQ_ORIG)]
    starts = sorted(set(ptrs))
    ends = {s: (starts[k + 1] if k + 1 < len(starts) else SEQ_TABLE) for k, s in enumerate(starts)}
    bad = 0
    for i, p in enumerate(ptrs):
        d = docs[i]
        while "same_as" in d:
            d = docs[d["same_as"]]
        want = list(struct.unpack_from(f"<{(ends[p] - p) // 2}h", rom, p))
        if encode(d, rom) != want:
            bad += 1
            print("diferente:", i)
    print(f"check: {SEQ_ORIG - bad}/{SEQ_ORIG} iguais a ROM original")
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--baserom", default=str(__import__("paths").DECOMP / "baserom.gba"))
    a = ap.parse_args()
    rom = Path(a.baserom).read_bytes()
    if a.export:
        export(rom, a.force)
    if a.check:
        raise SystemExit(0 if check(rom) else 1)
    if not (a.export or a.check):
        ap.print_help()


if __name__ == "__main__":
    main()
