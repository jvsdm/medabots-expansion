"""
decomp_make_eu.py - Gera a arvore da descompilacao para a Rokusho EU a partir da USA (rommerhacks/medabots-rokusho).

Uso: python tools/decomp_make_eu.py [--src build/scratch/decomp_rok] [--dst build/scratch/decomp_eu]
     depois, na arvore gerada: make compare (precisa do agbcc instalado em tools/agbcc; ver pc/research/DECOMP_C.md)

O que faz (pc/research/DECOMP_C.md, "Alvo EU"):
  1. copia a arvore (sem build/), poe a ROM EU como baserom.gba e o sha1 dela em rom.sha1;
  2. mapa fino USA->EU (pedacos de 32 B achados na EU perto do previsto, ponteiros mascarados);
  3. remapeia todo `.incbin "baserom.gba", o, s` (dados, som, graficos, cabecalho, libgcc) para o endereco EU, com o
     tamanho = distancia ate o proximo bloco na EU; remapeia config/data_ptrs/*.tsv e os marcadores `@ data at`;
  4. as funcoes C que mudaram na EU (FUNCS) viram NAKED com os bytes da EU (`-DEU_BUILD`), mesmo nome.
Fora do mapa ('?') o endereco sai do vizinho da esquerda (+1 byte), e o script avisa.
"""
import argparse
import bisect
import hashlib
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EU_ROM = ROOT / "Medabots - Rokusho (Europe).gba"
GBA = 0x08000000
# funcoes que mudam na Rokusho EU (DECOMP_US2EU.tsv: sem par ou com o vizinho deslocado)
AUTO = True   # --fixed-funcs: usa a lista abaixo (a que foi achada a mao para a Rokusho EU)
FUNCS = ["team_has_part_equipped", "field_effect_run", "vehicle_check_usable", "field_debug_update_page",
         "field_debug_draw_page", "title_menu_start_new_game", "validate_save_data",
         "medapart_trade_init_sprite_tree", "load_medapart_sprite_animation", "multiplayer_battle_sync_update"]


def masked(b):
    o = bytearray(b)
    for i in range(0, len(b) - 3, 4):
        if b[i + 3] in (8, 9):
            o[i:i + 4] = b"\0\0\0\0"
    return bytes(o)


def fine_map(us, eu, C=32, WIN=0x3000):
    um, em = masked(us), masked(eu)
    delta, starts, deltas = 0, [], []
    for o in range(0, len(us) - C, C):
        b = um[o:o + C]
        if len(set(b)) <= 2:
            continue
        p = o + delta
        lo, hi = max(0, p - WIN), min(len(em), p + WIN + C)
        best, k = -1, em.find(b, lo, hi)
        while k >= 0:
            if best < 0 or abs(k - p) < abs(best - p):
                best = k
            k = em.find(b, k + 1, hi)
        if best < 0:
            j = em.find(b)
            if j >= 0 and em.find(b, j + 1) < 0:
                best = j
        if best >= 0:
            delta = best - o
            starts.append(o)
            deltas.append(delta)
    return starts, deltas


class Mapper:
    def __init__(self, us, eu):
        self.us, self.eu = us, eu
        self.starts, self.deltas = fine_map(us, eu)
        self.warn = 0
        self.um, self.em = masked(us), masked(eu)

    def delta_at(self, a):
        """delta do pedaco que contem a (ou o anterior); refina a fronteira byte a byte quando o delta muda."""
        i = bisect.bisect_right(self.starts, a) - 1
        if i < 0:
            return 0
        d = self.deltas[i]
        if i + 1 < len(self.deltas) and self.deltas[i + 1] != d and a >= self.starts[i]:
            # entre dois pedacos de deltas diferentes: se o byte bate com o delta da direita, usa o da direita
            d2 = self.deltas[i + 1]
            if self.starts[i + 1] - a <= 64 and 0 <= a + d2 < len(self.eu) and self.eu[a + d2] == self.us[a] \
                    and self.eu[a + d] != self.us[a]:
                return d2
        return d

    def map(self, a):
        return a + self.delta_at(a)


