"""anim_poses.py - Poses de batalha dos Medabots em JSON (data/anim/poses/NN.json), fonte da verdade do gerador.

Formato do jogo (src/engine/interpolate.c, common.c medabot_pose_anim_step): por roteiro de pose s (59):
  gPoseKeyframeEnds[s]    u8 por quadro-chave = quadro em que a pose-chave termina (0 fecha a lista)
  gPoseKeyframeAngles[s]  s16 por (linha de molde 1..63, quadro-chave): angulo do no (giro, 0x10000 = volta)
  gPoseKeyframeOffsets[s] (baixo, direita) s8 por (linha, quadro-chave): deslocamento do no (o C chama
                          de offsetX/offsetY, nomes trocados: ver tools/anim_render.py); angulo + = horario
  linha = id do molde (1..49 no jogo; 50..63 = moldes novos do Navi, slot depende da lista de bots).
JSON (um por roteiro, so linhas nao vazias, nomes de molde estaveis):
  {"script": 7, "ends": [8, 16, 24], "angles": {"core/07": [0, 4096, 0]}, "offsets": {"core/07": [[0, 0], ...]}}
  "angles_from"/"offsets_from": N = mesmo bloco do roteiro N (o jogo divide blocos entre roteiros).
  Moldes do Navi: "navi/MM" (id do molde no Navi) sobrescreve a linha; sem ele a linha copia o molde analogo do jogo.
Uso: python tools/anim_poses.py --export  (le a baserom original; nao sobrescreve arquivo existente sem --force)
"""
import argparse
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSES_DIR = ROOT / "data/anim/poses"
GBA = 0x08000000
POSE_ANG, POSE_OFF, POSE_END = 0x3D1CC0, 0x3D1DAC, 0x3D1E98   # Rokusho USA: 59 ponteiros cada
POSE_SCRIPTS = 59
ORIG_ROWS = 49


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


def script_ptrs(usa, s):
    end = u32(usa, POSE_END + 4 * s) - GBA
    keys = 0
    while usa[end + keys]:
        keys += 1
    return keys, list(usa[end:end + keys]), u32(usa, POSE_ANG + 4 * s) - GBA, u32(usa, POSE_OFF + 4 * s) - GBA


def export(usa, force=False):
    POSES_DIR.mkdir(parents=True, exist_ok=True)
    first_ang, first_off = {}, {}
    wrote = 0
    for s in range(POSE_SCRIPTS):
        keys, ends, ang, off = script_ptrs(usa, s)
        doc = {"script": s, "ends": ends}
        if keys:
            if ang in first_ang:
                doc["angles_from"] = first_ang[ang]
            else:
                first_ang[ang] = s
                rows = {}
                for r in range(1, ORIG_ROWS + 1):
                    vals = list(struct.unpack_from(f"<{keys}h", usa, ang + (r - 1) * keys * 2))
                    if any(vals):
                        rows[f"core/{r:02d}"] = vals
                doc["angles"] = rows
            if off in first_off:
                doc["offsets_from"] = first_off[off]
            else:
                first_off[off] = s
                rows = {}
                for r in range(1, ORIG_ROWS + 1):
                    raw = struct.unpack_from(f"<{keys * 2}b", usa, off + (r - 1) * keys * 2)
                    pairs = [[raw[2 * k], raw[2 * k + 1]] for k in range(keys)]
                    if any(v for p in pairs for v in p):
                        rows[f"core/{r:02d}"] = pairs
                doc["offsets"] = rows
        path = POSES_DIR / f"{s:02d}.json"
        if path.exists() and not force:
            continue
        path.write_text(compact_json(doc) + "\n", encoding="utf-8")
        wrote += 1
    print(f"data/anim/poses: {wrote} gravados")


