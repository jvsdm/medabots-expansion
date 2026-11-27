"""setup.py - Prepara o projeto num computador novo (uma vez; pode rodar de novo, so refaz o que falta).

  1. confere o Python e as ROMs (pasta roms/; tools/roms.py) e diz qual nivel da para montar
  2. baixa o decomp (jvsdm/medabots-rokusho: main = jogo original, expansion = a do projeto), o agbcc (pret) e o
     toolkit do WPF (so as assinaturas de layout) em deps/
  3. compila o agbcc e instala nas duas arvores; copia a ROM USA como baserom.gba
  4. compila a arvore original (make compare: confere ROM e compiladores; o .map serve ao layout do WPF)
  5. extrai os dados do jogo da sua ROM e aplica a camada do projeto (tools/project_data.py install)
  6. grava medabots.config.json (tools/paths.py le)
Depois: python tools/decomp_build.py --level core   (ou shingata / navi)

Precisa: git, make, um compilador C (gcc) e o binutils ARM (arm-none-eabi-*). Linux/WSL: veja INSTALL.md. Windows sem
WSL: w64devkit (passe --w64devkit <pasta bin>) e o binutils ARM no PATH (ou --arm-prefix).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
DEPS = ROOT / "deps"
DECOMP_URL = "https://github.com/jvsdm/medabots-rokusho.git"
AGBCC_URL = "https://github.com/pret/agbcc.git"
TOOLKIT_URL = "https://github.com/jvsdm/Medabots-Romhacking-Toolkit.git"


def run(cmd, cwd=None, env=None, check=True):
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if check and r.returncode:
        raise SystemExit(f"falhou ({r.returncode}): {' '.join(str(c) for c in cmd)}")
    return r.returncode


def clone(url, dst, branch=None, depth=None):
    if (dst / ".git").exists():
        print(f"  ja existe: {dst.relative_to(ROOT)}")
        return
    cmd = ["git", "clone", "--quiet"] + (["--branch", branch] if branch else []) + (["--depth", str(depth)] if depth else [])
    run(cmd + [url, dst])


def step(n, text):
    print(f"\n[{n}] {text}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--w64devkit", help="(Windows) pasta bin do w64devkit (make.exe, sh.exe, gcc.exe)")
    ap.add_argument("--arm-prefix", help="prefixo do binutils ARM, ex. arm-none-eabi- ou C:/arm/bin/arm-none-eabi-")
    a = ap.parse_args()
    cfg_file = ROOT / "medabots.config.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    if a.w64devkit:
        cfg["w64devkit"] = str(Path(a.w64devkit).resolve())
    if a.arm_prefix:
        cfg["arm_prefix"] = a.arm_prefix

    step(1, "Python e ROMs")
    if sys.version_info < (3, 10):
        raise SystemExit("precisa de Python 3.10 ou mais novo")
    import roms
    if roms.main() != 0:
        raise SystemExit(f"ponha ao menos as ROMs do nivel CORE em {ROOT / 'roms'} (veja README.md)")

    step(2, "Dependencias em deps/")
    DEPS.mkdir(exist_ok=True)
    original, expansion = DEPS / "decomp_original", DEPS / "decomp_expansion"
    clone(DECOMP_URL, original, branch="main")
    clone(DECOMP_URL, expansion, branch="expansion")
    clone(AGBCC_URL, DEPS / "agbcc", depth=1)
    clone(TOOLKIT_URL, DEPS / "toolkit", branch="decomp-project", depth=1)
    cfg.update({"decomp": "deps/decomp_expansion", "decomp_original": "deps/decomp_original", "toolkit": "deps/toolkit"})
    cfg_file.write_text(json.dumps(cfg, indent=1) + "\n", encoding="utf-8")

    import importlib
    import paths
    importlib.reload(paths)
    env = dict(os.environ)
    if os.name == "nt":
        _, env = paths.make_command(env)          # make/sh/gcc do w64devkit no PATH

    step(3, "agbcc e baserom.gba")
    # so o agbcc (o decomp nao usa old_agbcc/agbcc_arm/libs) e os headers: o build.sh do pret nao roda no Windows
    agbcc = DEPS / "agbcc"
    exe = agbcc / "gcc" / ("agbcc.exe" if os.name == "nt" else "agbcc")
    make = str(paths.W64 / "make.exe") if os.name == "nt" else "make"
    if not exe.exists():
        run([make, "-C", "gcc", "clean"], cwd=agbcc, env=env, check=False)   # sem restos de outra compilacao
        run([make, "-C", "gcc", "-j1"], cwd=agbcc, env=env)
    base = roms.rom_path("rokusho_us")
    for tree in (original, expansion):
        dst = tree / "tools/agbcc"
        if True:        # sempre (barato): nunca fica um agbcc de outra compilacao na arvore
            (dst / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(exe, dst / "bin" / exe.name)
            shutil.copytree(agbcc / "libc/include", dst / "include", dirs_exist_ok=True)
            shutil.copytree(agbcc / "ginclude", dst / "include", dirs_exist_ok=True)
        tb = tree / "baserom.gba"     # confere pelo SHA1 (uma copia interrompida nao fica)
        if not tb.exists() or hashlib.sha1(tb.read_bytes()).hexdigest() != roms.ROMS["rokusho_us"][1]:
            shutil.copyfile(base, tb)

    step(4, "compila o jogo original (make compare)")
    if not (original / "medabots_rokusho.map").exists():
        cmd, env2 = paths.make_command(dict(env))
        run(cmd + ["compare"], cwd=original, env=env2)

    step(5, "dados do jogo da sua ROM + camada do projeto")
    env3 = dict(os.environ, MEDABOTS_DECOMP=str(original.resolve()))
    run([sys.executable, ROOT / "tools/project_data.py", "install"], cwd=ROOT, env=env3)

    step(6, "pronto")
    print(f"  configuracao: {cfg_file.relative_to(ROOT)}")
    print(f"  nivel possivel com as suas ROMs: {roms.level_available()}")
    print("  construa: python tools/decomp_build.py --level " + (roms.level_available() or "core"))


if __name__ == "__main__":
    main()
