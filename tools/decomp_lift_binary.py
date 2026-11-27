"""
decomp_lift_binary.py - Leva os bots da expansao binaria antiga (tools/build.py sobre a Metabee EU: Sagehorn, os 60
do Shingata, Granbeetle do Navi) para a descompilacao do Rokusho USA. Usado por decomp_expand.py --from-binary.

Le a ROM gerada pelo build.py (EU expandida) e o log dele, e devolve o texto de asm/expansion.s mais as trocas a
aplicar na arvore:
  - linhas dos bots 120.. de cada tabela tiradas da EU expandida; ponteiros convertidos para simbolos:
      area nova da EU expandida (0xC00000..)  -> gExpBin + deslocamento (o bloco vai inteiro, cru, para
                                                expansion_eu.bin; so serve de alvo de ponteiros)
      dado original da EU                      -> endereco USA pelo mapa fino de conteudo -> rotulo + deslocamento
  - listas de imagens dos moldes de preview que o build recriou (38): copias convertidas (gExpMold<d>) e o
    ponteiro do registro do molde (config/data_ptrs) passa a apontar para elas;
  - bytes que o build trocou no lugar: paleta extra dos mini sprites (banco 3) e o total de paginas da lista.
A fonte italica corrigida (defeito so da EU) nao entra.
"""
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from decomp_make_eu import Mapper, masked  # noqa: E402

GBA = 0x08000000
DESCRIPTORS_EU = 0x3D1D78        # tabela de registros de molde (Metabee EU), 50 moldes
MOLD_WORDS = 512                 # lista de imagens recriada: 256 seletores x (imagem, paleta)
INPLACE = [(0x50F4F8, 0x20, "paleta extra dos mini sprites (banco 3)"),
           (0x4F1560, 4, "total de paginas da lista de Medaparts (cima)"),
           (0x4F1580, 4, "total de paginas da lista de Medaparts (baixo)")]
# tabela da descompilacao -> (nome no log do build.py, bytes por bot, tem ponteiros)
TABLE_SRC = {
    "gMedapartData": ("PART_STATS", 64, False),
    "gMedabotNames": ("BOT_NAMES", 4, True),
    "gMedapartNames": ("PART_NAMES", 16, True),
    "gMedabotPartSpriteTiles": ("BATTLE_SPRITES", 24, True),
    "gMedabotSpritePalettes": ("PALETTE_FAMILY", 1, False),
    "gLegPartPoseSets": ("MOVE_STYLE", 1, False),
    "gHeadPartSpriteNodes": ("PREVIEW_HEAD", 16, False),
    "gRightArmPartSpriteNodes": ("PREVIEW_RIGHT_ARM", 16, False),
    "gLeftArmPartSpriteNodes": ("PREVIEW_LEFT_ARM", 16, False),
    "gLegPartSpriteNodes": ("PREVIEW_LEGS", 32, False),
}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


class _Identity:
    def map(self, o):
        return o


