"""
patches.py - Sitios de codigo que dependem da quantidade de bots (Metabee EU).

Origem de cada lista:
  - "shingata": data/limits.md (mesmo sitio vira 0x3B/0x3C no Shingata, que tem 60 bots)
  - "manual":   classificados lendo o contexto (data/nomatch_ctx.txt), ver comentarios

Regra do motor (igual ao Shingata): com N bots,
  ultimo ID real = N-1, contagem = N, Tinpet macho = N, Tinpet femea = N+1.
Na expansao o Tinpet fica FIXO em TINPET_ID / TINPET_ID+1 (nao anda com N), para saves
sobreviverem a bots novos. IDs N..TINPET_ID-1 ficam vazios (linhas de tabela de enchimento;
inventario zerado, entao o ciclo de pecas os pula).
"""

# 236: ate 236 bots (0-235) = 59 paginas cheias de 4 pecas; Tinpet 236/237 continua dentro das 240
# vagas do inventario por tipo, caso algum codigo use o ID do Tinpet como indice (nenhum visto).
TINPET_ID = 236

# cmp/mov #0x77 -> N-1  ("e peca real?" / limite de laco / volta do cursor)
BOT_MAX_SITES = [
    # shingata
    0x0050AE, 0x005A70, 0x005A82, 0x005A94, 0x005AA8, 0x00703E, 0x007066, 0x00708C,
    0x0070B4, 0x00C614, 0x00C650, 0x00C6BE, 0x00FCDA, 0x00FE7E, 0x039B7C, 0x05B0EE,
    0x05B156, 0x061924, 0x06242A, 0x0626F2,
    # manual: nome/equipamento das 4 pecas (struct +0x98..+0x9B)
    0x005CB0, 0x005D28, 0x005E14, 0x005E90, 0x005F7C, 0x005FF8, 0x0060E4, 0x006160,
    0x0063C0, 0x006F96, 0x006FA4,
    # manual: clamp em funcao que monta Tinpet
    0x006E2E, 0x006E32,
    # manual: perna (struct 0x30017A0 +6) em listas
    0x009DD4, 0x00AF82,
    # manual: cursor que da a volta 0 <-> 119
    0x00C4EC, 0x00C524, 0x00FE04,
    # manual: paleta 10 p/ peca real, 9 p/ Tinpet
    0x016000, 0x0160F0,
    # manual: validador de Medabot (medalha < 30 e 4 pecas <= 119)
    0x043830, 0x043834, 0x043838, 0x04383C,
    # manual: laco 0..119 em funcao de inventario
    0x062682,
]

# cmp #0x78 -> TINPET_ID ("e o Tinpet macho?" no ciclo de pecas 0x436AC; no Shingata vira 0x3C
# porque la contagem e Tinpet coincidem)
TINPET_CHECK_SITES = [
    0x0436D0,   # shingata: voltando do Tinpet femea, pula o macho
    0x04374E,   # manual: avancando, macho -> femea
]

# adds rX, #0x78 -> TINPET_ID   (genero + 0x78 = Tinpet)
TINPET_SITES = [
    # shingata
    0x0421E0, 0x043766, 0x0437D6,
    # manual
    0x006E20,                                   # equipamento -> Tinpet
    0x015862, 0x015884, 0x0158A4, 0x0158C4,     # batalha: peca destruida -> Tinpet
    0x042246,                                   # cria Medabot pelado (4 pecas Tinpet)
]

# adds rX, #0x78 -> N   (loja: 0x2023000 + N = variavel de rolagem, depois das N quantidades;
# escala com N junto com SHOP_SCROLL_LITERALS). Nao e Tinpet, apesar do mesmo imediato.
SHOP_SCROLL_ADDS = [0x061D6C, 0x062008, 0x06211E, 0x0621EA, 0x062312]

# #0x79 -> TINPET_ID+1 (Tinpet femea)
TINPET_F_SITES = [
    0x043752,   # movs r0, #0x79
    0x043758,   # adds r0, #0x79
]

