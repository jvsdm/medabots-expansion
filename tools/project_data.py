"""project_data.py - Separa os dados do jogo da camada do projeto (repositorio publico sem dados do jogo).

data/maps, data/events e data/anim/{seq,poses,pose_anims.json} sao gerados da ROM de quem usa o projeto (extratores
tools/maps_lift.py, events_lift.py, anim_seq.py, anim_poses.py, lendo a arvore ORIGINAL do decomp em MEDABOTS_DECOMP).
O que o projeto muda ou cria fica em overlay/:
  overlay/<pasta>/<arquivo>.patch.json   arquivo do jogo alterado: SHA1 do original + trocas de linhas
  overlay/<pasta>/<arquivo>              arquivo novo do projeto (copiado como esta)

Uso:
  python tools/project_data.py install          extrai os dados da ROM para data/ e aplica overlay/ (quem usa)
  python tools/project_data.py make-overlay     compara data/ com o que sai da ROM e grava overlay/ (quem edita)
  python tools/project_data.py check            confere que install reproduz o data/ atual
Precisa: MEDABOTS_DECOMP = arvore original do decomp (branch main) com a baserom.gba (Rokusho USA).
"""
import argparse
import difflib
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
DATA = ROOT / "data"
OVERLAY = ROOT / "overlay"
# pastas/arquivos que saem da ROM (relativos a data/)
GENERATED = ["maps", "events", "anim/seq", "anim/poses", "anim/pose_anims.json"]
TEXT = {".json", ".evt", ".txt", ".tail", ".md"}


def _tmpbase():
    d = ROOT / "build"          # dentro do projeto (os extratores mostram caminhos relativos a ele); fora do git
    d.mkdir(exist_ok=True)
    return d


def _decomp():
    d = os.environ.get("MEDABOTS_DECOMP")
    if not d or not (Path(d) / "baserom.gba").exists():
        raise SystemExit("MEDABOTS_DECOMP precisa apontar a arvore original do decomp (branch main) com a baserom.gba")
    return Path(d)


def extract(dst):
    """Gera em dst/ (mesma estrutura de data/) o que sai da ROM."""
    dec = _decomp()
    os.environ["MEDABOTS_DECOMP"] = str(dec)
    import subprocess
    py = sys.executable
    for tool, out in (("maps_lift.py", dst / "maps"), ("events_lift.py", dst / "events")):
        r = subprocess.run([py, str(ROOT / "tools" / tool), "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"{tool} falhou:\n{r.stdout}\n{r.stderr}")
    usa = (dec / "baserom.gba").read_bytes()
    import anim_seq
    import anim_poses
    anim_seq.SEQ_DIR = dst / "anim/seq"
    anim_poses.POSES_DIR = dst / "anim/poses"
    anim_poses.ANIMS_FILE = dst / "anim/pose_anims.json"
    (dst / "anim").mkdir(parents=True, exist_ok=True)
    anim_seq.export(usa, force=True)
    anim_poses.export(usa, force=True)
    anim_poses.export_anims(usa, force=True)


def _files(base, rel):
    p = base / rel
    if p.is_file():
        return {rel}
    return {f.relative_to(base).as_posix() for f in p.rglob("*") if f.is_file()} if p.exists() else set()


def _lines(p):
    return p.read_bytes().replace(b"\r\n", b"\n").decode("utf-8").split("\n")


def _same(a, b):
    if a.suffix in TEXT:
        if a.suffix == ".json":
            try:
                return json.loads(a.read_text(encoding="utf-8")) == json.loads(b.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return _lines(a) == _lines(b)
    return a.read_bytes() == b.read_bytes()


def make_overlay():
    with tempfile.TemporaryDirectory(dir=_tmpbase()) as t:
        van = Path(t)
        extract(van)
        if OVERLAY.exists():
            shutil.rmtree(OVERLAY)
        n_patch = n_new = 0
        for rel in GENERATED:
            mine, theirs = _files(DATA, rel), _files(van, rel)
            for f in sorted(mine):
                src = DATA / f
                if f in theirs:
                    if _same(src, van / f):
                        continue
                    if src.suffix not in TEXT:
                        raise SystemExit(f"{f}: arquivo binario do jogo alterado (overlay so de texto)")
                    old, new = _lines(van / f), _lines(src)
                    ops = [[i1, i2, new[j1:j2]] for tag, i1, i2, j1, j2 in
                           difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if tag != "equal"]
                    out = OVERLAY / (f + ".patch.json")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps({"base_sha1": hashlib.sha1("\n".join(old).encode("utf-8")).hexdigest(),
                                               "ops": ops}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                    n_patch += 1
                else:
                    out = OVERLAY / f
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, out)
                    n_new += 1
            gone = sorted(theirs - mine)
            if gone:
                raise SystemExit(f"{rel}: arquivos do jogo apagados no projeto (overlay nao representa): {gone[:5]}")
    print(f"overlay/: {n_patch} arquivos alterados (patch), {n_new} novos")


def apply_overlay(dst):
    n = 0
    for p in sorted(OVERLAY.rglob("*")) if OVERLAY.exists() else []:
        if not p.is_file():
            continue
        rel = p.relative_to(OVERLAY).as_posix()
        if rel.endswith(".patch.json"):
            target = dst / rel[:-len(".patch.json")]
            patch = json.loads(p.read_text(encoding="utf-8"))
            lines = _lines(target)
            if hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest() != patch["base_sha1"]:
                raise SystemExit(f"{rel}: o arquivo do jogo nao e o esperado (ROM diferente?)")
            for i1, i2, new in reversed(patch["ops"]):
                lines[i1:i2] = new
            target.write_bytes("\n".join(lines).encode("utf-8"))
        else:
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        n += 1
    return n


def install(dst=DATA):
    for rel in GENERATED:
        p = dst / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    extract(dst)
    print(f"data/: dados do jogo extraidos da ROM; overlay/: {apply_overlay(dst)} arquivos aplicados")
    if dst == DATA:     # os 120 bots do jogo como JSON (tools/build.py completa a lista com eles)
        import core_bots
        print(f"data/bots: {core_bots.generate()} bots do jogo gerados da ROM")


def check():
    with tempfile.TemporaryDirectory(dir=_tmpbase()) as t:
        out = Path(t)
        extract(out)
        apply_overlay(out)
        bad = []
        for rel in GENERATED:
            mine, got = _files(DATA, rel), _files(out, rel)
            bad += [f"so no data/: {f}" for f in sorted(mine - got)] + [f"so no install: {f}" for f in sorted(got - mine)]
            bad += [f"diferente: {f}" for f in sorted(mine & got) if not _same(DATA / f, out / f)]
    print("install reproduz data/: " + ("OK" if not bad else f"{len(bad)} diferencas") + "".join("\n  " + b for b in bad[:20]))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["install", "make-overlay", "check"])
    a = ap.parse_args()
    if a.cmd == "make-overlay":
        make_overlay()
    elif a.cmd == "install":
        install()
    else:
        sys.exit(check())


if __name__ == "__main__":
    main()