def remap_incbins(text, M, stats):
    """Remapeia blocos contiguos de .incbin conferindo o conteudo: um bloco so fica num endereco EU onde os bytes
    batem (ponteiros mascarados); bloco que mudou na EU ocupa o espaco entre os vizinhos que bateram."""
    pat = re.compile(r'(\.incbin\s+"baserom\.gba",\s*)(0x[0-9A-Fa-f]+|\d+)(,\s*)(0x[0-9A-Fa-f]+|\d+)')
    ms = list(pat.finditer(text))
    blk = [(int(m.group(2), 0), int(m.group(4), 0)) for m in ms]
    um, em = M.um, M.em

    def fits(o, s, e):
        n = min(s, 256)
        return 0 <= e and e + n <= len(em) and em[e:e + n] == um[o:o + n]

    starts = [None] * len(blk)
    # posicao forcada pelo codigo EU (literal pools): mais forte que o conteudo
    for k, m in enumerate(ms):
        prev_end = ms[k - 1].end() if k else 0
        for lab in re.findall(r'^\s*(\w+):\s*$', text[prev_end:m.start()], re.M):
            if lab in FORCED:
                starts[k] = FORCED[lab]
    for k, (o, s) in enumerate(blk):
        if starts[k] is not None:
            continue
        cands = [M.map(o)]
        if k and starts[k - 1] is not None and blk[k - 1][0] + blk[k - 1][1] == o:
            cands.insert(0, starts[k - 1] + blk[k - 1][1])
        for c in cands:
            if fits(o, s, c):
                starts[k] = c
                break
    # 2a passada (de tras para frente): bloco que invade o seguinte ou nao bateu tenta ficar colado ao seguinte
    for k in range(len(blk) - 2, -1, -1):
        o, s = blk[k]
        if blk[k + 1][0] != o + s or starts[k + 1] is None:
            continue
        nxt = starts[k + 1]
        if starts[k] is None or starts[k] + 1 > nxt or starts[k] + s > nxt + 0x10000:
            c = nxt - s
            if fits(o, s, c):
                starts[k] = c
    for k, (o, s) in enumerate(blk):
        if starts[k] is None:   # mudou na EU: comeca onde o anterior acaba (o tamanho sai do seguinte)
            stats["mudou"] += 1
            if k and blk[k - 1][0] + blk[k - 1][1] == o and starts[k - 1] is not None:
                starts[k] = starts[k - 1] + blk[k - 1][1] if fits(*blk[k - 1], starts[k - 1]) else M.map(o)
            else:
                starts[k] = M.map(o)
    out, last = [], 0
    for k, m in enumerate(ms):
        o, s = blk[k]
        eo = starts[k]
        if k + 1 < len(ms) and blk[k + 1][0] == o + s:
            ee = starts[k + 1]
        elif o + s == len(M.us):
            ee = len(M.eu)                     # espaco livre ate o fim da ROM
        else:
            ee = M.map(o + s - 1) + 1
        if ee - eo != s:
            stats["tamanho"] += 1
            if ee - eo <= 0:
                stats["ruim"].append((o, s, eo, ee))
        between = text[last:m.start()]
        for lab in re.findall(r'^\s*(\w+):\s*$', between, re.M):   # rotulos logo antes do bloco
            LABELS[lab] = (o, eo)
        out.append(between + f"{m.group(1)}0x{eo:X}{m.group(3)}0x{ee - eo:X}")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


LABELS = {}   # rotulo de dado -> (endereco USA, endereco EU), preenchido por remap_incbins
FORCED = {}   # rotulo -> endereco EU (offset de arquivo) lido nos literal pools do codigo EU


def forced_from_code(src, M, code_end=0x750D8):
    """Rotulos de dado citados no codigo: o literal pool USA aponta para o rotulo; a mesma palavra no codigo EU
    (o codigo ja esta alinhado pelo mapa) da o endereco EU. Fica o voto da maioria."""
    us_lab = {}
    for f in list(src.glob("data/*.s")) + list(src.glob("sound/*.s")) + list(src.glob("graphics/*.s")):
        t = f.read_text()
        for m in re.finditer(r'^\s*(\w+):\s*\n(?:\s*\.global\s+\w+\s*\n)?\s*\.incbin\s+"baserom\.gba",\s*(0x[0-9A-Fa-f]+)',
                             t, re.M):
            us_lab[int(m.group(2), 16) + GBA] = m.group(1)
    votes = {}
    us, eu = M.us, M.eu
    for p in range(0, code_end, 4):
        w = int.from_bytes(us[p:p + 4], "little")
        if w in us_lab:
            q = M.map(p)
            if q % 4 == 0 and q + 4 <= len(eu):
                v = int.from_bytes(eu[q:q + 4], "little") - GBA
                votes.setdefault(us_lab[w], {}).setdefault(v, 0)
                votes[us_lab[w]][v] += 1
    for lab, vs in votes.items():
        v, n = max(vs.items(), key=lambda kv: kv[1])
        if 0 <= v < len(eu):
            FORCED[lab] = v
    return FORCED


def remap_target(sym, M):
    """`rotulo+0xN` aponta para rotulo_US + N; na EU vira rotulo + (destino EU - rotulo EU)."""
    m = re.match(r'^(\w+)\s*\+\s*(0x[0-9A-Fa-f]+)$', sym.strip())
    if not m or m.group(1) not in LABELS:
        return sym
    us_l, eu_l = LABELS[m.group(1)]
    n = int(m.group(2), 16)
    eu_t = M.map(us_l + n)
    return f"{m.group(1)}+0x{eu_t - eu_l:X}" if eu_t != eu_l else m.group(1)