# #0x1D (ultima pagina, 30 paginas de 4 pecas) -> ceil(N/4)-1
# Cuidado: 0x1D tambem e "ultima medalha" (30 medalhas) em varios lugares; so estes sao paginas.
PAGE_LAST_SITES = [
    0x00F0A8,   # menu Medaparts (pagina em +0x3F): volta 0 -> ultima
    0x00F0CA,   # menu Medaparts: ultima -> 0
    0x00C0BC,   # lista 0x3000440+0x35[modo 0]: ultima -> 0
    0x00CFE0,   # idem
    0x00D030,   # idem: volta 0 -> ultima
]
# "/30" da lista de pecas: tilemap Malias em 0x4F1514 (BG1, 32 colunas, tile guardado = VRAM - 0x200).
# Os 7 bytes abaixo sao literais no stream comprimido e nao sao reaproveitados por outras entradas
# (0x4F1563 alimenta tambem o byte alto do "0" de baixo, que precisa do mesmo valor). O build troca
# o "30" desenhado pela fonte de digitos do numero da pagina (VRAM 0x360 + 2*d em cima, +1 embaixo,
# paleta 7), com o total ceil(N/4).
PAGE_TOTAL_MAP = 0x4F1514
PAGE_TOTAL_BYTES = {   # endereco: (valor original, papel)
    0x4F1560: (0x20, "dezena, cima, tile"),
    0x4F1561: (0x70, "dezena, cima, paleta/bits altos"),
    0x4F1562: (0x21, "unidade, cima, tile"),
    0x4F1563: (0x70, "unidade, cima e baixo, paleta/bits altos"),
    0x4F1580: (0x2B, "dezena, baixo, tile"),
    0x4F1581: (0x70, "dezena, baixo, paleta/bits altos"),
    0x4F1583: (0x2C, "unidade, baixo, tile"),
}

# Seletor de imagem das pecas (preview/batalha) com 8 bits em vez de 7. Na funcao 0x45E6C:
#   r2 = (entrada >> 6) + variante ; r2 = (r2 & 0x7F) << 1   (lsls #25 ; lsrs #24)
# vira (r2 & 0xFF) << 1 (lsls #24 ; lsrs #23): 256 vagas por molde. Seguro p/ os bots originais
# (nenhum usa o bit 13). Achado com watchpoint no mGBA (posicao 0x2026491 ativada pelo molde 60).
SELECTOR_8BIT_PATCH = [
    (0x045ECC, 0x0652, 0x0612),   # lsls r2, r2, #25 -> #24
    (0x045ECE, 0x0E12, 0x0DD2),   # lsrs r2, r2, #24 -> #23
]
# Obs.: o estado de cada peca em batalha fica num vetor indexado pelo NUMERO DO MOLDE, com 50
# posicoes (EWRAM 0x20260D0, 16 B cada); logo depois vem o vetor do inimigo. Por isso moldes
# clonados em IDs >= 50 invadem o inimigo (pecas voando). Nao usar clones.

# Lacos 0..N-1 com contador de 1 byte COM SINAL (`lsls #24 ; asrs #24 ; cmp #N-1 ; ble`).
# Com N > 128 o contador passa de 127 para -128 e o laco nunca termina (trava ao comprar na loja).
# asrs -> lsrs (contador sem sinal). (endereco, halfword original, novo)
UNSIGNED_LOOP_PATCHES = [
    (0x062428, 0x1600, 0x0E00),   # asrs r0, r0, #24 -> lsrs
    (0x062680, 0x161B, 0x0E1B),   # asrs r3, r3, #24 -> lsrs
    (0x0626F0, 0x161B, 0x0E1B),   # asrs r3, r3, #24 -> lsrs
    # Dentro dos mesmos lacos o indice e reconvertido com sinal antes de indexar os vetores da
    # loja (0x2023000 + i e 0x2040000 + i*8): item 128+ viraria indice negativo.
    (0x0623D8, 0x1610, 0x0E10),   # asrs r0, r2, #24 -> lsrs
    (0x06240A, 0x1610, 0x0E10),   # asrs r0, r2, #24 -> lsrs
    (0x062656, 0x161B, 0x0E1B),   # asrs r3, r3, #24 -> lsrs
    (0x0626C6, 0x161B, 0x0E1B),   # asrs r3, r3, #24 -> lsrs
]
# Os vetores da loja eram dimensionados p/ 120 itens: 0x2040000 (espelho de 0x02000000) usa
# 120 x 8 = 0x3C0 B; com N itens cresce sobre 0x020003C0-0x020007FF, area livre no scan de RAM
# (cabe ate 255 itens). 0x2023000 + i cresce sobre 0x2023040+, tambem livre.

