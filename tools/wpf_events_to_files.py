"""wpf_events_to_files.py - Roteiros editados no WPF (Modo Decomp) viram arquivos de data/events (M6 do
pc/research/MAPAS_EVENTOS_PLANO.md).

O editor de eventos do WPF grava o roteiro editado no projeto (data/wpf/project.medahack.json, "eventScriptPatches":
id + bytes). Aqui ele vira data/events/NNNN.evt (texto, tools/events_text.py) e sai do projeto. Id novo (alem dos do
jogo) ganha o seu NNNN.json. Roteiro que era compartilhado com outros ids: os outros continuam com o original. Roda no
comeco de cada build (tools/decomp_build.py); pode rodar a mao.

Uso: python tools/wpf_events_to_files.py [--project data/wpf/project.medahack.json] [--events data/events] [--dry-run]
"""
import argparse
import base64
import json
from pathlib import Path

from events_text import load_ops, write_event

ROOT = Path(__file__).resolve().parents[1]
NL = chr(10)


def convert(project, events, dry=False):
    if not project.exists():
        return []
    doc = json.loads(project.read_text(encoding="utf-8-sig"))
    patches = doc.get("eventScriptPatches", [])
    if not patches:
        return []
    ops, by_name = load_ops(events)
    done = []
    for p in sorted(patches, key=lambda x: x["eventId"]):
        eid = p["eventId"]
        data = base64.b64decode(p["scriptBytesBase64"])
        if data == bytes([0x06]) and (events / f"{eid:04d}.evt").exists():
            # "Add event here" do Maps cria um roteiro so com End no projeto; o .evt que ja existe (escrito na janela
            # Event scripts) e o de verdade
            done.append(f"roteiro {eid}: so End no projeto, fica o .evt")
            continue
        if dry:
            done.append(f"roteiro {eid}: {len(data)} B")
            continue
        done.append(write_event(events, eid, data, ops, by_name))
    if not dry:
        doc["eventScriptPatches"] = []
        project.write_text(json.dumps(doc, indent=2) + NL, encoding="utf-8")
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=str(ROOT / "data/wpf/project.medahack.json"))
    ap.add_argument("--events", default=str(ROOT / "data/events"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    done = convert(Path(a.project), Path(a.events), a.dry_run)
    print(f"{len(done)} roteiros do WPF {'a mover' if a.dry_run else 'movidos'} para data/events"
          + "".join(f"\n  {d}" for d in done))


if __name__ == "__main__":
    main()
