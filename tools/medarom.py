"""
medarom.py - Base comum: ROM, ponteiros, texto e offsets da Medabots Metabee (Europe).

Offsets do Medabots-Romhacking-Toolkit (STulling) sao da Rokusho (E); na Metabee (E)
a regiao de dados 0x07xxxx-0x3Dxxxx fica 0x20 bytes ANTES. Os valores abaixo ja
estao corrigidos e conferidos contra os literal pools do codigo.
"""
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROM_PATH = ROOT / "Medabots - Metabee (Europe).gba"
GBA_BASE = 0x08000000
ROM_HEADER = b"MEDABOTSMTBVA8BP"

import json
import os
import sys
from functools import lru_cache

VERSIONS_DIR = ROOT / "pc" / "versions"
DEFAULT_VERSION = "metabee_eu"
VERSION_ALIASES = {"metabee": "metabee_eu", "rokusho": "rokusho_eu"}  # flag curta -> perfil EU


def version_name(argv=None):
    """Versao: --version=NOME ou --version NOME na linha de comando; senao MEDABOTS_VERSION; senao metabee_eu."""
    argv = sys.argv if argv is None else argv
    for i, a in enumerate(argv):
        if a == "--version" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--version="):
            return a.split("=", 1)[1]
    return os.environ.get("MEDABOTS_VERSION") or DEFAULT_VERSION