def remap_markers(text, M):
    return re.sub(r'(@ data at )(0x[0-9A-Fa-f]+)', lambda m: m.group(1) + "0x%08X" % (M.map(int(m.group(2), 16) - GBA) + GBA), text)


def func_ranges(src, M):
    """US (inicio, fim) e EU (inicio, fim) de cada funcao de FUNCS (config/functions.tsv)."""
    fns = []
    for line in (src / "config/functions.tsv").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        a, s, n = line.split("\t")[:3]
        fns.append((int(a, 16) - GBA, int(s, 16), n))
    fns.sort()
    mods = {}
    for line in (src / "config/functions.tsv").read_text().splitlines():
        if not line.startswith("#") and line.strip():
            p = line.split("\t")
            mods[p[2]] = p[3] if len(p) > 3 else "-"
    # inicio EU de cada funcao, uma vez, em ordem: palpite = inicio EU da anterior + distancia USA (ou o mapa, se
    # a anterior mudou de tamanho); chave = ate 64 B da funcao (ponteiros e BL mascarados)
    # chamadas (BL) do codigo: o destino EU da mesma chamada no codigo EU e prova do inicio da funcao chamada
    starts_us = {a for a, _, _ in fns}
    votes = {}
    us, eu = M.us, M.eu
    for p in range(0, 0x750D8, 2):
        h1 = us[p] | us[p + 1] << 8
        h2 = us[p + 2] | us[p + 3] << 8
        if (h1 >> 11) == 0x1E and (h2 >> 11) == 0x1F:
            off = ((h1 & 0x7FF) << 12 | (h2 & 0x7FF) << 1)
            if off & 0x400000:
                off -= 0x800000
            t = p + 4 + off
            if t in starts_us:
                q = M.map(p)
                e1 = eu[q] | eu[q + 1] << 8
                e2 = eu[q + 2] | eu[q + 3] << 8
                if (e1 >> 11) == 0x1E and (e2 >> 11) == 0x1F:
                    eo = ((e1 & 0x7FF) << 12 | (e2 & 0x7FF) << 1)
                    if eo & 0x400000:
                        eo -= 0x800000
                    votes.setdefault(t, {}).setdefault(q + 4 + eo, 0)
                    votes[t][q + 4 + eo] += 1
    called = {t: max(v.items(), key=lambda kv: kv[1])[0] for t, v in votes.items()}
    es = []
    for i, (a, s, n) in enumerate(fns):
        guess = M.map(a - 1) + 1 if a else 0
        if i and es[i - 1] is not None:
            g2 = es[i - 1] + (a - fns[i - 1][0])
            if bl_masked(M.us[a:a + min(s, 64)]) == bl_masked(M.eu[g2:g2 + min(s, 64)]):
                guess = g2
        e = locate(M, a, guess, n=max(4, min(s, 64)))
        k = min(s, 64)
        if bl_masked(us[a:a + k]) != bl_masked(eu[e:e + k]) and a in called \
                and len(votes[a]) == 1 and sum(votes[a].values()) >= 2:
            e = called[a]   # a propria funcao mudou: vale o destino unanime das chamadas
        es.append(e)
    if AUTO:   # funcao C que muda: bytes (ponteiros e BL mascarados) ou distancia ate a seguinte diferentes na EU
        FUNCS.clear()
        for i, (a, s, n) in enumerate(fns[:-1]):
            if mods.get(n, "-") == "-":
                continue   # crt0/bibliotecas em asm
            nxt = fns[i + 1][0]
            adjacent = nxt - (a + s) < 0x10   # seguinte colada (senao vem dado no meio: so o alinhamento muda)
            if bl_masked(M.us[a:a + s]) != bl_masked(M.eu[es[i]:es[i] + s]) or \
                    (adjacent and es[i + 1] - es[i] != nxt - a):
                FUNCS.append(n)
    out = {}
    for i, (a, s, n) in enumerate(fns):
        if n in FUNCS:
            out[n] = (es[i], es[i + 1] - es[i])
    return out


def bl_masked(b):
    o = bytearray(masked(b))
    for i in range(0, len(o) - 3, 2):
        if (o[i + 1] >> 3) == 0x1E and (o[i + 3] >> 3) == 0x1F:
            o[i:i + 4] = b"\0\0\0\0"
    return bytes(o)


def locate(M, us_addr, guess, n=16, win=0x400):
    """Inicio EU da funcao que comeca em us_addr: os primeiros n bytes (ponteiros e BL mascarados) mais perto do
    palpite; sem achado, o palpite."""
    key = bl_masked(M.us[us_addr:us_addr + n])
    lo, hi = max(0, guess - win), guess + win
    em = bl_masked(M.eu[lo:hi + n])
    best, k = None, em.find(key)
    while k >= 0:
        if k % 2 == 0 and (best is None or abs(lo + k - guess) < abs(best - guess)):
            best = lo + k
        k = em.find(key, k + 1)
    return guess if best is None else best