# Loja: vetor de quantidades 0x2023000 + i (i < N) seguido da variavel de rolagem em base + 120
# (0x2023078). Com N itens a rolagem vai p/ base + N; estes literais guardam o endereco dela.
# (0x061954, 0x0620F4 e 0x0623F4 estavam antes em TINPET_SITES: os bytes `78 30` do literal
#  parecem `adds r0, #0x78`.)
SHOP_SCROLL_LITERALS = [0x05B3E8, 0x05B9C0, 0x05BA14, 0x061954, 0x061E84, 0x0620BC, 0x0620F4,
                        0x0623F4, 0x062804]
SHOP_SCROLL_BASE = 0x02023000
# Lista de venda (0x5B0D8): limpa os itens de tras p/ frente a partir do ultimo (base + 119*8).
SHOP_ITEMS_LAST_LITERAL = 0x05B178       # 0x020403B8 -> 0x02040000 + (N-1)*8
SHOP_ITEMS_BASE = 0x02040000

# Classificados como NAO relacionados (nao mexer): coordenadas, offsets de struct, dados,
# 0x04C996 (efeito sonoro 0x78), 0x0505D8, 0x067080, 0x011B4E, 0x0142DE, serie 0x1CAE0...

# ---------------- inventario ----------------
INV_OLD = 0x03004C40
INV_NEW = 0x0202E000          # EWRAM livre (scan de 88k frames + sem refs no codigo)
INV_STRIDE_SITES = [          # `lsls rd, rm, #4` (tipo*15<<4) -> #5
    0x00EC7A, 0x00ED36, 0x00EDC6, 0x00EE5A, 0x042120, 0x04214C, 0x042182, 0x0421C8,
    0x043572, 0x04358E, 0x0436F4, 0x04370A, 0x04371C, 0x04378A, 0x0437A0, 0x0437B2,
    0x05B102, 0x061BC6, 0x062668, 0x0626D8,
]
# (endereco, halfword original, halfword novo)
INV_HALFWORD_PATCHES = [
    (0x04A312, 0x0089, 0x00C9),   # clear new game: lsls r1,r1,#2 (0x3C0) -> #3 (0x780)
    (0x05D8A6, 0x0052, 0x0092),   # contador: lsls r2,r2,#1 (480) -> #2 (960)
    (0x05DF58, 0x8810, 0x7810),   # load: ldrh r0,[r2] -> ldrb
    (0x05DF5C, 0x3202, 0x3201),   # load: adds r2,#2 -> #1
    (0x05E066, 0x8008, 0x7008),   # save: strh r0,[r1] -> strb
    (0x05E068, 0x3102, 0x3101),   # save: adds r1,#2 -> #1
]
# (endereco do literal, valor original, valor novo)
INV_LITERAL_PATCHES = [
    (0x0440E8, 0x1DF, 0x3BF),     # contador de entradas (480 -> 960)
    (0x05DFD8, 0x3BF, 0x77F),     # load: 960 -> 1920 bytes
    (0x05E0F8, 0x3BF, 0x77F),     # save: 960 -> 1920 bytes
]
# Fonte italica (texto entre codigos F8, ex.: "Click!"): 128 glifos 8x16 4bpp em 0x4C59AC (cabecalho em
# 0x4C59A4, lido pelo codigo de texto 0x40144-0x40504). Na ROM EU original os tons escuros B-F viraram 0
# (transparente) e o 8 virou 5: o texto some no fundo. Reconstrucao: cada pixel 0 recebe um tom pela
# quantidade de vizinhos (4-conexos) com tinta: 4 -> F, 3 -> E, menos -> D (erro medio ~1 tom contra uma
# fonte de referencia). So aplica se a fonte tiver o defeito (pixels 0 e nenhum tom B-F).
ITALIC_FONT = 0x4C59AC
ITALIC_FONT_SIZE = 128 * 64
STARTER_FUNC = 0x044B58           # equipa e da as 4 pecas do bot inicial
STARTER_ID_AT = 0x044B6C          # movs r0, #<bot inicial>
