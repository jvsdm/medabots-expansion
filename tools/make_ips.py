"""make_ips.py - Patch IPS entre a ROM original e uma build (e aplicacao, para conferir).

IPS: "PATCH", registros (offset 3 B, tamanho 2 B, dados), "EOF". Offsets ate 16 MB (as builds tem ~9,3 MB). Um
registro nao pode comecar no offset 0x454F46 (le-se "EOF"): nesse caso comeca um byte antes.

Uso:
  python tools/make_ips.py criar ORIGINAL.gba BUILD.gba saida.ips
  python tools/make_ips.py aplicar ORIGINAL.gba patch.ips saida.gba
"""
import sys
from pathlib import Path

EOF_AT = 0x454F46
MAX = 0xFFFF


def create(base, new):
    out = bytearray(b"PATCH")
    n = len(new)
    i = 0
    while i < n:
        if i < len(base) and base[i] == new[i]:
            i += 1
            continue
        start = i
        # trecho diferente; junta diferencas separadas por ate 4 bytes iguais (menos cabecalhos)
        last = i                                        # ultimo byte diferente do trecho
        while i < n and i - start < MAX:
            if i < len(base) and base[i] == new[i]:
                if i - last > 4:
                    break
            else:
                last = i
            i += 1
        end = last + 1
        if start == EOF_AT:
            start -= 1
        if start > 0xFFFFFF:
            raise SystemExit("offset acima de 16 MB: IPS nao serve")
        out += start.to_bytes(3, "big") + (end - start).to_bytes(2, "big") + new[start:end]
        i = end
    out += b"EOF"
    return bytes(out)


def apply(base, patch):
    assert patch[:5] == b"PATCH"
    rom = bytearray(base)
    p = 5
    while patch[p:p + 3] != b"EOF":
        off = int.from_bytes(patch[p:p + 3], "big")
        size = int.from_bytes(patch[p + 3:p + 5], "big")
        p += 5
        if size == 0:                                   # RLE
            run = int.from_bytes(patch[p:p + 2], "big")
            data = patch[p + 2:p + 3] * run
            p += 3
        else:
            data = patch[p:p + size]
            p += size
        if off + len(data) > len(rom):
            rom += bytes(off + len(data) - len(rom))
        rom[off:off + len(data)] = data
    return bytes(rom)


def main():
    if len(sys.argv) != 5 or sys.argv[1] not in ("criar", "aplicar"):
        raise SystemExit(__doc__)
    a, b, c = (Path(x) for x in sys.argv[2:])
    if sys.argv[1] == "criar":
        c.write_bytes(create(a.read_bytes(), b.read_bytes()))
    else:
        c.write_bytes(apply(a.read_bytes(), b.read_bytes()))
    print(c, c.stat().st_size)


if __name__ == "__main__":
    main()