def wrap_function(code, name, eu_off, eu_size):
    """Troca a definicao da funcao por: #ifdef EU_BUILD NAKED (bytes EU) #else original #endif."""
    # so definicao: comeca na coluna 0 com o tipo (nao `if (...)`, chamada indentada etc.)
    m = re.search(r'^((?!if\b|while\b|for\b|switch\b|return\b|else\b)[A-Za-z_][\w \t*]*\b' + re.escape(name)
                  + r'\s*\([^;{]*\)\s*)\{', code, re.M)
    if not m:
        return None
    start = m.start()
    depth, i = 0, m.end() - 1
    while i < len(code):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    sig = m.group(1).strip()
    sig = re.sub(r'^static\s+', 'static ', sig)
    naked = (f'#ifdef EU_BUILD\nNAKED {sig} {{\n    asm(".incbin \\"baserom.gba\\", 0x{eu_off:X}, 0x{eu_size:X}");\n}}\n'
             f'#else\n')
    return code[:start] + naked + code[start:i + 1] + "\n#endif" + code[i + 1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "build/scratch/decomp_rok"))
    ap.add_argument("--dst", default=str(ROOT / "build/scratch/decomp_eu"))
    ap.add_argument("--ptrs", action="store_true",
                    help="remapeia os ponteiros dos dados como simbolos (modding; ainda erra no texto que muda na EU)")
    ap.add_argument("--rom", default=str(EU_ROM), help="ROM EU alvo (Rokusho ou Metabee)")
    ap.add_argument("--fixed-funcs", action="store_true", help="usa FUNCS fixa (Rokusho EU) em vez de detectar")
    a = ap.parse_args()
    global AUTO
    AUTO = not a.fixed_funcs
    src, dst = Path(a.src), Path(a.dst)
    us = (src / "baserom.gba").read_bytes()
    eu = Path(a.rom).read_bytes()
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("build", "build_modern", ".git", "*.gba", "*.elf", "*.map",
                                                            "*.sav"))
    (dst / "baserom.gba").write_bytes(eu)
    sha = hashlib.sha1(eu).hexdigest()
    (dst / "rom.sha1").write_text(f"{sha}  medabots_rokusho.gba\n")
    M = Mapper(us, eu)
    stats = {"tamanho": 0, "mudou": 0, "ruim": [], "var": set()}
    forced_from_code(src, M)
    print(f"rotulos com endereco EU lido no codigo: {len(FORCED)}")
    for f in list(dst.glob("data/*.s")) + list(dst.glob("sound/*.s")) + list(dst.glob("graphics/*.s")) + \
            list(dst.glob("asm/*.s")) + list(dst.glob("asm/lib/*.s")):
        t = f.read_text()
        if "baserom.gba" in t:
            f.write_text(remap_markers(remap_incbins(t, M, stats), M))
    for f in dst.glob("config/data_ptrs/*.tsv"):
        if not a.ptrs:   # build que bate: ponteiros dos dados vem crus da ROM EU (so os rotulos precisam estar certos)
            f.write_text("# ROM address of a pointer word in the stub, and the symbol it points to\n")
            continue
        lines = []
        for line in f.read_text().splitlines():
            if line and not line.startswith("#"):
                ad, sym = line.split("\t", 1)
                line = "%08X\t%s" % (M.map(int(ad, 16) - GBA) + GBA, remap_target(sym, M))
            lines.append(line)
        f.write_text("\n".join(lines) + "\n")
    rng = func_ranges(src, M)
    done = []
    for c in dst.rglob("src/**/*.c"):
        code = c.read_text()
        for n, (eo, es) in rng.items():
            if re.search(r'\b' + re.escape(n) + r'\s*\(', code):
                new = wrap_function(code, n, eo, es)
                if new:
                    code = new
                    done.append(n)
        c.write_text(code)
    mk = (dst / "Makefile").read_text()
    mk = mk.replace("CPPFLAGS := -nostdinc", "CPPFLAGS := -DEU_BUILD -nostdinc").replace("A9BE", "A9BP")
    (dst / "Makefile").write_text(mk)
    print(f"blocos que mudaram: {stats['mudou']}; tamanho <= 0: {[(hex(a), hex(b), hex(c), hex(d)) for a, b, c, d in stats['ruim']]}")
    print(f"arvore EU em {dst}; incbin com tamanho trocado: {stats['tamanho']}; funcoes trocadas: {sorted(set(done))}")
    print("faltaram:", sorted(set(FUNCS) - set(done)))


if __name__ == "__main__":
    main()