class Lifter:
    def __init__(self, exp_path, log_path, usa, dst):
        # exp_path / log_path: arquivos do build.py, ou (bytes, texto) feitos em memoria por build.build_rom
        self.exp = bytes(exp_path) if isinstance(exp_path, (bytes, bytearray)) else Path(exp_path).read_bytes()
        self.usa = usa
        # recipiente montado sobre a propria Rokusho USA (build.py data_only, perfil rokusho_us): mesmo endereco
        self.same_base = self.exp[0xAC:0xB0] == usa[0xAC:0xB0]
        self.eu = usa if self.same_base else __import__("roms").rom_bytes("metabee_eu")
        log = log_path if "\n" in str(log_path) else Path(log_path).read_bytes().decode("cp1252", "replace")
        self.tables = {m.group(1): int(m.group(2), 16) - GBA
                       for m in re.finditer(r"^(\w+): \d+ ponteiros -> 0x([0-9A-Fa-f]+)", log, re.M)}
        m = re.search(r"tabelas 0x([0-9A-Fa-f]+)-0x([0-9A-Fa-f]+)", log)
        self.region = (int(m.group(1), 16), int(m.group(2), 16))
        self.M = _Identity() if self.same_base else Mapper(self.eu, usa)   # offset da base -> offset USA
        self.labels = self._labels(dst)
        self.bad = []

    def _labels(self, dst):
        """(offset USA, rotulo) por arquivo de dado, so rotulos seguidos de .incbin (posicao conhecida)."""
        out = []
        for f in list(dst.glob("data/*.s")) + list(dst.glob("sound/*.s")) + list(dst.glob("graphics/*.s")):
            t = f.read_text()
            spans = [(int(a, 16), int(b, 16)) for a, b in
                     re.findall(r'\.incbin\s+"baserom\.gba",\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+)', t)]
            if not spans:
                continue
            lo, hi = min(a for a, _ in spans), max(a + b for a, b in spans)
            for m in re.finditer(r'^(\w+):\s*\n(?:\s*\.global\s+\w+\s*\n)?\s*\.incbin\s+"baserom\.gba",\s*(0x[0-9A-Fa-f]+)',
                                 t, re.M):
                out.append((int(m.group(2), 16), m.group(1), lo, hi))
        out.sort()
        return out

    def usa_symbol(self, us_off):
        best = None
        for off, lab, lo, hi in self.labels:
            if off <= us_off and lo <= us_off < hi:
                if best is None or off > best[0]:
                    best = (off, lab)
        if best is None:
            return None
        return best[1] if us_off == best[0] else f"{best[1]}+0x{us_off - best[0]:X}"

    def conv(self, w, where):
        """Palavra-ponteiro da EU expandida -> texto para .4byte na descompilacao."""
        if w == 0:
            return "0"
        a, b = self.region
        if GBA + a <= w < GBA + b:
            return f"gExpBin+0x{w - GBA - a:X}"
        if GBA <= w < GBA + 0x800000:
            eo = w - GBA
            uo = self.M.map(eo)
            if masked(self.eu[eo:eo + 16]) != masked(self.usa[uo:uo + 16]):
                self.bad.append((where, hex(w)))
            sym = self.usa_symbol(uo)
            if sym is None:
                self.bad.append((where, hex(w) + " sem rotulo"))
                return f"0x{GBA + uo:08X}"
            return sym
        return f"0x{w:08X}"

    def rows(self, table, first, count):
        """Texto asm das linhas [first, first+count) da tabela do build.py para a tabela `table`."""
        return self.rows_ids(table, range(first, first + count))

    def rows_ids(self, table, ids):
        """Como rows, para uma lista de ids do build.py (a lista de bots escolhe quais entram, em ordem)."""
        name, size, ptrs = TABLE_SRC[table]
        base = self.tables[name]
        out = []
        for bid in ids:
            o = base + bid * size
            if ptrs:
                out.append("".join(f"\t.4byte {self.conv(u32(self.exp, o + 4 * k), f'{table}[{bid}]')}\n"
                                   for k in range(size // 4)))
            else:
                out.append("\t.byte " + ", ".join(str(x) for x in self.exp[o:o + size]) + "\n")
        return "".join(out)

    def bot_names(self, first, count):
        return self.bot_names_ids(range(first, first + count))

    def bot_names_ids(self, ids):
        out = []
        base = self.tables["BOT_NAMES"]
        for bid in ids:
            p = u32(self.exp, base + 4 * bid) - GBA
            raw = self.exp[p:p + 16]
            out.append(raw[:raw.index(0xFE)] if 0xFE in raw else raw)
        return out

    def part_names_ids(self, ids):
        """[[4 nomes crus]] por id (tabela PART_NAMES do build.py: 4 ponteiros por bot)."""
        out = []
        base = self.tables["PART_NAMES"]
        for bid in ids:
            row = []
            for k in range(4):
                p = u32(self.exp, base + bid * 16 + 4 * k) - GBA
                raw = self.exp[p:p + 24]
                row.append(raw[:raw.index(0xFE)] if 0xFE in raw else raw)
            out.append(row)
        return out

    def molds(self):
        """[(molde, offset EU do registro, asm da lista nova)] para os moldes cuja lista o build recriou."""
        out = []
        for d in range(1, 50):
            rec = u32(self.eu, self._descriptors() + 4 * d) - GBA
            if not (0 <= rec < 0x800000) or self.exp[rec:rec + 4] == self.eu[rec:rec + 4]:
                continue
            bt = u32(self.exp, rec) - GBA
            words = "".join(f"\t.4byte {self.conv(u32(self.exp, bt + 4 * i), f'molde {d}')}\n"
                            for i in range(MOLD_WORDS))
            out.append((d, rec, f"\n\t.align 2\n\t.global gExpMold{d}\ngExpMold{d}:\n{words}"))
        return out

    def _descriptors(self):
        if self.same_base:
            import medarom
            return medarom.MOLD_TABLE
        return DESCRIPTORS_EU

    def inplace(self):
        """[(offset USA, bytes novos, nome)] dos trechos trocados no lugar; confere os bytes originais."""
        out = []
        places = INPLACE
        if self.same_base:      # so a paleta extra dos minis (o total de paginas o decomp_expand troca direto)
            import medarom
            places = [(medarom.PALETTE_SET + 0x60, 0x20, "paleta extra dos mini sprites (banco 3)")]
        for eo, n, what in places:
            uo = self.M.map(eo)
            if self.eu[eo:eo + n] != self.usa[uo:uo + n]:
                self.bad.append((what, f"bytes originais diferem na USA em 0x{uo:X}"))
                continue
            out.append((uo, self.exp[eo:eo + n], what))
        return out

    def region_bytes(self):
        a, b = self.region
        return self.exp[a:b]


def patch_stub_bytes(dst, us_off, data):
    """Troca bytes [us_off, us_off+len) dentro do .incbin de um stub de dado (divide o bloco)."""
    for f in list(dst.glob("data/*.s")) + list(dst.glob("graphics/*.s")) + list(dst.glob("sound/*.s")):
        t = f.read_text()
        for m in re.finditer(r'(\t\.incbin\s+"baserom\.gba",\s*)(0x[0-9A-Fa-f]+)(,\s*)(0x[0-9A-Fa-f]+)\n', t):
            o, n = int(m.group(2), 16), int(m.group(4), 16)
            if o <= us_off and us_off + len(data) <= o + n:
                parts = []
                if us_off > o:
                    parts.append(f'\t.incbin "baserom.gba", 0x{o:X}, 0x{us_off - o:X}\n')
                parts.append("\t.byte " + ", ".join(f"0x{x:02X}" for x in data) + "\n")
                end = us_off + len(data)
                if o + n > end:
                    parts.append(f'\t.incbin "baserom.gba", 0x{end:X}, 0x{o + n - end:X}\n')
                f.write_text(t[:m.start()] + "".join(parts) + t[m.end():])
                return f.name
    return None
