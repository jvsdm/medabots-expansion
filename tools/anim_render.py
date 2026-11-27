"""anim_render.py - Renderizador de referencia do esqueleto dos Medabots (batalha), igual ao jogo.

Reproduz src/engine/sprite_engine.c (render_sprite_node_recursive, load_sprite_tree_recursive) e a interpolacao de
pose (src/engine/interpolate.c, common.c medabot_pose_anim_step). Le os dados de uma ROM + o .map da build (vanilla
ou expansao; nas builds com EXP_NAVI_SPRITES entende o bit `navi` e o `lift`).

Nomes trocados no C (conferido em set_oam_sprite_shape_size, cujo 1o argumento e a altura): na SpriteNodeDesc os
campos "X" sao verticais e os "Y" horizontais (width = altura, pivotX = pivo vertical, jointX = junta vertical);
na SpriteNodeOam offsetX = deslocamento vertical. Aqui os nomes sao os de verdade (v = vertical, h = horizontal).
O parametro "y" de render_sprite_node_recursive e o Y da tela (o chamador passa x << 8 nele... com x = linha).

Uso:
  python tools/anim_render.py --rom R --map M --bot 120 --pose 7 --png out.png [--side 1] [--frames]
  (sem --pose: pose neutra). --frames grava um PNG por quadro (out_000.png ...).
"""
import argparse
import math
import re
import struct
from pathlib import Path

from codecs_gba import lz77_decompress

GBA = 0x08000000
NODES = 0x40            # linhas de estado por arvore (interpolate_entity_positions count)


def load_map(path):
    syms = {}
    pat = re.compile(r"^\s*0x([0-9a-fA-F]{8})\s+(g\w+)")
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = pat.match(line)
        if m:
            syms.setdefault(m.group(2), int(m.group(1), 16))
    return syms


def affine_set(rot, sx=0x100, sy=0x100):
    """ObjAffineSet (HLE do mGBA): angulo u16, so os 8 bits altos contam."""
    theta = ((rot & 0xFFFF) >> 8) / 128.0 * math.pi
    a = d = math.cos(theta)
    b = c = math.sin(theta)
    s16 = lambda v: ((int(v) + 0x8000) & 0xFFFF) - 0x8000
    return s16(a * sx / 256 * 256), s16(-b * sx / 256 * 256), s16(c * sy / 256 * 256), s16(d * sy / 256 * 256)


