"""roms.py - Acha as ROMs do projeto pelo SHA1 (o nome do arquivo nao importa).

Quem usa o projeto poe as ROMs que tiver em `roms/` (ou na raiz do projeto, ou numa pasta em MEDABOTS_ROMS). Cada
nivel do projeto pede um conjunto:
  CORE      = rokusho_us + core_kuwagata_j
  +shingata = CORE + shingata_kabuto_j
  +navi     = CORE + shingata_kabuto_j + navi_kuwagata_j

Uso: python tools/roms.py            lista o que foi achado e o que falta
     from roms import rom_path, rom_bytes, has_rom
"""
import hashlib
import os
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROMS = {
    "rokusho_us": ("Medabots - Rokusho Version (USA)", "c4572428ea97b302f699a3b4eba2a1f0e87c1c9c"),
    "core_kuwagata_j": ("Medarot 2 Core - Kuwagata Version (Japan)", "868157b4d047f7f5f2a9c30577d082dc59b763b2"),
    "shingata_kabuto_j": ("Shingata Medarot - Kabuto Version (Japan)", "c14e7612698342ccd495e4aef764d4083c5a4765"),
    "navi_kuwagata_j": ("Medarot Navi - Kuwagata Version (Japan)", "de8de6734f0f990832988ea133fa05241946800e"),
    # legado (fora dos niveis): ferramentas antigas de arte/estudo que ainda abrem a versao europeia
    "metabee_eu": ("Medabots - Metabee Version (Europe)", "74b72bfff8bdd668069d73263d73419f23781646"),
}
PROFILE_ROM = {"rokusho_us": "rokusho_us", "metabee_eu": "metabee_eu"}   # pc/versions/<perfil>.json -> ROM
LEVELS = {"core": ["rokusho_us", "core_kuwagata_j"],
          "shingata": ["rokusho_us", "core_kuwagata_j", "shingata_kabuto_j"],
          "navi": ["rokusho_us", "core_kuwagata_j", "shingata_kabuto_j", "navi_kuwagata_j"]}


def _dirs():
    out = []
    if os.environ.get("MEDABOTS_ROMS"):
        out.append(Path(os.environ["MEDABOTS_ROMS"]))
    out += [ROOT / "roms", ROOT]
    return [d for d in out if d.is_dir()]


@lru_cache(maxsize=None)
def _index():
    """sha1 -> caminho, para todo .gba das pastas de ROM (com cache do sha1 por tamanho/data)."""
    found = {}
    for d in _dirs():
        for p in sorted(d.glob("*.gba")):
            if p.stat().st_size not in (8 << 20, 16 << 20, 32 << 20, 4 << 20):
                continue
            h = hashlib.sha1(p.read_bytes()).hexdigest()
            found.setdefault(h, p)
    return found


def has_rom(key):
    return ROMS[key][1] in _index()


def rom_path(key):
    name, sha = ROMS[key]
    p = _index().get(sha)
    if p is None:
        raise SystemExit(f"falta a ROM {name} (SHA1 {sha}); ponha o arquivo em {ROOT / 'roms'}")
    return p


@lru_cache(maxsize=None)
def rom_bytes(key):
    return rom_path(key).read_bytes()


def by_name(name):
    """ROM citada pelo nome de arquivo antigo (ex.: "graphics_source" dos JSON dos bots): o arquivo, se existir na raiz;
    senao a ROM de mesmo jogo achada pelo SHA1."""
    p = ROOT / name
    if p.exists():
        return p
    low = name.lower()
    for key, words in (("shingata_kabuto_j", ("shingata",)), ("navi_kuwagata_j", ("navi",)),
                       ("core_kuwagata_j", ("core", "kuwagata")), ("metabee_eu", ("metabee", "europe")),
                       ("rokusho_us", ("rokusho", "usa"))):
        if all(w in low for w in words):
            return rom_path(key)
    raise SystemExit(f"ROM desconhecida: {name}")


def level_available():
    """O maior nivel (core < shingata < navi) com todas as ROMs presentes, ou None."""
    best = None
    for lv in ("core", "shingata", "navi"):
        if all(has_rom(k) for k in LEVELS[lv]):
            best = lv
    return best


def main():
    for key, (name, sha) in ROMS.items():
        if key not in LEVELS["navi"] and not has_rom(key):
            continue                     # ROM de legado (ferramentas antigas): nao e pedida por nenhum nivel
        print(f"  {'ok  ' if has_rom(key) else 'FALTA'} {name}  (SHA1 {sha})" + (f"  -> {rom_path(key)}" if has_rom(key) else ""))
    lv = level_available()
    print(f"nivel possivel: {lv or 'nenhum (precisa ao menos de ' + ' + '.join(ROMS[k][0] for k in LEVELS['core']) + ')'}")
    return 0 if lv else 1


if __name__ == "__main__":
    sys.exit(main())
