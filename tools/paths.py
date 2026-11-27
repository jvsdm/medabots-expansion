"""paths.py - Onde ficam as coisas de fora do projeto (arvores do decomp, toolkit, compiladores).

Ordem: variavel de ambiente > medabots.config.json (gravado pelo tools/setup.py) > padrao deste repositorio.
  decomp            MEDABOTS_DECOMP_EXPANSION  arvore do decomp na branch expansion (copiada a cada build)
  decomp_original   MEDABOTS_DECOMP_ORIGINAL   arvore do decomp na branch main, ja compilada (dados do jogo, .map)
  toolkit           MEDABOTS_TOOLKIT           clone do Medabots-Romhacking-Toolkit (assinaturas de layout do WPF)
  w64devkit         MEDABOTS_W64DEVKIT         (Windows) pasta bin do w64devkit (make, sh); fora do Windows usa o PATH
  arm_prefix        MEDABOTS_ARM_PREFIX        prefixo do binutils ARM (ex.: arm-none-eabi-)
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "medabots.config.json"
_cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}


def _get(key, env, default):
    v = os.environ.get(env) or _cfg.get(key)
    if v:
        p = Path(v)
        return p if p.is_absolute() else ROOT / p
    return default


DECOMP = _get("decomp", "MEDABOTS_DECOMP_EXPANSION", ROOT / "build/scratch/decomp_rok")
DECOMP_ORIGINAL = _get("decomp_original", "MEDABOTS_DECOMP_ORIGINAL", DECOMP)
TOOLKIT = _get("toolkit", "MEDABOTS_TOOLKIT", ROOT / "git/Medabots-Romhacking-Toolkit")
W64 = _get("w64devkit", "MEDABOTS_W64DEVKIT", ROOT / "build/scratch/w64/w64devkit/bin")


def arm_prefix():
    v = os.environ.get("MEDABOTS_ARM_PREFIX") or _cfg.get("arm_prefix")
    if v:
        return v
    local = ROOT / "tools/arm-gcc/bin/arm-none-eabi-"
    return local.as_posix() if Path(str(local) + ("gcc.exe" if os.name == "nt" else "gcc")).exists() else "arm-none-eabi-"


def arm_path(env):
    """Poe no PATH a pasta do binutils ARM quando o prefixo e um caminho (o build.sh do agbcc procura arm-none-eabi-as)."""
    pre = arm_prefix()
    d = os.path.dirname(pre)
    if d:
        env["PATH"] = os.pathsep.join([str(Path(d)), env.get("PATH", "")])
    return env


def make_command(env):
    """(comando make, env) para compilar uma arvore do decomp. No Windows: make/sh do w64devkit e um python3 que chama
    este Python (o Makefile do decomp chama python3); fora dele, o make do sistema."""
    if os.name == "nt":
        if not (W64 / "make.exe").exists():
            raise SystemExit(f"w64devkit nao encontrado em {W64} (tools/setup.py ou MEDABOTS_W64DEVKIT)")
        shim = ROOT / "build/shim"
        shim.mkdir(parents=True, exist_ok=True)
        (shim / "python3").write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n', encoding="utf-8")
        env["PATH"] = os.pathsep.join([str(shim), str(W64), env.get("PATH", "")])
        env = arm_path(env)
        return [str(W64 / "make.exe"), "-j4", f"PREFIX={arm_prefix()}", f"SHELL={(W64 / 'sh.exe').as_posix()}"], env
    if not shutil.which("make"):
        raise SystemExit("make nao encontrado (instale build-essential)")
    return ["make", f"-j{os.cpu_count() or 4}", f"PREFIX={arm_prefix()}"], arm_path(env)