def tdiv(a, b):
    """Div da BIOS: trunca para zero."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q


class Desc:
    __slots__ = ("frames", "pv", "ph", "jv", "jh", "depth", "sibling", "child", "pal", "h", "w", "hdiv", "wdiv",
                 "bpp", "affine_mode", "obj_mode", "hflip", "vflip")

    @classmethod
    def parse(cls, b):
        d = cls()
        d.frames, d.pv, d.ph = struct.unpack_from("<Iii", b, 0)
        d.jv, d.jh, d.depth = struct.unpack_from("<bbb", b, 12)
        d.sibling, d.child, d.pal, d.h, d.w, div, fl = b[15:22]
        d.hdiv, d.wdiv = div & 15, div >> 4
        d.bpp, d.affine_mode, d.obj_mode = fl & 1, (fl >> 1) & 3, (fl >> 3) & 3
        d.hflip, d.vflip = (fl >> 5) & 1, (fl >> 6) & 1
        return d

    def copy(self):
        d = Desc()
        for k in self.__slots__:
            setattr(d, k, getattr(self, k))
        return d


class PartLists(list):
    """As 4 listas de Ref de um bot; .swap = (lista do braco esquerdo da peca do braco direito, e o contrario)."""
    swap = None


class Ref:
    __slots__ = ("node", "frame", "affine", "alt", "navi", "lift", "custom")

    def __init__(self, v):
        self.node, self.frame = v & 0x3F, (v >> 6) & 0xFF
        self.affine, self.alt, self.navi = (v >> 14) & 1, (v >> 15) & 1, (v >> 16) & 1
        self.lift = ((v >> 24) & 0xFF) - (0x100 if v >> 31 else 0)
        self.custom = (v >> 17) & 0x7F          # molde proprio do bot (EXP_CUSTOM_MOLDS, gCustomSpriteNodeDescs)


class Rig:
    """Dados do esqueleto de uma build: moldes, listas de peca, poses."""

    def __init__(self, rom, map_path):
        self.rom = Path(rom).read_bytes()
        self.sym = load_map(map_path)
        self.navi = "gNaviSpriteNodeDescs" in self.sym
        self.core = self._desc_table("gMedabotSpriteNodeDescs")
        self.navi_descs = self._desc_table("gNaviSpriteNodeDescs") if self.navi else None
        self.mirror = self.rom[self.off("gMirroredPartNode"):self.off("gMirroredPartNode") + NODES]
        self.customs = {}                       # moldes proprios: gCustomSpriteNodeDescs[1..127]
        if "gCustomSpriteNodeDescs" in self.sym:
            t = self.off("gCustomSpriteNodeDescs")
            for c in range(1, 128):
                q = self.u32(t + 4 * c)
                if q == 0:
                    continue
                if q >> 24 != 0x08 or q - GBA >= len(self.rom) - 0x18:
                    break
                self.customs[c] = Desc.parse(self.rom[q - GBA:q - GBA + 0x18])
        self.mirror_navi = (self.rom[self.off("gMirroredPartNodeNavi"):self.off("gMirroredPartNodeNavi") + NODES]
                            if "gMirroredPartNodeNavi" in self.sym else self.mirror)

    def off(self, name):
        return self.sym[name] - GBA

    def u32(self, o):
        return struct.unpack_from("<I", self.rom, o)[0]

    def _desc_table(self, name):
        by_addr = {a: n for n, a in self.sym.items()}
        base, out = self.off(name), {}
        for n in range(1, NODES):
            p = self.u32(base + 4 * n)
            if p >> 24 == 0x08 and p - GBA < len(self.rom) - 0x18:
                out[n] = Desc.parse(self.rom[p - GBA:p - GBA + 0x18])
            elif p >> 24 == 0x03 and by_addr.get(p, "").endswith("PartLayer"):
                t = self.off(by_addr[p] + "Template")     # camada de peca: copia do modelo na ROM
                d = Desc.parse(self.rom[t:t + 0x18])
                out[n] = d
                out.setdefault("_layers", {})[n] = by_addr[p]
            else:
                if n > 1 and not any(self.u32(base + 4 * k) for k in range(n, min(n + 4, NODES))):
                    break
        return out

    def part_lists(self, bot, parts=None):
        """4 listas (cabeca, braco dir., braco esq., pernas) de Ref; parts = ids por peca (padrao: o bot)."""
        parts = parts or (bot, bot, bot, bot)
        names = ("gHeadPartSpriteNodes", "gRightArmPartSpriteNodes", "gLeftArmPartSpriteNodes", "gLegPartSpriteNodes")
        out = PartLists(self.part_list(name, pid) for name, pid in zip(names, parts))
        # lado 1: a lista do braco oposto da mesma peca (load_sprite_tiles_by_table troca as imagens dos bracos)
        out.swap = (self.part_list("gLeftArmPartSpriteNodes", parts[1]),
                    self.part_list("gRightArmPartSpriteNodes", parts[2]))
        return out

    def part_list(self, name, pid):
        stride = 32 if name.startswith("gLeg") else 16
        o = self.off(name) + pid * stride
        refs = []
        for k in range(stride // 4):
            r = Ref(self.u32(o + 4 * k))
            if not r.node:
                break
            refs.append(r)
        return refs

    # ---- poses
    def pose_script(self, anim, legs):
        """gPoseAnimIds[anim][gLegPartPoseSets[legs]] (u32 [][7])."""
        col = self.rom[self.off("gLegPartPoseSets") + legs]
        return self.u32(self.off("gPoseAnimIds") + (anim * 7 + col) * 4)

    def pose_tables(self, s):
        ends_p = self.u32(self.off("gPoseKeyframeEnds") + 4 * s) - GBA
        n = 0
        while self.rom[ends_p + n]:
            n += 1
        ends = list(self.rom[ends_p:ends_p + n])
        ang = self.u32(self.off("gPoseKeyframeAngles") + 4 * s) - GBA
        off = self.u32(self.off("gPoseKeyframeOffsets") + 4 * s) - GBA
        return ends, ang, off


class Pose:
    """Estado por no (rotacao, deslocamento 8.8 v/h) e o passo da interpolacao igual ao jogo."""

    def __init__(self):
        self.rot = [0] * NODES
        self.ov = [0] * NODES
        self.oh = [0] * NODES

    def step_key(self, rig, s, key, frame):
        """interpolate_entity_positions(frame, idx=key). Retorna quantos nos chegaram."""
        ends, ang, off = rig.pose_tables(s)
        n, end, done = len(ends), ends[key], 0
        for i in range(1, NODES):
            target = struct.unpack_from("<h", rig.rom, ang + ((i - 1) * n + key) * 2)[0]
            tv, th = struct.unpack_from("<bb", rig.rom, off + ((i - 1) * n + key) * 2)
            if frame < end:
                rem = end - frame
                cur = ((self.rot[i] + 0x8000) & 0xFFFF) - 0x8000   # s16 angle
                c = [target - cur, target - (cur - 0x10000), target - (cur + 0x10000)]
                a = [abs(x) for x in c]
                if a[0] > a[1]:
                    delta = c[2] if a[1] > a[2] else c[1]
                else:
                    delta = c[2] if a[0] > a[2] else c[0]
                self.rot[i] = (cur + tdiv(delta, rem)) & 0xFFFF
                self.ov[i] = s16(self.ov[i] + tdiv((tv << 8) - self.ov[i], rem))
                self.oh[i] = s16(self.oh[i] + tdiv((th << 8) - self.oh[i], rem))
            else:
                self.rot[i] = target & 0xFFFF
                self.ov[i], self.oh[i] = tv << 8, th << 8
                done += 1
        return done

    def frames(self, rig, s):
        """Gera o estado depois de cada quadro do roteiro s (medabot_pose_anim_step ate voltar 1)."""
        ends = rig.pose_tables(s)[0]
        key, cnt = 0, 0
        while key < len(ends):
            cnt += 1
            if self.step_key(rig, s, key, cnt):
                key += 1
                cnt = 0
            yield self


def s16(v):
    return ((v + 0x8000) & 0xFFFF) - 0x8000


class Sprite:
    __slots__ = ("y", "x", "w", "h", "affine", "double", "mat", "hflip", "vflip", "z", "pixels", "pal", "bpp", "node", "jx", "jy")


def render_tree(rig, lists, pose, sx, sy, depth=200, side=0, no_affine=False):
    """Lista de Sprite (ordem da OAM: o primeiro fica na frente), como setup_medabot_part_sprites + o recursivo."""
    flat = [r for lst in lists for r in lst]
    # Bots do Navi com arte propria do lado 1 (alt) num no que o jogo troca (gMirroredPartNodeNavi): no lado 1 viram
    # espelho de verdade (sprite_engine.c navi_true_mirror): sem troca de no, sem troca de imagem, braco com a arte do
    # lado 0. Conferido no mGBA (Solid Cottage, 2026-11-23: 100% dos pixels no quadro parado).
    mir_t = rig.mirror_navi if rig.navi else rig.mirror
    true_mirror = bool(side) and rig.navi and any(((r.navi and r.alt) or r.custom) and mir_t[r.node] != r.node
                                                  for r in flat)
    arm_nodes = {r.node for i in (1, 2) for r in lists[i]} if true_mirror else set()
    # camadas de peca: raiz = 1o no da lista (0 = sem a peca); no lado 1 a junta horizontal espelha (-x - 2)
    layer_of = {"gHeadPartLayer": 0, "gRightArmPartLayer": 1, "gLeftArmPartLayer": 2, "gLegPartLayer": 3}

    def tables(navi):
        t = dict(rig.navi_descs if navi else rig.core)
        for n, name in rig.core.get("_layers", {}).items():
            d = t[n].copy()
            lst = lists[layer_of[name]]
            d.child = lst[0].node if lst else 0
            if side:
                d.jh = s8(-d.jh - 2)
            t[n] = d
        return t

    core_t = tables(False)
    navi_t = tables(True) if rig.navi else core_t

    def entry(node):
        for r in flat:
            if r.node == (node & 0xFF):
                return r
        return None

    palettes = {}
    tiles = {}
    for lst in lists:      # load_sprite_tree_recursive: paleta da 1a entrada, imagens por no
        for i, r in enumerate(lst):
            d = rig.customs[r.custom] if r.custom in rig.customs else (navi_t if r.navi else core_t)[r.node]
            fr = (r.frame + (0 if r.node in arm_nodes else side & r.alt)) * 2
            ptrs = d.frames - GBA
            gfx = rig.u32(ptrs + 4 * fr)
            if i == 0:
                pp = rig.u32(ptrs + 4 * (fr + 1))
                if pp:
                    palettes[d.pal] = [struct.unpack_from("<H", rig.rom, pp - GBA + 2 * k)[0] for k in range(16)]
            if gfx:
                tiles[r.node] = gfx_bytes(rig.rom, gfx - GBA)
    if side and getattr(lists, "swap", None) and not true_mirror:
        # lado 1 (setup_medabot_part_sprites, slot != 0): cada no do braco direito recebe a imagem do no k da lista
        # do braco ESQUERDO da mesma peca, e vice-versa (load_sprite_tiles_by_table). Nao troca: entrada sem alt da
        # lista de destino e obrigatoria; pula se a fonte e do Navi com alt ou os moldes do jogo tem tamanhos diferentes.
        for dst_list, src_list in ((lists[1], lists.swap[0]), (lists[2], lists.swap[1])):
            for k, dref in enumerate(dst_list):
                if dref.alt or k >= len(src_list):
                    continue
                s = src_list[k]
                if s.navi and s.alt:
                    continue
                a, b = rig.core.get(s.node), rig.core.get(dref.node)
                if a is None or b is None or (a.h, a.w) != (b.h, b.w):
                    continue
                d = (navi_t if s.navi else core_t)[s.node]
                gfx = rig.u32(d.frames - GBA + 4 * (s.frame * 2))
                if gfx:
                    tiles[dref.node] = gfx_bytes(rig.rom, gfx - GBA)

    lift = 0
    if rig.navi:
        for r in flat:
            if r.navi and r.lift:
                lift = r.lift
                break
    out = []

    def rec(node, a, b, dep, angle, flip, table):
        drawn = node
        if rig.navi:
            if node == 1:
                a -= lift << 8
            mn = rig.mirror_navi[node]
            if flip and entry(mn) is not None:
                drawn = mn
            e = entry(drawn)
            table = navi_t if (e is not None and e.navi) else core_t
        oa, ob = a, b
        mirror = (rig.mirror_navi if rig.navi else rig.mirror)[node] if flip else node
        if flip and true_mirror:          # espelho de verdade: cada no no proprio lugar
            mirror = drawn = node
            e = entry(node)
            table = navi_t if (e is not None and e.navi) else core_t
        desc = table[mirror] if flip else table[node]
        st = mirror if flip else node
        ce = entry(st)
        if ce is not None and ce.custom in rig.customs:   # molde proprio: registro so deste bot, arvore do no
            desc = rig.customs[ce.custom]
        rot, ov, oh = pose.rot[st], pose.ov[st], pose.oh[st]
        z = max(0, dep + desc.depth)
        dv = desc.jv + (ov >> 8)
        dh = desc.jh + (oh >> 8)
        src_rot = (-angle) & 0xFFFF
        pa, pb, pc, pd = affine_set(src_rot)
        if flip:
            src_rot = (-src_rot) & 0xFFFF
        a += pb * dh + pd * dv
        if flip:
            b -= pa * dh + pc * dv
        else:
            b += pa * dh + pc * dv
        e = entry(node)
        vis = 0 if no_affine else (e.affine if e is not None else 1)
        if e is not None:
            mat = None
            if vis:
                src_rot = (src_rot + rot) & 0xFFFF if flip else (src_rot - rot) & 0xFFFF
                pa, pb, pc, pd = affine_set(src_rot)
                if flip:
                    pa, pb = -pa, -pb
                mat = (pa, pb, pc, pd)
                hh, hw = desc.h >> 1, desc.w >> 1
                dv2, dh2 = desc.pv - hh, desc.ph - hw
                ya = a - (pb * dh2 + pd * dv2 + (hh << 8))
                xb = b - (pa * dh2 + pc * dv2 + (hw << 8))
            else:
                ya = a - (desc.pv << 8)
                xb = b - (((desc.w - desc.ph) if flip else desc.ph) << 8)
            sp = Sprite()
            sp.node, sp.z, sp.mat = node, z, mat
            sp.y, sp.x = (ya >> 8) & 0xFF, (xb >> 8) & 0x1FF
            sp.jy, sp.jx = a >> 8, b >> 8          # ponto da tela onde o no se prende (o pivo fica nele)
            h = desc.h // desc.hdiv if desc.hdiv > 1 else desc.h
            w = desc.w // desc.wdiv if desc.wdiv > 1 else desc.w
            sp.h, sp.w, sp.bpp = h, w, desc.bpp
            sp.affine = bool(vis) and desc.affine_mode != 0 or bool(vis)
            sp.double = vis and desc.affine_mode == 3
            sp.hflip = (desc.hflip or (not vis and flip))
            sp.vflip = desc.vflip
            sp.pal = desc.pal
            sp.pixels = tiles.get(node)
            k = len(out)
            while k > 0 and out[k - 1].z > z:
                k -= 1
            out.insert(k, sp)
        if table[node].child:
            rec(table[node].child, a, b, z, 0 if not vis else s16(rot + angle), flip, table)
        if table[node].sibling:
            rec(table[node].sibling, oa, ob, dep, angle, flip, table)

    rec(1, sy << 8, sx << 8, depth, 0, side, core_t)
    return out, palettes


def s8(v):
    return ((v + 0x80) & 0xFF) - 0x80


def gfx_bytes(rom, o):
    hdr = struct.unpack_from("<I", rom, o)[0]
    if (hdr >> 4) & 0xF == 1:
        return lz77_decompress(rom, o)[0]
    size = hdr >> 8
    return rom[o:o + size]


def bgr555(c):
    return ((c & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, ((c >> 10) & 31) * 255 // 31, 255)


def texel(sp, tx, ty):
    if sp.pixels is None:
        return 0
    tw = sp.w // 8
    t = (ty // 8) * tw + tx // 8
    if sp.bpp:
        o = t * 64 + (ty % 8) * 8 + tx % 8
        return sp.pixels[o] if o < len(sp.pixels) else 0
    o = t * 32 + (ty % 8) * 4 + (tx % 8) // 2
    if o >= len(sp.pixels):
        return 0
    v = sp.pixels[o]
    return (v >> 4) if tx & 1 else (v & 15)


def rasterize(sprites, palettes, size=(240, 160), bg=(48, 48, 64, 255)):
    from PIL import Image
    img = Image.new("RGBA", size, bg)
    px = img.load()
    W, H = size
    for sp in reversed(sprites):          # o primeiro da OAM fica por cima
        pal = palettes.get(sp.pal, [0x7FFF] * 16)
        x0 = sp.x - 512 if sp.x >= 240 + 64 else sp.x
        y0 = sp.y - 256 if sp.y >= 160 + 32 else sp.y
        if sp.mat is not None:
            bw, bh = (sp.w * 2, sp.h * 2) if sp.double else (sp.w, sp.h)
            cx, cy = bw / 2, bh / 2
            pa, pb, pc, pd = sp.mat
            for yy in range(bh):
                for xx in range(bw):
                    X, Y = x0 + xx, y0 + yy
                    if not (0 <= X < W and 0 <= Y < H):
                        continue
                    rx, ry = xx - int(cx), yy - int(cy)
                    tx = ((pa * rx + pb * ry) >> 8) + sp.w // 2
                    ty = ((pc * rx + pd * ry) >> 8) + sp.h // 2
                    if 0 <= tx < sp.w and 0 <= ty < sp.h:
                        c = texel(sp, tx, ty)
                        if c:
                            px[X, Y] = bgr555(pal[c] if c < 16 else 0x7FFF)
        else:
            for yy in range(sp.h):
                for xx in range(sp.w):
                    X, Y = x0 + xx, y0 + yy
                    if not (0 <= X < W and 0 <= Y < H):
                        continue
                    tx = sp.w - 1 - xx if sp.hflip else xx
                    ty = sp.h - 1 - yy if sp.vflip else yy
                    c = texel(sp, tx, ty)
                    if c:
                        px[X, Y] = bgr555(pal[c] if c < 16 else 0x7FFF)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--bot", type=int, default=120)
    ap.add_argument("--script", type=int, help="roteiro de pose (0..58) direto")
    ap.add_argument("--side", type=int, default=0)
    ap.add_argument("--x", type=int, default=120)
    ap.add_argument("--y", type=int, default=110)
    ap.add_argument("--png", default="anim.png")
    ap.add_argument("--frames", action="store_true")
    ap.add_argument("--dump", action="store_true", help="lista as entradas de OAM")
    a = ap.parse_args()
    rig = Rig(a.rom, a.map)
    lists = rig.part_lists(a.bot)
    pose = Pose()
    states = []
    if a.script is not None:
        for _ in pose.frames(rig, a.script):
            states.append(Pose.__new__(Pose))
            states[-1].rot, states[-1].ov, states[-1].oh = list(pose.rot), list(pose.ov), list(pose.oh)
    if not states:
        states = [pose]
    shots = states if a.frames else [states[-1]]
    for i, st in enumerate(shots):
        sprites, pals = render_tree(rig, lists, st, a.x, a.y, side=a.side)
        if a.dump and i == len(shots) - 1:
            for sp in sprites:
                print(f"node {sp.node:2d} y {sp.y:3d} x {sp.x:3d} {sp.w}x{sp.h} z {sp.z} "
                      f"{'aff' if sp.mat else '   '} {sp.mat or ''}")
        img = rasterize(sprites, pals)
        out = a.png if not a.frames else a.png.replace(".png", f"_{i:03d}.png")
        img.save(out)
    print(f"{len(shots)} imagem(ns); {len(sprites)} sprites")


if __name__ == "__main__":
    main()