def compact_json(doc):
    """JSON legivel com cada linha de molde numa linha so."""
    out = ["{"]
    items = list(doc.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if isinstance(v, dict):
            out.append(f' "{k}": {{')
            rows = list(v.items())
            for j, (rk, rv) in enumerate(rows):
                out.append(f'  "{rk}": {json.dumps(rv, separators=(",", ":"))}' + ("," if j < len(rows) - 1 else ""))
            out.append(" }" + comma)
        else:
            out.append(f' "{k}": {json.dumps(v)}{comma}')
    out.append("}")
    return "\n".join(out)


def load_all():
    docs = {}
    for f in sorted(POSES_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[d["script"]] = d
    if len(docs) < POSE_SCRIPTS:
        raise SystemExit(f"data/anim/poses: {len(docs)} roteiros, esperava {POSE_SCRIPTS}+ (python tools/anim_poses.py --export)")
    missing = [i for i in range(max(docs) + 1) if i not in docs]
    if missing:
        raise SystemExit(f"data/anim/poses: faltam roteiros {missing[:10]} (ids seguidos)")
    for s, d in docs.items():
        ends = d["ends"]
        if len(ends) > 0xFE or not all(1 <= e <= 255 for e in ends):
            raise SystemExit(f"data/anim/poses/{s:02d}.json: ends = quadros de cada pose-chave, 1..255 (ate 254 chaves)")
        for kind in ("angles", "offsets"):
            for name, row in (d.get(kind) or {}).items():
                if len(row) != len(ends):
                    raise SystemExit(f"data/anim/poses/{s:02d}.json: {kind} {name} tem {len(row)} valores, "
                                     f"ends tem {len(ends)} chaves")
    return docs


# ---- linhas de animacao (gPoseAnimIds[linha][coluna]) -------------------------------------------------------------
# actor_pose / target_pose (data/anim/seq) escolhem uma LINHA por peca (cabeca, braco dir., braco esq.) e lado; a
# COLUNA vem das pernas do bot (gLegPartPoseSets[pernas], 0..6); a celula e o roteiro de pose (data/anim/poses).
ANIMS_FILE = ROOT / "data/anim/pose_anims.json"
POSE_ANIM_IDS, POSE_ANIM_ROWS = 0x7E77C, 47


def export_anims(usa, force=False):
    if ANIMS_FILE.exists() and not force:
        return
    rows = [list(struct.unpack_from("<7I", usa, POSE_ANIM_IDS + 28 * r)) for r in range(POSE_ANIM_ROWS)]
    out = ['{', ' "_doc": "linha (operando de actor_pose/target_pose) -> roteiro de pose por coluna de pernas'
           ' (gLegPartPoseSets[pernas] = 0..6)",', ' "anims": [']
    out += [f"  {json.dumps(r)}" + ("," if i < len(rows) - 1 else "") for i, r in enumerate(rows)]
    out += [" ]", "}"]
    ANIMS_FILE.write_bytes(("\n".join(out) + "\n").encode("utf-8"))
    print(f"{ANIMS_FILE.relative_to(ROOT)}: {len(rows)} linhas")


def load_anims(docs):
    rows = json.loads(ANIMS_FILE.read_text(encoding="utf-8"))["anims"]
    if len(rows) > 255:
        raise SystemExit("pose_anims.json: ate 255 linhas (o id da pose e u8)")
    for i, r in enumerate(rows):
        if len(r) != 7 or not all(v in docs for v in r):
            raise SystemExit(f"pose_anims.json linha {i}: 7 roteiros de pose existentes, tem {r}")
    return rows


MOTION_ROWS = 63      # linhas por bloco (1..63 = os 0x40 nos do jogo menos o 0): as 49 do jogo + zeros


def apply(dst, blocks=False):
    """Na arvore gerada: gPoseKeyframeEnds e gPoseAnimIds originais viram _vanilla (no lugar) e os novos, dos JSON,
    vao para o fim de expansion.s. blocks=True (build sem bots do Navi): tambem gPoseKeyframeAngles/Offsets, com
    63 linhas (com o Navi, decomp_navi.plan ja monta esses dois com as linhas dos moldes novos)."""
    dst = Path(dst)
    docs = load_all()
    rows = load_anims(docs)
    for nm in ("gPoseKeyframeEnds", "gPoseAnimIds"):
        hit = 0
        for f in dst.glob("data/*.s"):
            t = f.read_text()
            new = t.replace(f"\t.global {nm}\n{nm}:", f"\t.global {nm}_vanilla\n{nm}_vanilla:")
            if new != t:
                f.write_text(new)
                hit += 1
        assert hit == 1, nm
    out = ["\n@ poses (tools/anim_poses.py, data/anim/poses + pose_anims.json)\n"]
    if blocks:
        for nm, kind in (("gPoseKeyframeAngles", "angles"), ("gPoseKeyframeOffsets", "offsets")):
            labels = []
            for s in sorted(docs):
                keys = len(docs[s]["ends"])
                if keys == 0:
                    labels.append("0")
                    continue
                data = block_bytes(docs, s, kind, MOTION_ROWS, keys, None)[0]
                lab = f"sPose{kind.capitalize()}{s:02d}"
                labels.append(lab)
                out.append(f"\t.align 2\n{lab}:\n")
                out += ["\t.byte " + ", ".join(f"0x{v:02X}" for v in data[i:i + 32]) + "\n"
                        for i in range(0, len(data), 32)]
            out.append(f"\t.align 2\n\t.global {nm}\n{nm}:\n")
            out += [f"\t.4byte {lab}\n" for lab in labels]
    for s in sorted(docs):
        out.append(f"sPoseEnds{s:02d}:\n\t.byte " + ", ".join(str(e) for e in docs[s]["ends"] + [0]) + "\n")
    out.append("\t.align 2\n\t.global gPoseKeyframeEnds\ngPoseKeyframeEnds:\n")
    out += [f"\t.4byte sPoseEnds{s:02d}\n" for s in sorted(docs)]
    out.append("\t.global gPoseAnimIds\ngPoseAnimIds:\n")
    out += ["\t.4byte " + ", ".join(map(str, r)) + "\n" for r in rows]
    exp = dst / "asm/expansion.s"
    exp.write_text(exp.read_text() + "".join(out))
    print(f"  poses: {len(docs)} roteiros, {len(rows)} linhas de animacao (data/anim)")


def block_bytes(docs, s, kind, rows_total, keys, extra_rows):
    """Bloco do roteiro s ("angles" ou "offsets") com rows_total linhas. extra_rows(row_bytes) -> {linha: bytes}
    (linhas dos moldes do Navi derivadas do analogo); "navi/MM" no JSON vence."""
    d = docs[s]
    src = d.get(kind)
    while src is None:
        d = docs[d[f"{kind}_from"]]
        src = d.get(kind)
    row = keys * 2
    data = bytearray(rows_total * row)

    def put(r, vals):
        if kind == "angles":
            data[(r - 1) * row:r * row] = struct.pack(f"<{keys}h", *vals)
        else:
            data[(r - 1) * row:r * row] = struct.pack(f"<{keys * 2}b", *(v for p in vals for v in p))

    for name, vals in src.items():
        if name.startswith("core/"):
            put(int(name[5:]), vals)
    return data, put, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--baserom", default=str(__import__("paths").DECOMP / "baserom.gba"))
    a = ap.parse_args()
    if a.export:
        usa = Path(a.baserom).read_bytes()
        export(usa, a.force)
        export_anims(usa, a.force)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
