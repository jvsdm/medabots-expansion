"""
decomp_navi.py - Bots do Medarot Navi para a descompilacao expandida (tools/decomp_expand.py --navi).

Porte do NaviImporter do Toolkit (git/Medabots-Romhacking-Toolkit/src/Medabots.Rom/Expansion/NaviImporter.cs,
docs/EXPANSAO_MEDABOTS.md 15.4-15.5) para dados da descompilacao em vez de bytes numa ROM:
  - cada bot do Navi vira um bot novo: stats, mini sprite, paleta e estilo de movimento de um bot do Medabots com a
    mesma geometria de pernas (Rokusho 42 bipede, Spidar 28 / Totalizer 93 corrente, Noctobat 0 / Armorparadeen 77 /
    Churlybear 13 uma peca); tipo de perna do Navi; nome da Medapedia; pecas com o codigo de modelo do Navi;
  - as pecas guardam as entradas do Navi (molde mapeado + seletor proprio) com o bit 16 (SpriteTileRef.navi);
  - gNaviSpriteNodeDescs: tabela de moldes do Navi (registros do Navi nos IDs do Medabots de mesmo formato, moldes
    novos 50+ para os formatos que o Medabots nao tem), cada um com sua lista de imagens;
  - gMedabotSpriteNodeDescs passa a 64 entradas (50+ = moldes novos), gMirroredPartNodeNavi com 64 e as linhas de
    movimento (gPoseKeyframeAngles/Offsets) com 63 linhas, as novas copiadas de um molde parecido;
  - linha do chao: bits 24-31 da 1a entrada das pernas (SpriteTileRef.lift), medida na pose parada contra a mediana
    dos bots do Medabots.
O lado C (escolha da tabela por peca) fica em src/engine/sprite_engine.c sob EXP_NAVI_SPRITES (include/config/expansion.h).
"""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from codecs_gba import lz77_decompress, lz77_store, compressed_size  # noqa: E402

NAVI_ROM = ROOT / "0100 - Medarot Navi - Kuwagata Version (J)(Eurasia).gba"
GBA = 0x08000000
NAVI_MOLDS = 0x658858
NAVI_ROWS = [(0x4BFC40, 16), (0x4C05C0, 16), (0x4C0F40, 16), (0x4C18C0, 32)]
NAVI_JOINTS = [0x4BFBE4, 0x4BFBFC, 0x4BFC14, 0x4BFC2C]
NAVI_FORMS = 0x4C2BC0                     # Medachange: 32 B por bot (fase 2)

# USA (descompilacao)
CORE_MOLDS = 0x3D1BF8                     # gMedabotSpriteNodeDescs, 50 ponteiros
MIRROR = 0x81320                          # gMirroredPartNode (50 bytes no inicio do bloco)
POSE_ANG, POSE_OFF, POSE_END = 0x3D1CC0, 0x3D1DAC, 0x3D1E98   # 59 ponteiros cada
POSE_SCRIPTS = 59
CORE_ROWS = [(0x7ED00, 16), (0x7F4A0, 16), (0x7FC40, 16), (0x803E0, 32)]
PART_DATA = 0x3B827C

FORM_LEGS = 0x9BA30                            # Navi: pernas da forma de Medachange (8 B por bot)
DRIVE_TABLES = (0x9A4D0, 0x9ABF0, 0x9B310)   # Navi: Drive A / B / C (12 B por bot, mesmo formato das pecas)
# Acao do Navi -> (tecnica do Medabots, efeito extra). Efeitos: 1 Shock (alvo proximity -16), 2 Vacuum (alvo
# remoteness -16), 3 Booster (si mesmo proximity +16 por 1 turno). pc/research/NAVI_ACOES_PLANO.md
NAVI_TO_CORE = {
    0: (0, 0), 1: (1, 0), 4: (2, 0), 5: (3, 0), 8: (4, 0), 9: (5, 0), 10: (6, 0), 11: (7, 0), 12: (8, 0), 13: (9, 0),
    14: (49, 0), 15: (13, 0), 16: (14, 0), 17: (17, 0), 18: (18, 0), 19: (19, 0), 20: (20, 0), 21: (15, 0),
    22: (16, 0), 23: (48, 0), 24: (27, 0), 25: (29, 0), 26: (34, 0), 27: (35, 0), 28: (36, 0), 29: (37, 0),
    32: (10, 0), 33: (11, 0), 43: (30, 0), 44: (32, 0), 45: (33, 0), 52: (31, 0), 53: (54, 0), 48: (24, 0),
    49: (25, 0), 50: (26, 0), 70: (44, 0), 73: (47, 0), 74: (50, 0), 42: (23, 0), 71: (45, 0), 57: (38, 0),
    69: (43, 0),
    2: (1, 1),      # Shock = Hammer + empurrao
    6: (2, 2),      # Vacuum = Rifle + puxao
    3: (36, 3),     # Booster (como Drive) = animacao do Scout + buff de proximity
    7: (36, 4),     # Scope (como Drive) = animacao do Scout + buff de remoteness
    # Grupos D/E (2026-11-22). Nomes do Medabots pelo 効果 do 弐CORE (pecas da ROM cruzadas com a wiki pelos stats).
    # Equivalente exato:
    37: (51, 0),    # クロス攻撃セット -> TEAM_FORM (クロス攻撃セット)
    38: (52, 0),    # クロス攻撃ファイア -> TEAM_ATTACK (クロス攻撃ファイア)
    40: (22, 0),    # マイナス症状クリア -> STABILITY (症状クリア)
    51: (22, 0),    # 症状クリア -> STABILITY
    41: (21, 0),    # トラップクリア -> BREAK_FORM (トラップクリア)
    72: (46, 0),    # 回避不能 -> NO_ESCAPE (回避不能)
    39: (37, 0),    # 完全隠蔽 -> CONCEAL (隠蔽)
    60: (55, 0),    # 変化 -> CHANGE (変化)
    62: (57, 0),    # 変化(威力) -> ATTK_CHANGE (変化(攻撃))
    65: (59, 0),    # 変化(回復) -> HEAL_CHANGE (変化(回復))
    64: (58, 0),    # 変化(援護) -> DEF_CHANGE (変化(防御))
    63: (56, 0),    # 変化(症状) -> ITRP_CHANGE (変化(妨害))
    56: (41, 0),    # ジェネレータダウン -> DRAIN_CHRG (チャージドレイン: atrasa a carga do alvo)
    58: (39, 0),    # チャージ -> RAPID_CHRG (急速チャージ)
    # Aproximacao (o Navi tem mecanica que o Medabots nao tem: mapa, ZOC, AP, Medaforce de aliado). Nunca para
    # tecnica passiva do Medabots (script de acao vazio: CANCEL_OPTIC/BOMB/GRAV, ACCEL_CHRG, STRENGTHEN): o jogo
    # recusa a peca ("not made for combat").
    47: (38, 0),    # ジェネレータアップ (AP mais rapido) -> BOOST_CHRG (補助チャージ)
    67: (39, 0),    # 連続行動 (age de novo) -> RAPID_CHRG
    61: (55, 0),    # 変化(速度) -> CHANGE
    66: (55, 0),    # 変化(支援) -> CHANGE
    36: (33, 0),    # ファーストエイド (revive peca quebrada) -> REACTIVATE (2026-11-23)
    46: (41, 5),    # レベルドレイン: rouba niveis da medalha do alvo -> DRAIN_CHRG + level_drain (2026-11-23)
    55: (36, 6),    # 敵影感知 -> SCOUT + detect (proximity e remoteness +16 em si mesmo; 2026-11-23)
    54: (36, 7),    # 重力制御 (movimento a custo fixo) -> SCOUT + speed (propulsao +40 em si mesmo; 2026-11-23)
    35: (12, 0),    # 単発クリア -> ATTACK_CLR (攻撃クリア)
    68: (12, 0),    # プラス症状クリア -> ATTACK_CLR
    30: (27, 0),    # ZOC強化 -> DEFENCE (防御)
    31: (27, 0),    # 全員集合 -> DEFENCE (防御)
    75: (18, 0),    # 範囲内固定 (prende no lugar) -> HOLD (o estado de prender do Medabots; 2026-11-23)
    76: (18, 0),    # 範囲外固定 (prende fora do alcance) -> HOLD
    34: (38, 8),    # フォースプラント -> BOOST_CHRG + force_plant (barra de MF +20 por acao, 4 acoes; 2026-11-23)
    59: (38, 9),    # フォースアップ -> BOOST_CHRG + force_up (o mesmo no aliado alvo; 2026-11-23)
}
ORIG_MOLDS, MOLDS = 50, 64
ORIG_MOTION_ROWS, MOTION_ROWS = 49, 63
NAVI_BIT = 1 << 16

