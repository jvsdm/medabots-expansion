"""make_public_repo.py - Monta a pasta do repositorio publico (sem dados do jogo) a partir deste projeto.

Copia so o que e do projeto: ferramentas da build/instalacao/WPF, a camada overlay/, os dados proprios (falas, lutas,
personagens, encontros, lojas, esqueleto, bots do Shingata e do Navi) e os textos (README/INSTALL). Os dados do jogo
(data/maps, data/events, data/anim/seq|poses, data/bots/000-119) sao gerados da ROM de quem usa (tools/setup.py).

Uso: python tools/make_public_repo.py DESTINO   (a pasta e recriada; o .git dela, se houver, fica)
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["acha_fala", "anim_effects", "anim_molds", "anim_poses", "anim_render", "anim_seq", "battles_build", "build",
         "characters_build", "check_template", "codecs_gba", "core_bots", "decomp_build", "decomp_expand",
         "decomp_layout", "decomp_lift_binary", "decomp_make_eu", "decomp_navi", "encounters_plan", "events_build",
         "events_lift", "events_text", "export_manifest", "export_template", "form_art", "gen_signatures", "gfx_port",
         "make_ips", "maps_build", "maps_inventory", "maps_lift", "maps_new", "medarom", "mini_palette", "patches",
         "paths", "project_data", "roms", "setup", "story_check", "text_build", "wpf_events_to_files",
         "wpf_maps_to_files", "make_public_repo"]
DATA_FILES = ["data/core_bots.txt", "data/encounters_new.json", "data/encounter_mix.json", "data/expansion_bots.txt",
              "data/anim/molds.json", "data/anim/base_bots.json", "data/anim/seq_operands.json",
              "data/story/battles_new.json", "data/story/characters_new.json", "data/story/shops.json",
              "data/story/text_portraits.json", "data/wpf/project.medahack.json", "data/navi/navi_bots.json"]
DATA_DIRS = ["data/story/text", "data/navi/bots", "overlay", "pc/versions"]
PUBLIC_TEXT = ROOT / "docs/public"      # README.md, INSTALL.md, .gitignore, requirements.txt do repositorio publico


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    dst = Path(sys.argv[1]).resolve()
    if dst == ROOT or ROOT in dst.parents and not str(dst).startswith(str(ROOT / "build")):
        raise SystemExit("destino dentro do projeto: use uma pasta fora dele (ou em build/)")
    dst.mkdir(parents=True, exist_ok=True)
    for p in dst.iterdir():
        if p.name != ".git":
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    (dst / "tools").mkdir()
    for t in TOOLS:
        shutil.copyfile(ROOT / "tools" / f"{t}.py", dst / "tools" / f"{t}.py")
    for f in DATA_FILES:
        (dst / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / f, dst / f)
    for d in DATA_DIRS:
        shutil.copytree(ROOT / d, dst / d)
    # bots do projeto: os do Shingata (121-180; nomes e ajustes); os 000-119 vem da ROM (tools/core_bots.py)
    (dst / "data/bots").mkdir(parents=True, exist_ok=True)
    for f in sorted((ROOT / "data/bots").glob("*.json")):
        if 121 <= int(f.stem[:3]) <= 180:
            shutil.copyfile(f, dst / "data/bots" / f.name)
    for f in PUBLIC_TEXT.iterdir():
        shutil.copyfile(f, dst / f.name)
    n = sum(1 for p in dst.rglob("*") if p.is_file() and ".git" not in p.parts)
    print(f"{dst}: {n} arquivos")


if __name__ == "__main__":
    main()
