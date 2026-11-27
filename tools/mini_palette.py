"""
mini_palette.py - Cores dos mini sprites (sprite composto de batalha/menus) de bots portados.

Cada componente do mini sprite usa o banco OBJ = "palette family" do bot (0-2). Os bancos 0-3 sao
carregados de MINI_PALETTES (4 paletas, a 4a zerada no jogo original = banco 3 livre). O Shingata
usa paletas proprias (0x58E0A0..), diferentes das EU, entao os tiles portados ficam com cor errada.

Solucao: o banco 3 recebe uma paleta "extra" calculada a partir das cores dos bots portados;
para cada bot escolhe-se o banco (0-3) com menor erro e os indices dos tiles sao remapeados.
"""
import colorsys
import os
import struct
import numpy as np
from codecs_gba import malias_decompress

from medarom import PALETTE_SET as MINI_PALETTES   # 4 x 32 B copiados para os bancos OBJ 0-3 (da versao em uso)
EXTRA_BANK = 3
# Ajuste de estilo das cores de origem (HSV): os minis do Shingata sao ~15% mais escuros que as
# pecas grandes e mais saturados que os do EU. Aplicado antes do remapeamento.
VALUE_GAIN = float(os.environ.get("MINI_VALUE_GAIN", "1.05"))   # 1.15 ate 2026-11-24; 1.05 escolhido pelo usuario        # MINI_VALUE_GAIN: teste de brilho
SATURATION_GAIN = float(os.environ.get("MINI_SATURATION_GAIN", "0.90"))


def rgb(c):
    return np.array(((c & 31) * 8, (c >> 5 & 31) * 8, (c >> 10 & 31) * 8), float)


def bgr555(v):
    r, g, b = (int(min(31, max(0, round(x / 8)))) for x in v)
    return r | g << 5 | b << 10


def palettes(data, at, count):
    return [[rgb(struct.unpack_from("<H", data, at + 32 * k + 2 * i)[0] & 0x7FFF) for i in range(16)]
            for k in range(count)]


def restyle(pal, value=VALUE_GAIN, saturation=SATURATION_GAIN):
    out = []
    for c in pal:
        h, sa, v = colorsys.rgb_to_hsv(*(c / 255))
        out.append(np.array(colorsys.hsv_to_rgb(h, min(1, sa * saturation), min(1, v * value))) * 255)
    return out


def malias_store(payload):
    """Bloco Malias so com literais (modo 3 = 3 bytes, modo 2 = 1 byte)."""
    out = bytearray(b"Le" + len(payload).to_bytes(3, "little") + b"\0")
    i = 0
    while i < len(payload):
        cmd, body = 0, bytearray()
        for op in range(4):
            if i >= len(payload):
                break
            n = 3 if len(payload) - i >= 3 else 1
            cmd |= (3 if n == 3 else 2) << (2 * op)
            body += payload[i:i + n]
            i += n
        out.append(cmd)
        out += body
    assert malias_decompress(bytes(out), 0)[0] == bytes(payload)
    return bytes(out)


def color_usage(components):
    cnt = np.zeros(16)
    for d in components:
        for b in d:
            cnt[b & 15] += 1
            cnt[b >> 4] += 1
    cnt[0] = 0
    return cnt


def nearest(color, pal):
    return 1 + int(np.argmin([np.linalg.norm(color - c) for c in pal[1:]]))


def cost(src_pal, cnt, pal):
    return sum(cnt[i] * np.linalg.norm(src_pal[i] - pal[nearest(src_pal[i], pal)])
               for i in range(1, 16) if cnt[i])


def extra_palette(samples):
    """15 cores por k-means ponderado pela quantidade de pixels (deterministico: semente = mais distante)."""
    X = np.array([c for c, _ in samples])
    W = np.array([w for _, w in samples]) + 1e-6
    C = [X[int(np.argmax(W))]]
    while len(C) < 15:
        d = np.array([min(np.linalg.norm(x - c) for c in C) for x in X]) * np.sqrt(W)
        C.append(X[int(np.argmax(d))])
    C = np.array(C)
    for _ in range(60):
        lab = np.argmin(((X[:, None] - C[None]) ** 2).sum(-1), 1)
        for k in range(15):
            if (lab == k).any():
                C[k] = np.average(X[lab == k], axis=0, weights=W[lab == k])
    return [np.zeros(3)] + [rgb(bgr555(c)) for c in C]


def recolor(jobs, base, log):
    """jobs: [(nome, paleta_origem(16 cores), [payloads dos 6 componentes], aplicar_estilo)].
    aplicar_estilo = ajuste HSV dos minis do Shingata (bots recoloridos a mao usam as cores exatas).
    Retorna (paleta extra em bytes, [(banco, [payloads remapeados])])."""
    jobs = [(name, restyle(src_pal) if style else src_pal, comps) for name, src_pal, comps, style in jobs]
    usage = [color_usage(comps) for _, _, comps in jobs]
    chosen = list(range(len(jobs)))            # 1a rodada: todos alimentam a paleta extra
    for _ in range(4):                        # alterna: paleta extra <-> escolha de banco por bot
        samples = [(jobs[j][1][i], usage[j][i]) for j in chosen for i in range(1, 16) if usage[j][i]]
        if not samples:     # nenhum bot quer a paleta extra (minis que cabem nas do jogo): fica a da rodada anterior
            break
        extra = extra_palette(samples)
        banks = base + [extra]
        pick = [min(range(4), key=lambda k: cost(src_pal, cnt, banks[k]))
                for (_, src_pal, _), cnt in zip(jobs, usage)]
        new_chosen = [j for j, k in enumerate(pick) if k == EXTRA_BANK]
        if new_chosen == chosen:
            break
        chosen = new_chosen
    out = []
    for name, src_pal, comps in jobs:
        cnt = color_usage(comps)
        bank = min(range(len(banks)), key=lambda k: cost(src_pal, cnt, banks[k]))
        lut = [0] + [nearest(src_pal[i], banks[bank]) for i in range(1, 16)]
        new = [bytes(lut[b & 15] | lut[b >> 4] << 4 for b in d) for d in comps]
        out.append((bank, new))
        log.append(f"mini sprite de {name}: banco {bank}, erro medio "
                   f"{cost(src_pal, cnt, banks[bank]) / max(1, cnt.sum()):.0f}")
    blob = b"".join(struct.pack("<H", bgr555(c)) for c in extra)
    return blob, out