SAME_SHAPE = {7: 7, 8: 8, 9: 9, 10: 10, 13: 17, 14: 18, 16: 14, 17: 15,
              19: 31, 20: 32, 21: 33, 22: 34, 23: 35, 25: 25, 26: 26, 27: 27, 28: 28, 29: 29}
NEW_ANALOG = {30: 13, 11: 11, 12: 12, 15: 19, 33: 19, 18: 16, 34: 16,
              24: 30, 31: 30, 32: 30, 35: 30, 36: 30, 37: 30}
MIRROR_PAIRS = [(15, 18), (33, 34)]
CORE_LIMB_ROOTS = [7, 17, 14, 20]
KIND_PT = ["cabeca", "braco_dir", "braco_esq", "pernas"]   # nomes de peca do export_template (PART_SLOTS)
# Braco grande de peca unica (64x64, analogo 19 / 16 do Medabots): no jogo so desliza, e nos golpes de espada parecia
# travado. Gira com a direcao final da mao do braco de duas pecas do Medabots: angulo = ombro + antebraco (17+18 /
# 14+15); o deslize continua o do 19 / 16. A entrada da peca ganha o bit de giro (14). "rotate": false na peca do JSON
# do bot desliga (2026-11-23, pedido do usuario; conferido no desenho em 6 bots).
TURN_FROM = {19: (17, 18), 16: (14, 15)}
LEG_CODE = {"Flying": 100, "Hover": 101, "Multi-leg": 102, "Bipedal": 103, "Wheeled": 104, "Tank": 105,
            "Aquatic": 106}
SUFFIX = ["01", "02", "03", "04"]
# nomes com mais de 13 letras nao cabem no buffer de nome da medalha (0xE com o fim)
SHORT = {"Imagine Kaiser": "Img.Kaiser", "Bottom Glisten": "B.Glisten", "Arcbeetle-Dash": "Arcbeetle D",
         "Tetsuwan Pandam": "T.Pandam", "Masked Kuwagata": "M.Kuwagata"}


def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]


