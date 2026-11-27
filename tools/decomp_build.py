"""decomp_build.py - Gera e compila uma ROM da decomp a partir da lista de bots e dos JSON (um passo so; usado pela
barra do WPF e por quem quiser). Sempre numa pasta NOVA (a ROM anterior pode estar aberta): sem --dst, a proxima
build/scratch/decomp_hpNN. Copia o save (.sav) da hp anterior e, com a build pronta, apaga as decomp_hp* antigas
(ficam as 2 ultimas; --keep-all nao apaga; nunca a que teve o save gravado durante a build).
Guarda em <pasta>/base/ a ROM pura com os arquivos de apoio: o WPF aplica as edicoes dele (fase 4) por cima dela.

Uso: python tools/decomp_build.py [--list data/expansion_bots.txt] [--dst build/scratch/decomp_hpNN] [--keep-all]
                                  [opcoes extras do decomp_expand, ex. --no-medachange]
Saida: a ultima linha e "ROM: <caminho>" (com <rom>.layout.json ao lado). Codigo de saida != 0 em erro.
"""
import argparse
import os
import re
import shutil
import time
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import paths  # noqa: E402  (arvores do decomp e compiladores: tools/paths.py)


def hp_builds():
    """[(N, pasta)] das build/scratch/decomp_hpNN, em ordem de N."""
    out = []
    for d in (ROOT / "build/scratch").glob("decomp_hp*"):
        m = re.fullmatch(r"decomp_hp(\d+)", d.name)
        if m and d.is_dir():
            out.append((int(m.group(1)), d))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=str(ROOT / "data/expansion_bots.txt"))
    ap.add_argument("--level", choices=["core", "shingata", "navi"],
                    help="nivel do projeto (ROMs em roms/, tools/roms.py): core = so os 120 bots do jogo; shingata = + os "
                         "60 do Shingata Medarot; navi = + os do Medarot Navi. Substitui --list")
    ap.add_argument("--dst")
    ap.add_argument("--keep-all", action="store_true", help="nao apaga as decomp_hp* antigas")
    a, extra = ap.parse_known_args()
    hps = hp_builds()
    t0 = time.time()
    dst = Path(a.dst) if a.dst else ROOT / "build/scratch" / f"decomp_hp{(hps[-1][0] + 1) if hps else 1}"
    if dst.exists():
        raise SystemExit(f"{dst} ja existe: use uma pasta nova")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    # edicoes de mapa do WPF (colisao, NPCs, warps) viram arquivos de data/maps antes de gerar (plano de mapas M5)
    import wpf_maps_to_files
    for d in wpf_maps_to_files.convert(ROOT / "data/wpf/project.medahack.json", ROOT / "data/maps"):
        print(f"  WPF -> data/maps: {d}", flush=True)
    # roteiros editados no WPF viram .evt de data/events (plano M6)
    import wpf_events_to_files
    for d in wpf_events_to_files.convert(ROOT / "data/wpf/project.medahack.json", ROOT / "data/events"):
        print(f"  WPF -> data/events: {d}", flush=True)
    # storyline (plano M7): warp, roteiro ou fala que nao existe para a build; o resto e aviso
    import story_check
    errs, warns, _ = story_check.check()
    for w in warns:
        print(f"  aviso: {w}", flush=True)
    if errs:
        raise SystemExit("storyline com erro (tools/story_check.py):\n  " + "\n  ".join(errs))
    print(f"gerando a arvore em {dst}", flush=True)
    if not a.level and a.list == str(ROOT / "data/expansion_bots.txt"):
        import roms           # sem --level nem --list (ex.: Build ROM do WPF): o maior nivel que as ROMs presentes deixam
        lv = roms.level_available()
        if lv != "navi":      # faltam ROMs para a lista completa: monta o nivel que da (a lista do arquivo vale com todas)
            a.level = lv
            print(f"nivel {lv} (ROMs presentes; tools/roms.py)", flush=True)
    if a.level:
        import roms
        for key in roms.LEVELS[a.level]:
            roms.rom_path(key)              # para aqui, com o nome e o SHA1, se faltar ROM do nivel
        lvl = {"core": [], "shingata": ["shingata/*"], "navi": ["shingata/*", "navi/*"]}[a.level]
        a.list = str(dst.parent / f".{dst.name}_nivel_{a.level}.txt")
        Path(a.list).write_text("\n".join([f"# nivel {a.level} (tools/decomp_build.py --level)"] + lvl) + "\n",
                                encoding="utf-8")
    packs = [l.split("#")[0].strip() for l in Path(a.list).read_text(encoding="utf-8").splitlines()]
    if any(packs):
        bots_arg = ["--bot-list", a.list]
    else:       # lista sem pacote (nivel CORE): so os 120 do jogo, sem a expansao binaria (nem a ROM do Shingata/Navi)
        vazio = dst.parent / f".{dst.name}_sem_bots.json"
        vazio.write_text("[]", encoding="utf-8")
        bots_arg = ["--bots", str(vazio)]
    r = subprocess.run([sys.executable, str(ROOT / "tools/decomp_expand.py"), *bots_arg, "--dst", str(dst),
                        *extra], cwd=ROOT, env=env)
    if r.returncode:
        raise SystemExit(f"decomp_expand falhou ({r.returncode})")
    make_cmd, env = paths.make_command(env)
    print("compilando (make)...", flush=True)
    r = subprocess.run(make_cmd, cwd=dst, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    (dst / "build.log").write_text(r.stdout, encoding="utf-8")
    if r.returncode:
        print(r.stdout[-3000:])
        raise SystemExit(f"make falhou ({r.returncode}); log em {dst / 'build.log'}")
    rom = dst / "medabots_rokusho.gba"
    # copia pura da ROM (base/): o WPF le dela e aplica o projeto dele (data/wpf/project.medahack.json) na ROM de jogar,
    # a cada build; os arquivos de apoio vao junto (perfil, simbolos, ids)
    base = dst / "base"
    base.mkdir(exist_ok=True)
    for f in [rom, rom.with_suffix(".layout.json"), rom.with_suffix(".map"), dst / "bot_ids.json", dst / "pose_rows.json"]:
        if f.exists():
            shutil.copy2(f, base / f.name)
    # save do usuario: o .sav gravado por ultimo entre as hp anteriores (quem joga pode estar numa hp mais velha)
    savs = [d / "medabots_rokusho.sav" for _, d in hps if d != dst and (d / "medabots_rokusho.sav").exists()]
    if savs:
        sav = max(savs, key=lambda f: f.stat().st_mtime)
        shutil.copy2(sav, dst / sav.name)
        print(f"save copiado de {sav.parent.name}", flush=True)
    if not a.keep_all and re.fullmatch(r"decomp_hp\d+", dst.name):
        # ficam as 2 ultimas que geraram ROM; arvore de build que falhou (sem ROM) nao conta e sai
        built = [d for _, d in hp_builds() if (d / "medabots_rokusho.gba").exists()]
        for _, d in hp_builds():
            if d == dst or d in built[-2:]:
                continue
            sav = d / "medabots_rokusho.sav"
            if sav.exists() and sav.stat().st_mtime > t0:   # alguem jogando nela durante a build: nao apaga
                print(f"mantida {d.name}: o save mudou durante a build (jogo aberto?)", flush=True)
                continue
            shutil.rmtree(d, ignore_errors=True)
            print(f"apagada build antiga {d.name}{' (parte em uso ficou)' if d.exists() else ''}", flush=True)
    print(f"ROM: {rom}")


if __name__ == "__main__":
    main()
