"""events_text.py - Roteiros de evento em texto (M2 do pc/research/MAPAS_EVENTOS_PLANO.md).

Disassembler e assembler dos roteiros de data/events: um comando por linha, saltos por rotulo.

Opcodes: data/events/_opcodes.json, gerado do EventOpcodeDefinitions.cs do Toolkit (--opcodes). Tamanhos conferidos
com a tabela antiga (LegacyEventOpcodeTable.cs) e com src/field/map_script.c da decomp.

Formato (.evt):
    ; comentario
    L_0012:                         rotulo (deslocamento no roteiro; o nome pode ser qualquer um)
    Show_Message_A bank=0, id=272   comando: nome e argumentos (nome=valor; a ordem e a do opcode)
    Jump jump=@L_0012               salto: @rotulo (ou numero cru, se o destino estiver fora do roteiro)
    Switch_Event_Counter @L_1, @L_2 tabela de saltos do opcode 0x2F
    .db 0x00, 0xFF                  bytes que nao sao comando alcancavel (enchimento, dados)
Argumentos com nome: direcao (north/south/west/east), parte (head/right/left/legs), movimento (south+3, unused);
o resto e numero (decimal ou 0x). Bank de mensagem e o valor do Toolkit (byte - 2).

Uso:
  python tools/events_text.py --opcodes                  gera data/events/_opcodes.json
  python tools/events_text.py --check                    ida e volta de todos os roteiros (bytes -> texto -> bytes)
  python tools/events_text.py --convert                  grava NNNN.evt ao lado de cada NNNN.json e tira o "bytes"
  python tools/events_text.py --show 272                 mostra o texto de um roteiro
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data/events"
TK = __import__("paths").TOOLKIT / "src/Medabots.Rom/Events"
NL = chr(10)

MULTI, END, GOTO = 0x2F, 0x06, 0x19
LEGACY = [1, 4, 4, 1, 2, 1, 1, 2, 2, 2, 2, 6, 6, 2, 1, 2, 5, 2, 3, 3, 1, 1, 3, 4, 3, 3, 3, 1, 2, 1, 2, 6,
          6, 5, 3, 3, 3, 2, 3, 4, 2, 2, 2, 6, 2, 3, 4, 5, 3, 2, 2, 4, 4, 2, 3, 3, 4, 4, 3, 3, 2, 2, 3, 3,
          2, 2, 1, 3, 2, 2, 1, 1, 2, 1, 3, 4, 4, 3, 4, 2, 4, 3, 3, 3, 1, 1, 1, 1, 1, 2, 2, 2, 3, 2, 2, 2,
          4, 1, 1, 4, 1, 1, 3, 3, 3, 3, 1, 2, 6, 3, 6, 3, 1, 1, 1, 1, 1, 1, 1, 1, 3, 2, 1, 4, 1, 2, 2, 2,
          1, 9, 1, 3, 2, 1, 9, 1, 3]
DIRS = ["north", "south", "west", "east"]
PARTS = ["head", "right", "left", "legs"]


# ---------------------------------------------------------------- opcodes
def gen_opcodes(events=EVENTS):
    src = (TK / "EventOpcodeDefinitions.cs").read_text(encoding="utf-8")
    ops = {}
    for chunk in re.split(r'(?=\[0x[0-9A-Fa-f]{2}\]\s*=\s*new EventOperationDefinition)', src)[1:]:
        m = re.match(r'\[0x([0-9A-Fa-f]{2})\]\s*=\s*new EventOperationDefinition\(\s*0x[0-9A-Fa-f]{2},\s*"(\w+)"', chunk)
        args = [{"name": a, "type": t} for a, t in re.findall(r'new\("(\w+)",\s*EventArgumentType\.(\w+)\)', chunk)]
        ops[f"0x{int(m[1], 16):02X}"] = {"name": m[2], "args": args}
    # correcoes e faltas do Toolkit, conferidas nos handlers de src/field/map_script.c (gMapScriptCommands)
    B = lambda n, t="Byte": {"name": n, "type": t}
    ops.update({
        "0x06": {"name": "End", "args": []},
        "0x19": {"name": "Goto_Event", "args": [B("event", "Short")]},
        "0x50": {"name": "Jump_If_Affinity_Below", "args": [B("who"), B("value"), B("jump")]},   # who 0 = ar, 1 = ka
        "0x52": {"name": "Jump_Random", "args": [B("unused1"), B("unused2")]},   # o C le 2 bytes e nao usa: salta (15 em 16) por cmd_args[2], resto do comando anterior (bug do jogo)
        "0x54": {"name": "Unused_54", "args": []},
        "0x67": {"name": "Skip_2", "args": [B("unused1"), B("unused2")]},   # le 2 bytes e nao usa
        "0x6A": {"name": "Unused_6A", "args": []},
        "0x77": {"name": "Unused_77", "args": []},
        "0x7F": {"name": "Follower_To_Actor", "args": [B("slot")]},
        "0x88": {"name": "Jump_Unless_Follower", "args": [B("jump", "Short")]},
    })
    ops = dict(sorted(ops.items()))
    seen = {}
    for k, o in ops.items():                     # nome repetido no Toolkit: o 2o ganha _<opcode>
        if o["name"] in seen:
            o["name"] = f"{o['name']}_{k[2:]}"
        seen[o["name"]] = k
    bad = []
    for k, o in ops.items():
        size = 1 + sum(2 if a["type"] == "Short" else 1 for a in o["args"])
        op = int(k, 16)
        if op < len(LEGACY) and LEGACY[op] != size and op != MULTI:
            bad.append(f"{k} {o['name']}: {size} != antigo {LEGACY[op]}")
    doc = {"_fonte": "git/Medabots-Romhacking-Toolkit/src/Medabots.Rom/Events/EventOpcodeDefinitions.cs",
           "_especiais": {"0x06": "fim", "0x19": "Goto_Event (id u16, big-endian; fim)",
                          "0x2F": "tabela de saltos (um byte por valor do contador de evento)"},
           "opcodes": ops}
    (events / "_opcodes.json").write_text(json.dumps(doc, indent=1) + NL, encoding="utf-8")
    print(f"{len(ops)} opcodes -> data/events/_opcodes.json")
    for b in bad:
        print("  tamanho diferente:", b)


def load_ops(events=EVENTS):
    d = json.loads((events / "_opcodes.json").read_text(encoding="utf-8"))["opcodes"]
    ops = {int(k, 16): v for k, v in d.items()}
    by_name = {v["name"]: k for k, v in ops.items()}
    return ops, by_name


def arg_size(a):
    return 2 if a["type"] == "Short" else 1


def op_size(o):
    return 1 + sum(arg_size(a) for a in o["args"])


# ---------------------------------------------------------------- disassembler
def multi_entries(data, off):
    """Mesma regra do EventScriptReader do Toolkit: a tabela acaba quando o menor deslocamento == numero de entradas."""
    js = [data[off + 1], data[off + 2]]
    for i in range(2, 8):
        if min(js) == len(js):
            return js[:min(js)]
        js.append(data[off + 1 + i])
    return js


def decode(data, off, ops, n):
    """Um comando em `off`: (tamanho, op, valores, destinos) ou None (desconhecido ou passa do fim)."""
    op = data[off]
    if op == MULTI:
        if off + 3 > n:
            return None
        js = multi_entries(data, off)
        if off + 1 + len(js) > n:
            return None
        return (1 + len(js), op, js, [off + 1 + j for j in js])
    o = ops.get(op)
    if o is None or off + op_size(o) > n:
        return None
    vals, cur, tgt = [], off + 1, []
    for a in o["args"]:
        v = data[cur] << 8 | data[cur + 1] if arg_size(a) == 2 else data[cur]
        vals.append(v)
        if a["name"] == "jump":
            tgt.append(off + 1 + (v - 0x10000 if arg_size(a) == 2 and v >= 0x8000 else v))
        cur += arg_size(a)
    return (op_size(o), op, vals, tgt)


def parse(data, ops):
    """Comandos alcancaveis a partir do inicio: {off: (tamanho, op, valores, destinos)}."""
    found, todo, seen = {}, [0], set()
    n = len(data)
    while todo:
        off = todo.pop()
        while 0 <= off < n and off not in seen:
            seen.add(off)
            d = decode(data, off, ops, n)
            if d is None:
                break                                      # desconhecido: o resto vira .db
            found[off] = d
            todo += d[3]
            if d[1] in (MULTI, GOTO, END):
                break
            off += d[0]
    return found


def dead_code(data, ops, a, b):
    """Trecho sem chamador [a, b): decodifica em linha enquanto der; devolve {off: comando}."""
    if not any(data[a:b]):
        return {}
    out, off = {}, a
    while off < b and any(data[off:b]):          # zeros do fim = enchimento
        d = decode(data, off, ops, b)
        if d is None:
            break
        out[off] = d
        off += d[0]
    return out


def fmt_arg(a, v):
    t = a["type"]
    if t == "Direction" and v < 4:
        return DIRS[v]
    if t == "Part" and v < 4:
        return PARTS[v]
    if t == "Move":
        if v == 0xFF:
            return "unused"
        if v & 0xF0 in (0x00, 0x10, 0x20, 0x30):
            return f"{DIRS[v >> 4]}+{v & 0xF}"
    if t == "EventBank":
        return str(v - 2)
    if t in ("BattleModeFlags", "PostBattleModeFlags"):
        return f"0x{v:02X}"
    return str(v)


def disasm(data, ops):
    found = parse(data, ops)
    # comandos em ordem, sem sobreposicao
    insts, end = [], 0
    for off in sorted(found):
        if off >= end:
            insts.append(off)
            end = off + found[off][0]
    # trechos sem chamador entre os comandos: decodificados tambem (marcados com comentario)
    dead, deadrun, prev = {}, set(), 0
    for off in insts + [len(data)]:
        if off > prev:
            dc = dead_code(data, ops, prev, off)
            dead.update(dc)
            if dc:
                deadrun.add(min(dc))
        if off < len(data):
            prev = off + found[off][0]
    found.update(dead)
    insts = sorted(set(insts) | set(dead))
    starts = set(insts)
    labels = sorted({t for off in insts for t in found[off][3] if t in starts})
    lab = {t: f"L_{t:04X}" for t in labels}
    out, pos = [], 0

    def flush(upto):
        nonlocal pos
        while pos < upto:
            chunk = data[pos:min(upto, pos + 16)]
            out.append(".db " + ", ".join(f"0x{b:02X}" for b in chunk))
            pos += len(chunk)

    for off in insts:
        flush(off)
        if off in deadrun:
            out.append("; sem chamador dentro deste roteiro")
        if off in lab:
            out.append(f"{lab[off]}:")
        sz, op, vals, tgt = found[off]
        if op == MULTI:
            out.append("Switch_Event_Counter " + ", ".join(
                f"@{lab[t]}" if t in lab else str(v) for v, t in zip(vals, tgt)))
        elif op == GOTO:
            out.append(f"{ops[op]['name'] if op in ops else 'Goto_Event'} event={vals[0]}")
        else:
            o, parts, k = ops[op], [], 0
            for a, v in zip(o["args"], vals):
                if a["name"] == "jump":
                    t = tgt[k]
                    k += 1
                    parts.append(f"jump=@{lab[t]}" if t in lab else f"jump={t - off - 1}")
                else:
                    parts.append(f"{a['name']}={fmt_arg(a, v)}")
            out.append(o["name"] + (" " + ", ".join(parts) if parts else ""))
        pos = off + sz
    flush(len(data))
    for t in lab:              # rotulo no fim exato do roteiro (nao acontece hoje)
        assert t < len(data), t
    return NL.join(out) + NL


# ---------------------------------------------------------------- assembler
def num(s):
    s = s.strip()
    return int(s, 0)


def parse_arg(a, s):
    t = a["type"]
    if t == "Direction" and s in DIRS:
        return DIRS.index(s)
    if t == "Part" and s in PARTS:
        return PARTS.index(s)
    if t == "Move":
        if s == "unused":
            return 0xFF
        m = re.fullmatch(r"(north|south|west|east)\+(\d+)", s)
        if m:
            return DIRS.index(m[1]) << 4 | int(m[2])
    if t == "EventBank":
        return num(s) + 2
    return num(s)


def asm(text, ops, by_name, where=""):
    """Duas passagens: tamanho e rotulos; depois os bytes."""
    items, labels, pos = [], {}, 0
    for ln, raw in enumerate(text.split(NL), 1):
        line = raw.split(";")[0].strip()
        if not line:
            continue
        ctx = f"{where}:{ln}"
        if line.endswith(":") and " " not in line:
            labels[line[:-1]] = pos
            continue
        if line.startswith(".db"):
            bs = [num(x) for x in line[3:].split(",") if x.strip()]
            items.append((pos, "db", bs, ctx))
            pos += len(bs)
            continue
        name, _, rest = line.partition(" ")
        args = [x.strip() for x in rest.split(",")] if rest.strip() else []
        if name == "Switch_Event_Counter":
            items.append((pos, "multi", args, ctx))
            pos += 1 + len(args)
            continue
        if name == "Goto_Event" and GOTO not in ops:
            items.append((pos, "op", (GOTO, args), ctx))
            pos += 3
            continue
        if name not in by_name:
            raise SystemExit(f"{ctx}: comando desconhecido {name}")
        op = by_name[name]
        items.append((pos, "op", (op, args), ctx))
        pos += 3 if op == GOTO else op_size(ops[op])
    out = bytearray()

    def target(s, at, ctx):
        if s.startswith("@"):
            if s[1:] not in labels:
                raise SystemExit(f"{ctx}: rotulo {s[1:]} nao existe")
            return labels[s[1:]] - (at + 1)
        return None

    for at, kind, val, ctx in items:
        assert len(out) == at
        if kind == "db":
            out += bytes(val)
        elif kind == "multi":
            out.append(MULTI)
            for s in val:
                d = target(s, at, ctx)
                d = num(s) if d is None else d
                if not 0 <= d <= 0xFF:
                    raise SystemExit(f"{ctx}: salto da tabela fora do alcance ({d})")
                out.append(d)
        else:
            op, args = val
            out.append(op)
            if op == GOTO:
                v = num(args[0].split("=")[-1])
                out += bytes([v >> 8, v & 0xFF])
                continue
            o = ops[op]
            if len(args) != len(o["args"]):
                raise SystemExit(f"{ctx}: {o['name']} pede {len(o['args'])} argumentos, veio {len(args)}")
            for a, s in zip(o["args"], args):
                if "=" in s:
                    k, _, s = s.partition("=")
                    if k.strip() != a["name"]:
                        raise SystemExit(f"{ctx}: argumento {k.strip()} fora de ordem (esperado {a['name']})")
                    s = s.strip()
                v = target(s, at, ctx) if a["name"] == "jump" else None
                if v is None:
                    v = parse_arg(a, s)
                sz = arg_size(a)
                if a["name"] == "jump":
                    if sz == 1 and not 0 <= v <= 0xFF:
                        raise SystemExit(f"{ctx}: salto curto fora do alcance ({v}); use Relative_Long_Jump")
                    if sz == 2 and not -0x8000 <= v <= 0xFFFF:
                        raise SystemExit(f"{ctx}: salto fora do alcance ({v})")
                    v &= 0xFFFF if sz == 2 else 0xFF
                if not 0 <= v < (1 << 8 * sz):
                    raise SystemExit(f"{ctx}: valor {v} nao cabe em {sz} byte(s)")
                out += bytes([v >> 8, v & 0xFF]) if sz == 2 else bytes([v])
    return bytes(out)


# ---------------------------------------------------------------- arquivos
def script_bytes(events, doc, ops=None, by_name=None):
    """Bytes do roteiro de um NNNN.json: do .evt (texto) ou do hex antigo."""
    if "bytes" in doc:
        return bytes.fromhex(doc["bytes"])
    evt = events / doc["script"]
    if ops is None:
        ops, by_name = load_ops(events)
    return asm(evt.read_text(encoding="utf-8"), ops, by_name, evt.name)


def check(events):
    ops, by_name = load_ops(events)
    n = bad = 0
    total = unread = 0
    for f in sorted(events.glob("[0-9]*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "shared_with" in d:
            continue
        data = script_bytes(events, d, ops, by_name)
        t = disasm(data, ops)
        n += 1
        total += len(data)
        unread += sum(len(l.split(",")) for l in t.split(NL) if l.startswith(".db"))
        if asm(t, ops, by_name, f.name) != data:
            bad += 1
            if bad <= 5:
                print("DIFERENTE:", f.name)
    print(f"{n} roteiros, {bad} diferentes; {total - unread}/{total} bytes como comando, {unread} em .db")
    return bad == 0


def convert(events):
    ops, by_name = load_ops(events)
    k = 0
    for f in sorted(events.glob("[0-9]*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "bytes" not in d:
            continue
        data = bytes.fromhex(d["bytes"])
        t = f"; roteiro {d['id']} (banco {d['bank']}, inicio 0x{d['start']:04X})" + NL + disasm(data, ops)
        assert asm(t, ops, by_name) == data, f.name
        evt = f.with_suffix(".evt")
        evt.write_text(t, encoding="utf-8")
        del d["bytes"]
        d["script"] = evt.name
        f.write_text(json.dumps(d) + NL, encoding="utf-8")
        k += 1
    print(f"{k} roteiros em texto (.evt)")


def new_event(events, name=None):
    """Roteiro novo com o proximo id livre (depois dos 2.288 do jogo). O montador poe num banco novo e aumenta o
    cabecalho. Flag e contador de evento: o jogo guarda ate o id 2.999 (gFieldWork, 0x5DC bytes)."""
    n = json.loads((events / "_blob.json").read_text(encoding="utf-8"))["count"]
    while (events / f"{n:04d}.json").exists():
        n += 1
    if n >= 3000:
        raise SystemExit("ids de evento com flag so ate 2999 (gFieldWork)")
    evt = events / f"{n:04d}.evt"
    evt.write_text(f"; roteiro {n} (novo){' - ' + name if name else ''}" + NL + "End" + NL, encoding="utf-8")
    (events / f"{n:04d}.json").write_text(json.dumps({"id": n, "script": evt.name, **({"name": name} if name else {})})
                                          + NL, encoding="utf-8")
    return n


def read_doc(events, eid):
    """O NNNN.json do roteiro, seguindo o "shared_with" ate o dono."""
    d = json.loads((events / f"{eid:04d}.json").read_text(encoding="utf-8"))
    if "shared_with" in d:
        d = json.loads((events / f"{d['shared_with']:04d}.json").read_text(encoding="utf-8"))
    return d


def write_event(events, eid, data, ops=None, by_name=None, note="editado no WPF"):
    """Grava os bytes de um roteiro como NNNN.evt (o WPF chama ao editar na aba Events; wpf_events_to_files tambem).
    Os comentarios do topo do .evt antigo ficam; rotulos voltam a ser L_xxxx. Roteiro compartilhado: os outros ids
    ficam com o original (o 1o deles vira o dono) e o editado vai para um banco novo."""
    if ops is None:
        ops, by_name = load_ops(events)
    jf = events / f"{eid:04d}.json"
    if jf.exists():
        d = json.loads(jf.read_text(encoding="utf-8"))
    else:
        if not (events / f"{eid - 1:04d}.json").exists():
            raise SystemExit(f"roteiro {eid}: id novo precisa vir logo depois do ultimo (sem buraco)")
        d = {"id": eid}
    head = []
    if "script" in d and (events / d["script"]).exists():
        for line in (events / d["script"]).read_text(encoding="utf-8").split(NL):
            if not line.startswith(";"):
                break
            head.append(line)
    text = NL.join(head or [f"; roteiro {eid} ({note})"]) + NL + disasm(data, ops)
    assert asm(text, ops, by_name) == data, f"roteiro {eid}: texto nao volta igual"
    group = sorted(int(f.stem) for f in events.glob("[0-9]*.json")
                   if json.loads(f.read_text(encoding="utf-8")).get("shared_with") == eid)
    if group and "script" in d:
        heir = group[0]
        (events / f"{heir:04d}.evt").write_text((events / d["script"]).read_text(encoding="utf-8"), encoding="utf-8")
        hd = {"id": heir, "bank": d["bank"], "start": d["start"], "script": f"{heir:04d}.evt"}
        (events / f"{heir:04d}.json").write_text(json.dumps(hd) + NL, encoding="utf-8")
        for o in group[1:]:
            (events / f"{o:04d}.json").write_text(json.dumps({"id": o, "bank": d["bank"], "start": d["start"],
                                                              "shared_with": heir}) + NL, encoding="utf-8")
        d.pop("bank", None)          # o editado vai para um banco novo (o lugar original ficou com o grupo)
        d.pop("start", None)
    if "shared_with" in d:           # usava o roteiro de outro: o lugar e do dono, o editado vai para um banco novo
        d.pop("shared_with")
        d.pop("bank", None)
        d.pop("start", None)
    d.pop("bytes", None)
    (events / f"{eid:04d}.evt").write_text(text, encoding="utf-8")
    d["script"] = f"{eid:04d}.evt"
    jf.write_text(json.dumps(d) + NL, encoding="utf-8")
    return f"roteiro {eid}: {len(data)} B" + (f" (o original fica com {len(group)} ids)" if group else "")


def callers(events, eid):
    """Quem chama o roteiro: NPC/gatilho de data/maps, NPC ainda no projeto do WPF, Goto_Event de outro roteiro."""
    out = []
    maps = events.parent / "maps"
    for f in sorted(maps.glob("area_*/npcs.json")):
        for n in json.loads(f.read_text(encoding="utf-8"))["npcs"]:
            if n["event"] == eid:
                out.append(f"{f.parent.name} ({n['x']},{n['y']})")
    proj = events.parent / "wpf" / "project.medahack.json"
    if proj.exists():
        for m in json.loads(proj.read_text(encoding="utf-8-sig")).get("mapEntitySpawnPatches", []):
            for r in m.get("records", []):
                if r["recordKindAndEventId"] & 0x0FFF == eid:
                    out.append(f"area_{m['mapId']:03d} ({r['tileX']},{r['tileY']}) no projeto do WPF")
    goto = re.compile(rf"^Goto_Event\s+event={eid}\s*$", re.M)
    for f in sorted(events.glob("*.evt")):
        if f.stem.lstrip("0") != str(eid) and goto.search(f.read_text(encoding="utf-8")):
            out.append(f"Goto_Event no roteiro {int(f.stem)}")
    return out


def delete_event(events, eid):
    """Apaga um roteiro novo. So o ultimo id (a build le os ids em sequencia, sem buraco), nunca um do jogo, e so se
    ninguem o chama."""
    count = json.loads((events / "_blob.json").read_text(encoding="utf-8"))["count"]
    if eid < count:
        raise SystemExit(f"roteiro {eid} e do jogo (ids 0-{count - 1}): nao se apaga; deixe so End se nao quiser usar")
    if not (events / f"{eid:04d}.json").exists():
        raise SystemExit(f"roteiro {eid} nao existe")
    if (events / f"{eid + 1:04d}.json").exists():
        raise SystemExit(f"so o ultimo roteiro pode ser apagado (existe o {eid + 1}; os ids nao podem ter buraco)")
    who = callers(events, eid)
    if who:
        raise SystemExit(f"roteiro {eid} ainda e chamado por: " + "; ".join(who))
    for suf in (".evt", ".json"):
        (events / f"{eid:04d}{suf}").unlink(missing_ok=True)
    return eid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bytes", type=int, nargs="+", help="bytes montados destes roteiros, em JSON {id: hex} (o WPF le)")
    ap.add_argument("--write", type=int, help="grava o roteiro com os bytes em hex da entrada padrao (o WPF chama)")
    ap.add_argument("--delete", type=int, help="apaga um roteiro novo (so o ultimo, sem chamador)")
    ap.add_argument("--new", nargs="?", const="", help="cria um roteiro novo (nome opcional) e mostra o id")
    ap.add_argument("--check-one", type=int, help="monta so este roteiro (o WPF chama ao salvar)")
    ap.add_argument("--events", default=str(EVENTS))
    ap.add_argument("--opcodes", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--convert", action="store_true")
    ap.add_argument("--show", type=int)
    a = ap.parse_args()
    ev = Path(a.events)
    if a.bytes:
        ops, by_name = load_ops(ev)
        print(json.dumps({str(i): script_bytes(ev, read_doc(ev, i), ops, by_name).hex()
                          for i in a.bytes if (ev / f"{i:04d}.json").exists()}))
    if a.write is not None:
        import sys
        print(write_event(ev, a.write, bytes.fromhex(sys.stdin.read().strip())))
    if a.delete is not None:
        print(f"roteiro {delete_event(ev, a.delete)} apagado")
    if a.check_one is not None:
        d = json.loads((ev / f"{a.check_one:04d}.json").read_text(encoding="utf-8"))
        if "shared_with" in d:
            d = json.loads((ev / f"{d['shared_with']:04d}.json").read_text(encoding="utf-8"))
        print(f"roteiro {a.check_one}: ok, {len(script_bytes(ev, d))} bytes")
    if a.new is not None:
        print(f"roteiro novo: {new_event(ev, a.new or None)}")
    if a.opcodes:
        gen_opcodes(ev)
    if a.check:
        raise SystemExit(0 if check(ev) else 1)
    if a.convert:
        convert(ev)
    if a.show is not None:
        ops, _ = load_ops(ev)
        d = json.loads((ev / f"{a.show:04d}.json").read_text(encoding="utf-8"))
        if "shared_with" in d:
            print(f"; compartilha o roteiro {d['shared_with']}")
            d = json.loads((ev / f"{d['shared_with']:04d}.json").read_text(encoding="utf-8"))
        print(disasm(script_bytes(ev, d), ops), end="")


if __name__ == "__main__":
    main()