class Navi:
    def __init__(self, path=None):
        # ROM do Navi achada pelo SHA1 (tools/roms.py): o nome do arquivo nao importa
        self.d = Path(path).read_bytes() if path else __import__("roms").rom_bytes("navi_kuwagata_j")
        assert self.d[0xA0:0xAC] == b"MEDAROTNVKWG", "esperava Medarot Navi Kuwagata"

    def record(self, mold):
        return bytearray(self.d[u32(self.d, NAVI_MOLDS + 4 * mold) - GBA:][:0x18])

    def joint(self, part):
        o = NAVI_JOINTS[part]
        return [struct.unpack_from("b", self.d, o + 0x0C + k)[0] for k in range(3)]

    def has_picture(self, e):
        rec = u32(self.d, NAVI_MOLDS + 4 * (e & 0x3F)) - GBA
        if not 0 <= rec < len(self.d):
            return False
        img = u32(self.d, u32(self.d, rec) - GBA + 8 * ((e >> 6) & 0xFF)) - GBA
        return 0 <= img < len(self.d) and self.d[img] == 0x10

    def rows(self, bot, form=False):
        out = []
        for part, (tab, size) in enumerate(NAVI_ROWS):
            t = (NAVI_FORMS if part == 3 else None) if form else tab
            ent = []
            for k in range(size // 4 if t is not None else 0):
                e = u32(self.d, t + bot * size + 4 * k)
                if e and e < 0x10000 and self.has_picture(e):
                    ent.append(e)
            out.append(ent)
        return out

    def art(self, e):
        """(imagem LZ77, paleta 32 B ou None) por pose; 2 poses se o bit 15 (arte propria do lado 1)."""
        blobs = u32(self.d, u32(self.d, NAVI_MOLDS + 4 * (e & 0x3F)) - GBA) - GBA
        sel = (e >> 6) & 0xFF
        out = []
        for pose in range(((e >> 15) & 1) + 1):
            img = u32(self.d, blobs + 8 * (sel + pose)) - GBA
            pal = u32(self.d, blobs + 8 * (sel + pose) + 4) - GBA
            n = compressed_size(self.d, img)
            out.append((self.d[img:img + n], None if pal == img else self.d[pal:pal + 32]))
        return out


NAVI_LEGS = 0x9A010                            # Navi: pernas normais (8 B por bot, mesmo formato de FORM_LEGS)


def leg_stat_to_core(usa, nv):
    """Conversao dos stats de pernas do Navi para a escala do Medabots, por posicao na distribuicao (quantis).

    Para cada stat (propulsao, esquiva, defesa, proximidade, distancia): o valor do Navi vira o percentil dele no
    conjunto de TODAS as pernas do Navi (normais + formas, bots 0..149), e esse percentil vira o valor na mesma
    posicao das pernas dos 120 bots do Medabots (gMedapartData). Pernas normais do Navi ficam perto do que eram
    (as duas escalas sao parecidas); as formas, que no Navi passam do teto, caem no topo da escala do Medabots.
    0 continua 0 (hover/tanque sem propulsao no Navi e escolha do jogo, nao falta de dado).
    Devolve 5 funcoes (uma por stat)."""
    core = [[] for _ in range(5)]
    for bid in range(120):
        r = usa[PART_DATA + (bid * 4 + 3) * 16:][:16]
        if 100 <= r[1] <= 106:
            for k in range(5):
                core[k].append(r[5 + k])
    navi = [[] for _ in range(5)]
    for tab in (NAVI_LEGS, FORM_LEGS):
        for nid in range(150):
            r = nv.d[tab + 8 * nid:][:8]
            if tab == FORM_LEGS and not any(r[:7]):
                continue                                  # bot sem forma
            for k in range(5):
                navi[k].append(r[2 + k])

    def make(src, dst):
        src, dst = sorted(src), sorted(dst)

        def conv(v):
            if v == 0:
                return 0
            below = sum(1 for x in src if x < v)
            same = sum(1 for x in src if x == v)
            p = (below + same / 2) / len(src)             # percentil (meio do empate)
            pos = p * (len(dst) - 1)
            i = int(pos)
            j = min(i + 1, len(dst) - 1)
            return max(1, round(dst[i] + (dst[j] - dst[i]) * (pos - i)))
        return conv
    return [make(navi[k], core[k]) for k in range(5)]


NAVI_PARTS = (0x98AB0, 0x991D0, 0x998F0)      # Navi: cabeca, braco dir., braco esq. (12 B por bot)
# grupo de escala pelo tipo da habilidade: Navi (nibble baixo do byte 1) e Medabots (data[2], SKILL_TYPE_*)
NAVI_KIND_GROUP = {0: "normal", 1: "normal", 2: "heavy", 3: "heavy"}      # golpe, tiro, imprudente, mirado
CORE_KIND_GROUP = {0: "normal", 2: "normal", 1: "heavy", 3: "heavy"}      # STRIKE, SHOOT, BERSERK, AIM_SHOT
# tipo do Navi -> SKILL_TYPE_* do Medabots: golpe, tiro, imprudente, mirado, protecao -> DEFEND, suporte/especial/
# おうえん -> SUPPORT, cura -> HEAL, sabotagem -> INTERRUPT
NAVI_KIND_CORE = {0: 0, 1: 2, 2: 1, 3: 3, 4: 4, 5: 6, 6: 5, 7: 6, 8: 6, 9: 7}


def core_skill_tables(usa):
    """(tecnica -> tipo mais usado, tipo -> tecnica mais usada) na tabela de pecas do Medabots."""
    from collections import Counter
    by_skill, by_type = {}, {}
    for bid in range(120):
        for k in range(3):
            r = usa[PART_DATA + (bid * 4 + k) * 16:][:16]
            by_skill.setdefault(r[1], Counter())[r[2]] += 1
            by_type.setdefault(r[2], Counter())[r[1]] += 1
    return ({s: c.most_common(1)[0][0] for s, c in by_skill.items()},
            {t: c.most_common(1)[0][0] for t, c in by_type.items()})


def quantile_map(src, dst):
    """Valor de src -> valor na mesma posicao de dst (percentil, meio do empate); 0 fica 0."""
    src, dst = sorted(src), sorted(dst)

    def conv(v):
        if v == 0:
            return 0
        below = sum(1 for x in src if x < v)
        same = sum(1 for x in src if x == v)
        pos = (below + same / 2) / len(src) * (len(dst) - 1)
        i = int(pos)
        j = min(i + 1, len(dst) - 1)
        return max(1, round(dst[i] + (dst[j] - dst[i]) * (pos - i)))
    return conv


class PartScale:
    """Stats das pecas do Navi -> escala do Medabots, por posicao (tools/navi_to_core.py faz a mesma conta com os
    dados da wiki e mede o erro nos 10 bots que existem nos dois jogos: ~8 pontos por stat, igual a uma formula de
    multiplicadores ajustada nesses mesmos bots, sem perder a ordem entre os bots).
    Grupos: armadura por peca; acerto/forca por tipo (normal = golpe/tiro, pesado = imprudente/mirado, suporte = o
    resto; cabeca e bracos juntos); usos da cabeca; AP dos bracos -> carga e resfriamento (por tipo). Do lado do
    Navi entram as pecas normais e os Drives (que, como as pernas das formas, vao alem do teto: caem no topo)."""

    def __init__(self, usa, nv):
        core, navi = {}, {}

        def add(d, k, v):
            d.setdefault(k, []).append(v)
        for bid in range(120):
            for k in range(3):
                r = usa[PART_DATA + (bid * 4 + k) * 16:][:16]
                g = CORE_KIND_GROUP.get(r[2], "support")
                add(core, ("armor", "head" if k == 0 else "arm"), r[4])
                add(core, ("success", g), r[5])
                add(core, ("power", g), r[6])
                if k == 0:
                    add(core, ("uses", "head"), r[8])
                else:
                    add(core, ("charge", g), r[8])
                    add(core, ("cooldown", g), r[9])
            add(core, ("armor", "legs"), usa[PART_DATA + (bid * 4 + 3) * 16 + 4])
        for nid in range(150):
            add(navi, ("armor", "legs"), nv.d[NAVI_LEGS + 8 * nid + 1])
            for k, t in enumerate(NAVI_PARTS + DRIVE_TABLES):
                r = nv.d[t + 12 * nid:][:12]
                if not r[2] and not r[3] and not r[4]:
                    continue                                  # sem Drive (ou registro vazio)
                g = NAVI_KIND_GROUP.get(r[1] & 15, "support")
                if k < 3:
                    add(navi, ("armor", "head" if k == 0 else "arm"), r[2])
                add(navi, ("success", g), r[3])
                add(navi, ("power", g), r[4])
                if k == 0:
                    add(navi, ("uses", "head"), r[5])
                else:
                    add(navi, ("ap", g), r[5])
        self.maps = {}
        for (stat, g), vals in core.items():
            src = navi.get(("ap", g) if stat in ("charge", "cooldown") else (stat, g))
            if src:
                self.maps[(stat, g)] = quantile_map(src, vals)

    def conv(self, stat, g, v):
        f = self.maps.get((stat, g)) or self.maps.get((stat, "support"))
        return f(v) if f else v


def navi_part_record(scale, skills, nv, nid, k, base):
    """Registro de 16 B do Medabots para a peca k (0 cabeca, 1/2 bracos) do bot Navi nid. base = registro do bot
    usado como molde (bytes que o Navi nao tem: 0, 3, 10-15). skills = core_skill_tables().
    Tecnica pelo mapa NAVI_TO_CORE; tipo: nos ataques o do Navi (golpe/tiro/imprudente/mirado), nos outros o que o
    Medabots usa com a tecnica. Acao do Navi sem traducao (ZOC, cruzado, campo, 変化 do Navi...: grupos D/E de
    pc/research/NAVI_ACOES_PLANO.md): aproximacao = tecnica mais usada do Medabots no tipo equivalente."""
    skill_type, type_skill = skills
    r = nv.d[NAVI_PARTS[k] + 12 * nid:][:12]
    out = list(base)
    kind = NAVI_KIND_CORE.get(r[1] & 15)
    skill = NAVI_TO_CORE.get(r[0], (0xFF, 0))[0]
    if skill != 0xFF and skill in skill_type:
        out[1] = skill
        out[2] = kind if kind is not None and kind <= 3 else skill_type[skill]
    elif kind is not None and kind in type_skill:
        out[1], out[2] = type_skill[kind], kind
    g = CORE_KIND_GROUP.get(out[2], "support")
    out[4] = max(1, scale.conv("armor", "head" if k == 0 else "arm", r[2]))
    out[5] = scale.conv("success", g, r[3])
    out[6] = scale.conv("power", g, r[4])
    out[7] = 1 if r[1] >> 4 else 0                     # ◎ = Chain Reaction (nibble alto do tipo no Navi)
    if k == 0:
        out[8] = max(1, scale.conv("uses", "head", r[5]))
        out[9] = 0
    else:
        out[8] = max(1, scale.conv("charge", g, r[5]))
        out[9] = max(1, scale.conv("cooldown", g, r[5]))
    return out


def navi_slug(name):
    """Nome do bot do Navi na lista de bots (data/expansion_bots.txt): minusculo, so letras/numeros e _."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ---- Formato por bot (data/navi/bots/NNN_nome.json; pc/research/EXPANSAO_MODULAR.md, passo 2) ----
# Mesmo formato de data/bots (os 16 bytes de cada peca com nome de campo). O exportador (navi_export) calcula da ROM
# do Navi: tecnica pelo NAVI_TO_CORE, stats na escala do Medabots (PartScale / leg_stat_to_core), bytes que o Navi nao
# tem do bot-molde (clone_source). O gerador (plan) le os JSONs: editar um JSON muda a ROM. Da ROM do Navi o gerador
# so tira os sprites.
BOTS_DIR = ROOT / "data/navi/bots"
PART_SLOTS = ("head", "right_arm", "left_arm", "legs")
STAT_KEYS = ("medal_compat", "technique", "speciality", "female", "armor", "success", "power", "chain_reaction",
             "uses_or_charge", "radiation", "u10", "buy_price", "u12", "u13", "u14", "u15")
LEG_STAT_KEYS = ("medal_compat", "leg_type", "speciality", "female", "armor", "propulsion", "evasion", "defense",
                 "proximity", "remoteness", "u10", "buy_price", "u12", "u13", "u14", "u15")
FORM_LEG_KEYS = ("leg_type", "propulsion", "evasion", "defense", "proximity", "remoteness")
EFFECTS = ("none", "shock", "vacuum", "booster", "scope", "level_drain", "detect", "speed", "force_plant", "force_up")      # efeito extra do Drive (EXP_NAVI_EFFECTS)


def bot_json_path(x):
    return BOTS_DIR / f"{x['navi_id']:03d}_{navi_slug(x['name'])}.json"


_json_cache = {}


def load_bot_json(x):
    path = bot_json_path(x)
    if path not in _json_cache:
        if not path.exists():
            raise SystemExit(f"falta {path}: rode  python tools/decomp_navi.py --export")
        _json_cache[path] = json.loads(path.read_text(encoding="utf-8"))
    return _json_cache[path]


def stats_bytes(st):
    vals = list(st.values())
    assert len(vals) == 16 and all(0 <= v <= 255 for v in vals), st
    return vals


def stats_dict(raw, legs):
    return dict(zip(LEG_STAT_KEYS if legs else STAT_KEYS, raw))


def clone_source(x, r):
    """Bot do Medabots que empresta os graficos que o Navi nao tem (mini sprites, paleta) e os bytes 0, 3, 10-15:
    o de mesma geometria de pernas."""
    legs = {e & 0x3F for e in r[3]}
    if legs and all(19 <= m <= 23 for m in legs):
        return 42
    if legs and all(25 <= m <= 29 for m in legs):
        return 93 if x["leg_type"] == "Tank" else 28
    return {"Flying": 0, "Aquatic": 0, "Wheeled": 77, "Tank": 77}.get(x["leg_type"], 13)


def tech_class_table(usa):
    """Classe (medal_compat) de cada tecnica no Medabots: a mais comum entre as pecas do jogo (52 de 60 tecnicas tem
    uma so). O Navi nao guarda medalha por peca nem por bot; no Medabots a cabeca/bracos tem a classe da tecnica e as
    pernas a medalha do bot, que e a classe do braco direito em 108 de 120 bots (2026-11-23)."""
    from collections import Counter, defaultdict
    cls = defaultdict(Counter)
    for b in range(120):
        for k in range(3):
            rec = usa[PART_DATA + (b * 4 + k) * 16:][:16]
            cls[rec[1]][rec[0]] += 1
    return {t: c.most_common(1)[0][0] for t, c in cls.items()}


def compute_bot(usa, nv, x, scale, leg_map, skills):
    """Dados editaveis de um bot do Navi (o que vai para o JSON)."""
    nid = x["navi_id"]
    r = nv.rows(nid)
    src = clone_source(x, r)
    stats = [list(usa[PART_DATA + (src * 4 + k) * 16:][:16]) for k in range(4)]
    if x["leg_type"] in LEG_CODE:
        stats[3][1] = LEG_CODE[x["leg_type"]]
    for k in range(3):
        stats[k] = navi_part_record(scale, skills, nv, nid, k, stats[k])
    lg = nv.d[NAVI_LEGS + 8 * nid:][:8]
    stats[3][4] = max(1, scale.conv("armor", "legs", lg[1]))
    tclass = tech_class_table(usa)
    for k in range(3):
        stats[k][0] = tclass.get(stats[k][1], stats[k][0])
    stats[3][0] = stats[1][0]                          # pernas: a medalha do bot = a classe do braco direito
    for k in range(5):
        stats[3][5 + k] = leg_map[k](lg[2 + k])
    names = [x["parts"][p]["model"].replace("ー", "-") for p in PART_SLOTS]
    names = [p if p and p.isascii() else f'{x["model"]}-{SUFFIX[k]}' for k, p in enumerate(names)]
    parts = {}
    for k, slot in enumerate(PART_SLOTS):
        parts[slot] = {"name": names[k], "name_jp": x["parts"][slot].get("name_jp") or x["parts"][slot].get("model"),
                       "stats": stats_dict(stats[k], slot == "legs")}
    mc = None
    if any(e != 0x1818 for e in nv.rows(nid, form=True)[3]):
        fr = nv.d[FORM_LEGS + 8 * nid:][:8]
        assert fr[0] <= 6, (x["name"], list(fr))
        drives = {}
        for k, t in zip("ABC", DRIVE_TABLES):
            dr = nv.d[t + 12 * nid: t + 12 * nid + 12]
            skill, effect = NAVI_TO_CORE.get(dr[0], (0xFF, 0))
            typ = skills[0].get(skill, 0) if skill != 0xFF else 0
            g = CORE_KIND_GROUP.get(typ, "support")
            drives[k] = {"technique": skill, "medal_compat": tclass.get(skill, stats[k][0]), "speciality": typ, "success": scale.conv("success", g, dr[3]),
                         "power": scale.conv("power", g, dr[4]), "effect": EFFECTS[effect],
                         "navi": {"action": dr[0], "success": dr[3], "power": dr[4]}}
        mc = {"legs": dict(zip(FORM_LEG_KEYS, [100 + fr[0]] + [leg_map[k](fr[2 + k]) for k in range(5)])),
              "legs_navi": dict(zip(FORM_LEG_KEYS[1:], fr[2:7])), "drives": drives}
    return {"pack": "navi", "navi_id": nid, "slug": navi_slug(x["name"]), "name": SHORT.get(x["name"], x["name"]),
            "name_full": x["name"], "name_jp": x.get("name_jp"), "leg_type": x["leg_type"],
            "notes": "Gerado por tools/decomp_navi.py --export (stats do Navi na escala do Medabots). Editavel: o "
                     "gerador le este arquivo. Campos 'navi' / 'legs_navi' sao so referencia (valores originais).",
            "graphics_source": {"rom": NAVI_ROM.name, "navi_id": nid, "clone_for_missing_graphics": src},
            "parts": parts, "medachange": mc}


def navi_export(usa, navi_json, force=False):
    """Grava data/navi/bots/*.json (todos os 150 bots do Navi). Nao sobrescreve arquivos existentes (edicoes do
    usuario) sem force."""
    nv = Navi()
    scale, leg_map, skills = PartScale(usa, nv), leg_stat_to_core(usa, nv), core_skill_tables(usa)
    BOTS_DIR.mkdir(parents=True, exist_ok=True)
    wrote = kept = 0
    for x in navi_json:
        if x["navi_id"] >= 150:
            continue
        path = bot_json_path(x)
        if path.exists() and not force:
            kept += 1
            continue
        path.write_text(json.dumps(compute_bot(usa, nv, x, scale, leg_map, skills), ensure_ascii=False, indent=1)
                        + "\n", encoding="utf-8")
        wrote += 1
    print(f"data/navi/bots: {wrote} gravados, {kept} mantidos (ja existiam; --force reescreve)")


def flip_picture(lz, w, h):
    """Imagem 4bpp w x h (tiles 1D) espelhada na horizontal; recomprimida (so literais)."""
    px = lz77_decompress(lz, 0)[0]
    if len(px) < w * h // 2 or w % 8 or h % 8:
        return lz
    out = bytearray(px)
    across, down = w // 8, h // 8
    for ty in range(down):
        for tx in range(across):
            fr, to = 32 * (ty * across + tx), 32 * (ty * across + across - 1 - tx)
            for row in range(8):
                for b in range(4):
                    v = px[fr + 4 * row + b]
                    out[to + 4 * row + 3 - b] = ((v >> 4) | (v << 4)) & 0xFF
    return lz77_store(bytes(out))


def lowest_row(px, w, h):
    if px is None or w < 8:
        return -1
    across = w // 8
    for row in range(h - 1, -1, -1):
        for tile in range(across):
            at = 32 * ((row // 8) * across + tile) + 4 * (row % 8)
            if at + 4 <= len(px) and any(px[at:at + 4]):
                return row
    return -1


FORM_CUSTOM_TOP = 127   # moldes proprios das formas de bot proprio: 127, 126, ... (os de molds.json vem de 1 para cima)


def plan(usa, navi_json, existing_names, ptrs, select=None, own_forms=(), mini_banks=None):
    """Escolhe os bots do Navi (sem Tinpet e sem os que ja existem) e monta tudo. Devolve (bots, asm, info).
    ptrs: offset USA de uma palavra-ponteiro -> simbolo (config/data_ptrs, como no decomp_expand).
    mini_banks: as 4 paletas de mini sprite da build (16 cores cada; a 4a e a extra dos bots novos), para o mini de
    um bot do Navi com desenho proprio ("art" no JSON, pasta no formato do export_template, ja limpa)."""
    from gfx_port import art_mini, palette_bgr555, png_tiles

    def ptr(off):
        return ptrs.get(off) or f"0x{u32(usa, off):08X}"
    nv = Navi()
    scale = PartScale(usa, nv)
    leg_map = leg_stat_to_core(usa, nv)
    skills = core_skill_tables(usa)
    core_type = skills[0]                             # tecnica do Medabots -> tipo mais usado (SKILL_TYPE_*)
    # select = nomes da lista de bots (navi_slug) ou None = todos. A escala dos stats (PartScale, leg_map) usa sempre
    # todos os bots do Navi, entao os numeros de um bot nao mudam com a lista.
    pick = [x for x in navi_json if x["navi_id"] < 150 and x["name"].lower() not in existing_names
            and (select is None or navi_slug(x["name"]) in select)]
    rows = [nv.rows(x["navi_id"]) for x in pick]
    # formas de Medachange (fase 2): so desenho, pendurado na junta das pernas; ids depois do Tinpet (fora da contagem)
    form_owner = []                                   # indice do bot em `pick` dono de cada forma
    form_rows = []
    for i, x in enumerate(pick):
        legs = [e for e in nv.rows(x["navi_id"], form=True)[3] if e != 0x1818]
        if legs and load_bot_json(x)["medachange"] is not None:   # medachange: null no JSON = sem forma
            form_owner.append(i)
            form_rows.append([[], [], [], legs])
    units = rows + form_rows                          # bots e formas passam pelo mesmo caminho (moldes, arte, chao)

    used = sorted({e & 0x3F for r in units for part in r for e in part})
    unknown = [m for m in used if m not in SAME_SHAPE and m not in NEW_ANALOG]
    assert not unknown, f"moldes do Navi sem par: {unknown}"
    new_ids = [m for m in used if m not in SAME_SHAPE]
    blank = ORIG_MOLDS + len(new_ids)                 # molde vazio: cabeca e bracos da forma (o jogo le a 1a entrada)
    assert blank < MOLDS, f"{len(new_ids)} moldes novos + o vazio nao cabem em {MOLDS}"
    mp = dict(SAME_SHAPE)
    mp.update({m: ORIG_MOLDS + i for i, m in enumerate(new_ids)})
    limb_root = {}
    for r in units:
        for part, ent in enumerate(r):
            if ent:
                limb_root[ent[0] & 0x3F] = part
    inner = {e & 0x3F for r in units for ent in r for e in ent[1:]} & set(limb_root)
    assert not inner, f"molde raiz num bot e interno noutro: {inner}"
    # pedacos filhos das formas (31 -> 32; 35 -> 36, 37): sem movimento proprio, colados na raiz (o filho soma o
    # movimento do pai; com a linha das pernas dele tambem, a forma abria uma costura vertical no desvio e no ataque)
    form_child = {e & 0x3F for r in form_rows for ent in r for e in ent[1:]}
    assert not form_child & {e & 0x3F for r in rows for ent in r for e in ent}, "pedaco de forma usado por bot"
    analog = {m: (CORE_LIMB_ROOTS[limb_root[m]] if m in limb_root else NEW_ANALOG[m]) for m in new_ids}

    def core_record(mold):
        return bytearray(usa[u32(usa, CORE_MOLDS + 4 * mold) - GBA:][:0x18])

    records = {}            # alvo -> registro (bytes 4..0x17; lista em gNaviArt<alvo>)
    body2 = nv.record(2)
    for m in used:
        t = mp[m]
        rec = core_record(t if t < ORIG_MOLDS else analog[m])
        nrec = nv.record(m)
        rec[4:0x0F] = nrec[4:0x0F]
        if m in limb_root:
            part = limb_root[m]
            j = nv.joint(part)
            body = [struct.unpack_from("b", body2, 0x0C + k)[0] for k in range(3)] if part < 3 else [0, 0, 0]
            for k in range(3):
                v = struct.unpack_from("b", rec, 0x0C + k)[0] + j[k] + body[k]
                rec[0x0C + k] = v & 0xFF
        rec[0x0F] = 0 if nrec[0x0F] == 0 else mp[nrec[0x0F]]
        rec[0x10] = 0 if nrec[0x10] == 0 else mp[nrec[0x10]]
        rec[0x12], rec[0x13] = nrec[0x12], nrec[0x13]
        records[t] = rec

    # molde vazio: 8x8 transparente, sem paleta, sem filhos
    brec = bytearray(0x18)
    brec[0x12] = brec[0x13] = 8
    brec[0x14] = 0x11
    records[blank] = brec
    # esqueleto editado (data/anim/molds.json, "navi"): antes das imagens e da linha do chao, que usam os registros
    import anim_molds
    edited = anim_molds.apply_navi(records)
    if edited:
        merged = {m: r for m, (_, r) in anim_molds.core_records(usa).items()}
        merged.update(records)
        anim_molds.check_tree(merged, "navi")
        print(f"  esqueleto (data/anim/molds.json): moldes do Navi editados: {edited}")

    # arte: lista propria por alvo (seletor 1..), entradas novas com o bit 16
    lists = {t: [None] * 256 for t in records}       # (rotulo imagem, rotulo paleta)
    blobs = [("sNaviBlankImg", lz77_store(bytes(32)))]   # (rotulo, bytes)
    lists[blank] = [("sNaviBlankImg", "0")] * 256
    blank_entry = blank | (1 << 6) | NAVI_BIT
    turn = {mp[m]: TURN_FROM[NEW_ANALOG[m]] for m in new_ids if NEW_ANALOG[m] in TURN_FROM}
    nxt = {}
    bot_rows = []
    # desenho proprio (aba Art do WPF): pecas com o nome do export_template (large_<peca>_<n>_m<molde>[_pose<k>].png)
    art_dirs = {b: ROOT / load_bot_json(x)["art"] for b, x in enumerate(pick) if load_bot_json(x).get("art")}
    own_pieces = 0
    for b, r in enumerate(units):
        out_rows = []
        for part, ent in enumerate(r):
            words = []
            rotate = True
            if b < len(rows):
                rotate = load_bot_json(pick[b])["parts"][PART_SLOTS[part]].get("rotate", True)
            for idx, e in enumerate(ent):
                t = mp[e & 0x3F]
                if t in turn and rotate:
                    e |= 0x4000                       # bit de giro (SpriteTileRef.affine)
                pairs = nv.art(e)
                sel = nxt.get(t, 1)
                assert sel + len(pairs) <= 256, f"molde {t}: sem vaga de imagem (precisa do seletor estendido)"
                nxt[t] = sel + len(pairs)
                for pose, (img, pal) in enumerate(pairs):
                    suffix = f"_pose{pose + 1}" if len(pairs) > 1 else ""
                    png = (art_dirs[b] / f"large_{KIND_PT[part]}_{idx + 1}_m{t:02d}{suffix}.png") if b in art_dirs else None
                    if png is not None and png.exists():
                        w, h = records[t][0x13], records[t][0x12]     # +0x13 largura, +0x12 altura
                        raw, ppal = png_tiles(png, w, h)
                        img = lz77_store(raw)
                        if pal is not None:
                            pal = bytes(palette_bgr555(ppal))
                        own_pieces += 1
                    elif pose == 1 and not e & 0x4000:
                        nrec = nv.record(e & 0x3F)
                        img = flip_picture(img, nrec[0x13], nrec[0x12])
                    li = f"sNaviImg{len(blobs)}"
                    blobs.append((li, img))
                    lp = li
                    if pal is not None:
                        lp = f"sNaviImg{len(blobs)}"
                        blobs.append((lp, pal))
                    lists[t][sel + pose] = (li, lp)
                words.append((e & ~0x3F & ~(0xFF << 6)) | t | (sel << 6) | NAVI_BIT)
            if not words and b >= len(rows):
                words = [blank_entry]                 # forma: cabeca e bracos vazios
            out_rows.append(words)
        bot_rows.append(out_rows)
    for t, L in lists.items():
        first = next(p for p in L if p)
        lists[t] = [p or first for p in L]

    # linha do chao (pose parada): fundo de cada bot vs mediana dos bots 0..119 do Medabots
    def image_px(table_navi, mold, entry):
        if table_navi:
            li = lists[mold][(entry >> 6) & 0xFF][0]
            data = dict(blobs)[li]
            return lz77_decompress(data, 0)[0]
        rec = u32(usa, CORE_MOLDS + 4 * mold) - GBA
        img = u32(usa, u32(usa, rec) - GBA + 8 * ((entry >> 6) & 0xFF)) - GBA
        try:
            return lz77_decompress(usa, img)[0]
        except Exception:
            return None

    def rec_of(navi_tab, mold):
        if navi_tab:
            return records.get(mold) or core_record(mold)
        return core_record(mold)

    def bottom(row_words):
        best = None
        for part in range(4):
            ent = {}
            first = 0
            for e in row_words[part]:
                if e & 0x3F == 0:
                    break
                first = first or e
                ent.setdefault(e & 0x3F, e)
            if not first:
                continue
            stack = [(first & 0x3F, 0, 0)]
            while stack:
                mold, parent, depth = stack.pop()
                if depth > 16:
                    continue
                e = ent.get(mold)
                nav = bool(e and e & NAVI_BIT)
                rec = rec_of(nav, mold)
                at = parent + struct.unpack_from("b", rec, 0x0C)[0]
                if e is not None:
                    px = image_px(nav, mold, e)
                    low = lowest_row(px, rec[0x13], rec[0x12])
                    if low >= 0:
                        bt = at - struct.unpack_from("<i", rec, 4)[0] + low + 1
                        best = bt if best is None else max(best, bt)
                if rec[0x10]:
                    stack.append((rec[0x10], at, depth + 1))
                if rec[0x0F]:
                    stack.append((rec[0x0F], parent, depth + 1))
        return best

    core_bottoms = []
    for bid in range(120):
        rw = [[u32(usa, o + bid * s + 4 * k) for k in range(s // 4)] for o, s in CORE_ROWS]
        v = bottom(rw)
        if v is not None:
            core_bottoms.append(v)
    core_bottoms.sort()
    ground = core_bottoms[len(core_bottoms) // 2]
    for rws in bot_rows:
        v = bottom(rws)
        if v is None or not rws[3]:
            continue
        lift = max(-128, min(127, v - ground))
        rws[3][0] = (rws[3][0] & 0x00FFFFFF) | ((lift & 0xFF) << 24)

    # bots (clones do bot do Medabots com a mesma geometria de pernas)
    names = ("gHeadPartSpriteNodes", "gRightArmPartSpriteNodes", "gLeftArmPartSpriteNodes", "gLegPartSpriteNodes")
    sizes = (4, 4, 4, 8)
    bots = []
    for x, r, rws in zip(pick, rows, bot_rows):
        d = load_bot_json(x)
        src = clone_source(x, r)
        stats = [stats_bytes(d["parts"][p]["stats"]) for p in PART_SLOTS]
        parts = [d["parts"][p]["name"] for p in PART_SLOTS]
        rowsw = {nm: (rws[k] + [0] * sizes[k])[:sizes[k]] for k, nm in enumerate(names)}
        bots.append({"name": d["name"], "parts": parts, "clone": src, "stats": stats,
                     "rows": rowsw, "navi_id": x["navi_id"], "form": 0, "json": d})
    # mini do desenho proprio: cores na paleta de mini mais proxima das 4 da build (como os bots de data/bots)
    mini_asm = []
    if art_dirs and mini_banks:
        import mini_palette
        for b, folder in art_dirs.items():
            if not (folder / "mini_cabeca.png").exists():
                continue
            src_pal, comps = art_mini(folder, bots[b]["name"])
            cnt = mini_palette.color_usage(comps)
            bank = min(range(len(mini_banks)), key=lambda k: mini_palette.cost(src_pal, cnt, mini_banks[k]))
            lut = [0] + [mini_palette.nearest(src_pal[i], mini_banks[bank]) for i in range(1, 16)]
            lab = f"sNaviOwnMini{b}"
            for k, payload in enumerate(comps):
                blob = mini_palette.malias_store(bytes(lut[v & 15] | lut[v >> 4] << 4 for v in payload))
                mini_asm.append(f"\t.align 2\n{lab}_{k}:\n\t.byte " + ", ".join(f"0x{v:02X}" for v in blob) + "\n")
            bots[b]["rows_asm"] = {"gMedabotPartSpriteTiles": "\t.4byte " + ", ".join(f"{lab}_{k}" for k in range(6)) + "\n",
                                   "gMedabotSpritePalettes": f"\t.byte {bank}\n"}
            print(f"  desenho proprio de {bots[b]['name']}: mini no banco de paleta {bank}")
    if art_dirs:
        print(f"  desenho proprio (Navi): {len(art_dirs)} bot(s), {own_pieces} pedaco(s) grandes")

    # formas: numero 1.. no bot dono (gNaviMedachange); linhas proprias para os ids N+2.. (depois do Tinpet)
    forms = []
    for k, (i, rws) in enumerate(zip(form_owner, bot_rows[len(rows):])):
        bots[i]["form"] = k + 1
        forms.append({"owner": i, "clone": bots[i]["clone"], "stats": bots[i]["stats"],
                      "rows": {nm: (rws[j] + [0] * sizes[j])[:sizes[j]] for j, nm in enumerate(names)}})

    # formas de bots proprios (data/bots com "medachange"; 2026-11-24): depois das do Navi. Cabeca e bracos com o molde
    # vazio; perna = a entrada de perna de um bot do jogo (padrao Tankar 89: molde 30, perna inteira 64x64) com um molde
    # proprio carregando o desenho da forma ("picture"). own_forms = [(id do bot, json do bot)].
    own = []
    for j, (bid, bj) in enumerate(own_forms):
        mc = bj["medachange"]
        src = mc.get("legs_from", 89)
        word = u32(usa, CORE_ROWS[3][0] + src * CORE_ROWS[3][1])
        custom = FORM_CUSTOM_TOP - j
        legs_word = (word & ~(0x7F << 17)) | (custom << 17)
        forms.append({"owner": None, "own_bot": bid, "clone": src, "custom": custom, "node": word & 0x3F,
                      "picture": mc.get("picture"),
                      "stats": [[v for v in bj["parts"][p]["stats"].values()] for p in PART_SLOTS],
                      "rows": {nm: ([legs_word] + [0] * 7 if k == 3 else [blank_entry] + [0] * 3)
                               for k, nm in enumerate(names)}})
        own.append((len(forms), bj))

    # ---- asm ----
    a = ["\n@ ---- Medarot Navi (tools/decomp_navi.py) ----\n"]
    core = [ptr(CORE_MOLDS + 4 * m) for m in range(ORIG_MOLDS)] + ["0"] * (MOLDS - ORIG_MOLDS)
    for t in records:
        if t >= ORIG_MOLDS:
            core[t] = f"gNaviNode{t}"
    a.append("\t.align 2\n\t.global gMedabotSpriteNodeDescs\ngMedabotSpriteNodeDescs:   @ 64 moldes\n")
    a += [f"\t.4byte {v}\n" for v in core]
    a.append("\t.align 2\n\t.global gNaviSpriteNodeDescs\ngNaviSpriteNodeDescs:\n")
    a += [f"\t.4byte {('gNaviNode%d' % m) if m in records else core[m]}\n" for m in range(MOLDS)]
    for t in sorted(records):
        rec = records[t]
        a.append(f"\t.align 2\ngNaviNode{t}:\n\t.4byte gNaviArt{t}\n\t.byte " +
                 ", ".join(f"0x{v:02X}" for v in rec[4:0x18]) + "\n")
        a.append(f"\t.align 2\ngNaviArt{t}:\n")
        for li, lp in lists[t]:
            a.append(f"\t.4byte {li}, {lp}\n")
    for lab, data in blobs:
        a.append(f"\t.align 2\n{lab}:\n")
        for i in range(0, len(data), 32):
            a.append("\t.byte " + ", ".join(f"0x{v:02X}" for v in data[i:i + 32]) + "\n")

    # mapa de espelho com 64
    mir = list(usa[MIRROR:MIRROR + ORIG_MOLDS]) + list(range(ORIG_MOLDS, MOLDS))
    newm = {m: mp[m] for m in new_ids}
    for rgt, lft in MIRROR_PAIRS:
        if rgt in newm and lft in newm:
            mir[newm[rgt]], mir[newm[lft]] = newm[lft], newm[rgt]
    a.append("\t.global gMirroredPartNodeNavi\ngMirroredPartNodeNavi:\n\t.byte " + ", ".join(map(str, mir)) + "\n")

    # movimento: 63 linhas por bloco; moldes novos copiam a linha do analogo
    # As pecas grandes (64x32 / 64x64) nao giram em nenhum dos dois jogos (bit 14 sempre 0): animam por translacao.
    # O Medabots tem linhas proprias para as suas pecas unicas (braco 19 / 16, cabeca 13, pernas 30: Noctobat,
    # Armorparadeen); as linhas do 1o pedaco do membro (17 / 14 / 7 / 20) so tem giro, e com elas o bot do Navi
    # ficava parado nos ataques. Por isso o movimento vem sempre do analogo de mesmo formato (NEW_ANALOG).
    row_src = {mp[m]: NEW_ANALOG[m] for m in new_ids}
    import anim_poses
    pose_docs = anim_poses.load_all()
    moved = {}
    tabs = {"gPoseKeyframeAngles": POSE_ANG, "gPoseKeyframeOffsets": POSE_OFF}
    ptr_lines = {k: [] for k in tabs}
    # quadros-chave pelos "ends" do JSON (editaveis; gPoseKeyframeEnds sai deles em anim_poses.apply) e roteiros
    # novos (ids 59+, arquivos novos em data/anim/poses)
    for s in range(max(pose_docs) + 1):
        keys = len(pose_docs[s]["ends"])
        for nm, tab in tabs.items():
            old = u32(usa, tab + 4 * s) - GBA if s < POSE_SCRIPTS else ("novo", s)
            if keys == 0:
                ptr_lines[nm].append(ptr(tab + 4 * s) if s < POSE_SCRIPTS else "0")
                continue
            if old not in moved:
                # linhas do jogo pelos JSON de data/anim/poses (tools/anim_poses.py); moldes do Navi copiam o analogo,
                # pedacos-filhos das formas ficam parados; "navi/MM" no JSON sobrescreve
                row = keys * 2
                kind = "angles" if nm == "gPoseKeyframeAngles" else "offsets"
                data, put, src = anim_poses.block_bytes(pose_docs, s, kind, MOTION_ROWS, keys, None)
                for mold, srcm in row_src.items():
                    data[(mold - 1) * row:mold * row] = data[(srcm - 1) * row:srcm * row]
                if kind == "angles":
                    for mold, (ra, rb) in turn.items():
                        va = struct.unpack_from(f"<{keys}h", data, (ra - 1) * row)
                        vb = struct.unpack_from(f"<{keys}h", data, (rb - 1) * row)
                        struct.pack_into(f"<{keys}h", data, (mold - 1) * row,
                                         *(((x + y + 0x8000) & 0xFFFF) - 0x8000 for x, y in zip(va, vb)))
                for m in form_child:
                    data[(mp[m] - 1) * row:mp[m] * row] = bytes(row)
                for name, vals in src.items():
                    if name.startswith("navi/") and int(name[5:]) in mp:
                        put(mp[int(name[5:])], vals)
                lab = f"sNaviPose{len(moved)}"
                moved[old] = lab
                a.append(f"\t.align 2\n{lab}:\n")
                for i in range(0, len(data), 32):
                    a.append("\t.byte " + ", ".join(f"0x{v:02X}" for v in data[i:i + 32]) + "\n")
            ptr_lines[nm].append(moved[old])
    for nm, lst in ptr_lines.items():
        a.append(f"\t.align 2\n\t.global {nm}\n{nm}:\n")
        for p in lst:
            a.append(f"\t.4byte {p}\n")
    # Medachange (fase 2): rotulo na cruz de MF (fonte dos nomes, fim 0xFE) e mensagens da luta (pausa 0xFA 0x50, fim 0xFF)
    from medarom import encode_text
    for lab, text in [("sMedachangeLabel", "Medachange"), ("sMedachangeBackLabel", "Change back")]:
        a.append(f"\t.global {lab}\n{lab}:\n\t.byte " + ", ".join(f"0x{c:02X}" for c in encode_text(text)) + "\n")
    # Drives (Drive A/B/C = H/R/L na forma): por forma, 3 x {tecnica do Medabots, tipo, acerto, forca, efeito extra}.
    # Tecnica 0xFF = sem traducao ainda (a peca fica como esta). Registro do Navi (12 B): byte 0 acao, 1 tipo (nibble
    # baixo; nibble alto 1 = Chain Reaction), 2 armadura, 3 acerto, 4 forca, 5 usos (cabeca) / AP (bracos), 6-8
    # forma/alcance, 9 usos/alvos. Acerto e forca na escala do Medabots por posicao (PartScale).
    a.append("\t.align 2\n\t.global gNaviDrives\ngNaviDrives:   @ [forma][drive] = tecnica, tipo, acerto, forca, efeito, anim, emit dx, dy, chain, classe, qtd\n")
    for owner in form_owner:
        mc = bots[owner]["json"]["medachange"]
        row = []
        for k in "ABC":
            dv = mc["drives"][k]
            anim = dv.get("anim")
            emit = dv.get("emit") or [0, 0]
            medal = dv.get("medal_compat")
            amount = dv.get("effect_amount")
            if amount is None:
                t = DRIVE_TABLES["ABC".index(k)]
                amount = nv.d[t + 12 * bots[owner]["navi_id"] + 4]
            chain = dv.get("chain_reaction")
            if chain is None:   # sem o campo no JSON: o do Navi (nibble alto do byte 1 do registro do Drive)
                t = DRIVE_TABLES["ABC".index(k)]
                chain = int(nv.d[t + 12 * bots[owner]["navi_id"] + 1] >> 4 == 1)
            row += [dv["technique"], dv["speciality"], dv["success"], dv["power"], EFFECTS.index(dv["effect"]),
                    0xFF if anim is None else anim, emit[0] & 0xFF, emit[1] & 0xFF,   # anim / emit do Drive (opcionais)
                    1 if chain else 0,                                                  # Chain Reaction do Drive
                    0xFF if medal is None else medal,                                   # classe (medal_compat) do Drive
                    min(255, max(0, amount))]                                           # quantidade do efeito
        a.append("\t.byte " + ", ".join(str(v) for v in row) + "\n")
    for _, bj in own:   # formas de bots proprios: tudo do JSON (quantidade = navi.power ou 0; chain do JSON)
        row = []
        for k in "ABC":
            dv = bj["medachange"]["drives"][k]
            anim, emit, medal = dv.get("anim"), dv.get("emit") or [0, 0], dv.get("medal_compat")
            amount = dv.get("effect_amount", (dv.get("navi") or {}).get("power", 0))
            row += [dv["technique"], dv["speciality"], dv["success"], dv["power"], EFFECTS.index(dv.get("effect", "none")),
                    0xFF if anim is None else anim, emit[0] & 0xFF, emit[1] & 0xFF, 1 if dv.get("chain_reaction") else 0,
                    0xFF if medal is None else medal, min(255, max(0, amount))]
        a.append("\t.byte " + ", ".join(str(v) for v in row) + "\n")
    # Pernas da forma (Navi 0x9BA30, 8 B por bot: tipo 0..6, armadura, propulsao, esquiva, defesa, proximidade,
    # distancia, 0). Tipo = mesma ordem do Medabots (Flying 100 .. Aquatic 106). Os stats passam pela escala do
    # Medabots (leg_stat_to_core): as formas do Navi vao bem alem do teto do jogo (proximidade ate 96; max 29 aqui).
    a.append("\t.align 2\n\t.global gNaviFormLegs\ngNaviFormLegs:   @ [forma] = tipo, propulsao, esquiva, defesa, "
             "proximidade, distancia (escala do Medabots)\n")
    for owner in form_owner:
        fl = bots[owner]["json"]["medachange"]["legs"]
        a.append("\t.byte " + ", ".join(str(fl[k]) for k in FORM_LEG_KEYS) + "\n")
    for _, bj in own:
        fl = bj["medachange"]["legs"]
        a.append("\t.byte " + ", ".join(str(fl[k]) for k in FORM_LEG_KEYS) + "\n")
    for lab, text in [("sNaviProxDownMsg", "Proximity down!"), ("sNaviRemoteDownMsg", "Remoteness down!"),
                      ("sNaviProxUpMsg", "Proximity up!"), ("sNaviRemoteUpMsg", "Remoteness up!"),
                      ("sNaviLevelDrainMsg", "Medal level drained!"), ("sNaviDetectMsg", "Accuracy up!"),
                      ("sNaviSpeedMsg", "Speed up!"), ("sNaviForceMsg", "Medaforce charging!")]:
        data = encode_text(text)[:-1] + b"\xFA\x50\xFF\x04"   # FF + modo de fim 4, como as da luta do jogo
        a.append(f"\t.global {lab}\n{lab}:\n\t.byte " + ", ".join(f"0x{c:02X}" for c in data) + "\n")
    for lab, text in [("sMedachangeOnMsg", "Medachange!"), ("sMedachangeOffMsg", "Back to normal form!")]:
        data = encode_text(text)[:-1] + b"\xFA\x50\xFF\x04"   # FF + modo de fim 4, como as da luta do jogo
        a.append(f"\t.global {lab}\n{lab}:\n\t.byte " + ", ".join(f"0x{c:02X}" for c in data) + "\n")
    # bots do Navi com forma que ja existiam na base (pulados acima, ex.: Granbeetle 181): o Medachange vale para eles
    skipped_forms = [x["name"].lower() for x in navi_json
                     if x["navi_id"] < 150 and x["name"].lower() in existing_names
                     and any(e != 0x1818 for e in nv.rows(x["navi_id"], form=True)[3])]
    info = {"forms": len(forms), "form_rows": forms, "blank_mold": blank, "skipped_forms": skipped_forms,
            "molds_new": {m: mp[m] for m in new_ids}, "ground": ground, "images": len(blobs),
            "records": {t: bytes(r) for t, r in records.items()},   # base "navi:N" dos moldes proprios
            "selectors": dict(sorted(nxt.items())), "pose_blocks": len(moved),
            # linhas de movimento dos moldes do Navi: alvo -> molde do jogo copiado; pedacos de forma parados
            "pose_rows": {"copy": {str(t): s for t, s in sorted(row_src.items())},
                          "still": sorted(mp[m] for m in form_child),
                          "turn": {str(t): list(v) for t, v in sorted(turn.items())}}}
    a += mini_asm
    return bots, "".join(a), info


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Bots do Medarot Navi: --export grava data/navi/bots/*.json")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--force", action="store_true", help="reescreve JSONs ja existentes (perde edicoes)")
    ap.add_argument("--baserom", default=str(__import__("paths").DECOMP / "baserom.gba"))
    a = ap.parse_args()
    if a.export:
        navi_export(Path(a.baserom).read_bytes(),
                    json.loads((ROOT / "data/navi/navi_bots.json").read_text(encoding="utf-8")), a.force)
    else:
        ap.print_help()