@lru_cache(maxsize=None)
def profile(versao=None):
    """Perfil da versao (pc/versions/<versao>.json): rom, code, tables (enderecos CPU) e counts."""
    v = versao or version_name()
    v = VERSION_ALIASES.get(v, v)          # nome curto da flag -> perfil (rokusho -> rokusho_eu)
    path = VERSIONS_DIR / f"{v}.json"
    if not path.exists():
        raise FileNotFoundError(f"perfil de versao inexistente: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def addr(nome, versao=None):
    """Endereco CPU (0x08xxxxxx) da tabela 'nome' na versao escolhida."""
    p = profile(versao)
    if nome not in p["tables"]:
        raise KeyError(f"tabela {nome!r} nao existe no perfil {p['versao']}")
    return int(p["tables"][nome], 16)


def off(nome, versao=None):
    """Offset de arquivo da tabela 'nome' (= addr - 0x08000000)."""
    return addr(nome, versao) - GBA_BASE


def count(nome, versao=None):
    """Contagem (ex.: numero de encontros de batalha) da versao."""
    return profile(versao)["counts"][nome]


BOT_COUNT = 120          # 0x78
PART_KINDS = ("head", "right_arm", "left_arm", "legs")
PART_SIZE = 0x10

# --- tabelas indexadas por bot / peca (EU) ---
PART_STATS = off("medarom.part_stats")         # 480 x 16 B   (stats; logo apos vem texto -> nao cresce no lugar)
BOT_NAMES = off("medarom.bot_names")          # 120 ponteiros
PART_NAMES = off("medarom.part_names")         # 480 ponteiros
BATTLE_SPRITES = off("medarom.battle_sprites")     # 6 ponteiros por bot (sprite composto de batalha)
PALETTE_FAMILY = off("medarom.palette_family")     # 1 byte por bot
MOVE_STYLE = off("medarom.move_style")         # 1 byte por bot (122): estilo de deslocamento em batalha, 0-6
                              # fn 0x44A3C: roteiro = tab[tipo*7 + MOVE_STYLE[bot das pernas]]
PREVIEW_TABLES = {            # 16 B por entrada, 0x7A0 bytes cada (122 entradas)
    "head": off("medarom.preview_head"),
    "right_arm": off("medarom.preview_right_arm"),
    "left_arm": off("medarom.preview_left_arm"),
    "legs": off("medarom.preview_legs"),
}
MEDAL_INFO = off("medarom.medal_info")
MOLD_TABLE = off("medarom.mold_table")          # ponteiro p/ registro de cada molde de preview (50)
PALETTE_SET = off("export.palette_set")         # paletas dos mini sprites (4 x 32 B)
SHOP_TABLE_SIG = bytes([0x13, 0x00, 0xFF, 0xFF, 0x13, 0x00, 0x42, 0xFF, 0x13, 0x00])

# --- RAM (IWRAM) ---
RAM_PARTS_INVENTORY = 0x03004C40   # 4 blocos de 0xF0 (120 x 2 B), um por tipo
RAM_EQUIPPED_BOT = 0x030017A0

# Registro de peca (16 B). byte1 = indice em TECHNIQUES (ou tipo de perna 100+),
# byte2 = indice em SPECIALITIES, u10 = "rank" do bot (mesmo nas 4 pecas),
# buy_price (byte 11) = preco de compra / 100: a loja mostra byte x 100 em centavos (54 -> 54.00); a venda paga
# a metade (shop_list.c: total /= 2), sem byte proprio. Antes se chamava u11.
# u12 = flag (1 normal, 32 em alguns chefes).
COMBAT_FIELDS = ["medal_compat", "technique", "speciality", "female", "armor",
                 "success", "power", "chain_reaction", "uses_or_charge", "radiation",
                 "u10", "buy_price", "u12", "u13", "u14", "u15"]
LEG_FIELDS = ["medal_compat", "leg_type", "speciality", "female", "armor",
              "propulsion", "evasion", "defense", "proximity", "remoteness",
              "u10", "buy_price", "u12", "u13", "u14", "u15"]


def part_fields(kind):
    return LEG_FIELDS if kind == "legs" else COMBAT_FIELDS


# Mesmo encoding do legado/insert_text_v2.py (0x4F = 'õ' na fonte PT-BR; na original e vazio)
ENCODING = (
    " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789·"
    ".,'-/:?!\"()♥£&%õ"
    "ÄäÁáÂâÈèÉéÊêËëÎî"
    "ÏïÍíÖöÔôÓóÜüÛûÙù"
    "ÚúßÇçÑñ¡¿ÀàÆæÃãÕ"
)
assert len(ENCODING) == 0x80
_ENCODE = {c: i for i, c in enumerate(ENCODING)}


def encode_text(s):
    """Texto simples -> bytes da ROM terminados em FE (formato dos nomes)."""
    try:
        return bytes(_ENCODE[c] for c in s) + b"\xFE"
    except KeyError as e:
        raise ValueError(f"Caractere sem glifo na fonte: {e} em {s!r}") from None


def profile_rom_path():
    """ROM da versao em uso (perfil): achada pelo SHA1 (tools/roms.py), o nome do arquivo nao importa."""
    import roms
    v = VERSION_ALIASES.get(version_name(), version_name())
    return roms.rom_path(roms.PROFILE_ROM[v]) if v in roms.PROFILE_ROM else ROOT / profile()["rom"]


class Rom:
    def __init__(self, path=None):
        path = path or profile_rom_path()
        self.path = Path(path)
        self.data = bytearray(self.path.read_bytes())
        # cabecalho: titulo MEDABOTS... + codigo do perfil da versao (A8BP EU, A8BE USA, ...)
        code = profile()["code"].encode()
        if self.data[0xA0:0xA8] != b"MEDABOTS" or self.data[0xAC:0xB0] != code:
            raise ValueError(f"ROM inesperada para o perfil {profile()['versao']}: {bytes(self.data[0xA0:0xB2])!r}")

    def u8(self, o):
        return self.data[o]

    def u32(self, o):
        return struct.unpack_from("<I", self.data, o)[0]

    def ptr(self, o):
        """Le um ponteiro GBA e devolve offset na ROM (ou None se nao for ROM)."""
        v = self.u32(o)
        if GBA_BASE <= v < GBA_BASE + 0x2000000:
            return v - GBA_BASE
        return None

    def ptr_at(self, table, index):
        return self.ptr(table + 4 * index)

    def text(self, o, limit=512):
        """Decodifica uma string ate FE/FF; codigos de controle viram <XX>."""
        out = []
        for _ in range(limit):
            b = self.data[o]
            if b in (0xFE, 0xFF):
                break
            out.append(ENCODING[b] if b < 0x80 else f"<{b:02X}>")
            o += 1
        return "".join(out)

    def find(self, sig, start=0):
        return self.data.find(sig, start)
