"""
codecs_gba.py - Descompressores usados pelo Medabots/Shingata (so leitura; servem para medir blocos).

- Malias ('Le'): portado de mdr-navi-i18n navi/gfx.py (MIT, caribbeansc), por sua vez de
  Normmatt's Malias2.cs.
- LZ77 da BIOS do GBA (cabecalho 0x10).
"""


def malias_decompress(data, offset):
    """Retorna (payload, tamanho comprimido em bytes)."""
    if data[offset:offset + 2] != b"Le":
        raise ValueError(f"Sem bloco Malias em 0x{offset:X}")
    length = data[offset + 2] | data[offset + 3] << 8 | data[offset + 4] << 16
    src, out, remaining = offset + 6, bytearray(), length
    while remaining > 0:
        command = data[src]
        src += 1
        for _ in range(4):
            if remaining <= 0:
                break
            mode = command & 3
            if mode == 0:
                value = data[src] | data[src + 1] << 8
                src += 2
                distance, count = (value & 0xFFF) + 5, (value >> 12) + 3
                for _ in range(count):
                    out.append(out[-distance])
                remaining -= count
            elif mode == 1:
                value = data[src]
                src += 1
                distance, count = (value & 3) + 1, (value >> 2) + 2
                for _ in range(count):
                    out.append(out[-distance])
                remaining -= count
            elif mode == 2:
                out.append(data[src])
                src += 1
                remaining -= 1
            else:
                out += data[src:src + 3]
                src += 3
                remaining -= 3
            command >>= 2
    return bytes(out[:length]), src - offset


def lz77_decompress(data, offset):
    """LZ77 da BIOS (0x10). Retorna (payload, tamanho comprimido em bytes)."""
    if data[offset] != 0x10:
        raise ValueError(f"Sem bloco LZ77 em 0x{offset:X}")
    length = data[offset + 1] | data[offset + 2] << 8 | data[offset + 3] << 16
    src, out = offset + 4, bytearray()
    while len(out) < length:
        flags = data[src]
        src += 1
        for bit in range(8):
            if len(out) >= length:
                break
            if flags & (0x80 >> bit):
                b1, b2 = data[src], data[src + 1]
                src += 2
                count, distance = (b1 >> 4) + 3, (((b1 & 0xF) << 8) | b2) + 1
                for _ in range(count):
                    out.append(out[-distance])
            else:
                out.append(data[src])
                src += 1
    return bytes(out[:length]), src - offset


def lz77_store(payload):
    """Bloco LZ77 (0x10) so com literais: cada grupo = flag 0x00 + 8 bytes."""
    out = bytearray([0x10, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF, (len(payload) >> 16) & 0xFF])
    for i in range(0, len(payload), 8):
        out.append(0)
        out += payload[i:i + 8]
    while len(out) % 4:
        out.append(0)
    assert lz77_decompress(bytes(out), 0)[0] == bytes(payload)
    return bytes(out)


def compressed_size(data, offset):
    """Tamanho em bytes do bloco comprimido em `offset` (Malias ou LZ77)."""
    if data[offset:offset + 2] == b"Le":
        return malias_decompress(data, offset)[1]
    if data[offset] == 0x10:
        return lz77_decompress(data, offset)[1]
    raise ValueError(f"Formato desconhecido em 0x{offset:X}: {data[offset:offset + 4].hex()}")
