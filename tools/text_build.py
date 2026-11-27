"""text_build.py - Falas novas do projeto (M4 do pc/research/MAPAS_EVENTOS_PLANO.md).

O jogo tem 16 bancos de fala em gTextBankTables (o roteiro diz `Show_Message_A bank=N, id=M`: banco N = indice da
tabela; o byte no roteiro e N + 2). Os bancos do projeto ficam em data/story/text/bank_NN.json (NN = 16, 17...) e
entram como bancos novos: a build monta uma gTextBankTables nova (os 16 do jogo + os do projeto) em asm/text_project.s.
O lugar antigo fica como sOrig_gTextBankTables, porque ponteiros do jogo para o texto logo depois da tabela usam
esse rotulo + deslocamento. Os textos do jogo nao mudam.

bank_NN.json: {"bank": NN, "messages": ["texto", ...]}; o id da fala e a posicao na lista.
Texto: caracteres da fonte do jogo (tools/medarom.py ENCODING) e os codigos
    |  nova linha (FD)          ||  nova caixa, espera o botao (FC)
    <FB 00 44 00>  bytes crus em hex (ex.: cabecalho de quem fala, como nas falas do jogo)
O fim (FF 00: fim da fala, espera o botao) entra sozinho.

Uso: python tools/text_build.py --check            confere os textos (caracteres e codigos)
     python tools/text_build.py --show 16 0        mostra os bytes de uma fala
"""
import argparse
import json
import re
from pathlib import Path

from medarom import ENCODING

ROOT = Path(__file__).resolve().parents[1]
TEXT = ROOT / "data/story/text"
NL, TAB = chr(10), chr(9)
GAME_BANKS = 16
TABLE_AT = 0x47E45C                  # gTextBankTables (USA)
_ENC = {c: i for i, c in enumerate(ENCODING)}


def encode(s, where=""):
    out = bytearray()
    for tok in re.split(r"(<[0-9A-Fa-f ]+>|\|\||\|)", s):
        if not tok:
            continue
        if tok == "||":
            out.append(0xFC)
        elif tok == "|":
            out.append(0xFD)
        elif tok.startswith("<"):
            out += bytes.fromhex(tok[1:-1])
        else:
            for c in tok:
                if c not in _ENC:
                    raise SystemExit(f"{where}: caractere sem glifo na fonte do jogo: {c!r} em {s!r}")
                out.append(_ENC[c])
    return bytes(out) + b"\xFF\x00"        # FF modo: fim da fala; modo 0 = espera A/B (src/text/message.c)


def load_banks(text=TEXT):
    banks = []
    for f in sorted(text.glob("bank_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        banks.append((d["bank"], [encode(m, f"{f.name}[{i}]") for i, m in enumerate(d["messages"])]))
    banks.sort()
    want = list(range(GAME_BANKS, GAME_BANKS + len(banks)))
    if [b for b, _ in banks] != want:
        raise SystemExit(f"bancos do projeto precisam ser {want} (sem buraco), veio {[b for b, _ in banks]}")
    if banks and banks[-1][0] + 2 > 0xFF:
        raise SystemExit("banco passa de 253")
    return banks


def install(tree, text=TEXT):
    """asm/text_project.s com a gTextBankTables nova; sem banco do projeto, nada muda na arvore."""
    banks = load_banks(text) if text.exists() else []
    out = tree / "asm/text_project.s"
    if not banks:
        if out.exists():
            out.unlink()
        return 0
    # entradas do jogo: os simbolos do .tsv do bloco (gTextTable+deslocamento)
    tsv = next(t for t in (tree / "config/data_ptrs").glob("*.tsv") if f"{TABLE_AT + 0x08000000:08X}{TAB}" in
               t.read_text(encoding="utf-8"))
    ptr = {int(l.split(TAB)[0], 16) - 0x08000000: l.split(TAB)[1] for l in tsv.read_text(encoding="utf-8").split(NL)
           if l and not l.startswith("#")}
    game = [ptr[TABLE_AT + 4 * i] for i in range(GAME_BANKS)]
    # rotulo antigo -> sOrig_ (no bloco e nos ponteiros rotulo+deslocamento)
    stub = next(s for s in (tree / "data").glob("*.s") if "gTextBankTables:" in s.read_text(encoding="utf-8")
                or "sOrig_gTextBankTables:" in s.read_text(encoding="utf-8"))
    s = stub.read_text(encoding="utf-8")
    if f"{NL}gTextBankTables:" in s:
        stub.write_text(s.replace(f"{TAB}.global gTextBankTables{NL}gTextBankTables:",
                                  f"{TAB}.global sOrig_gTextBankTables{NL}sOrig_gTextBankTables:"), encoding="utf-8")
        for t in (tree / "config/data_ptrs").glob("*.tsv"):
            x = t.read_text(encoding="utf-8")
            if f"{TAB}gTextBankTables+" in x:
                t.write_text(x.replace(f"{TAB}gTextBankTables+", f"{TAB}sOrig_gTextBankTables+"), encoding="utf-8")
    a = [f"{TAB}.section .rodata", "", "@ gerado por tools/text_build.py a partir de data/story/text (nao editar)",
         f"{TAB}.align 2", f"{TAB}.global gTextBankTables", "gTextBankTables:"]
    a += [f"{TAB}.4byte {g}" for g in game] + [f"{TAB}.4byte sProjectTextBank{b}" for b, _ in banks]
    for b, msgs in banks:
        # termina com 0, como as tabelas do jogo (o leitor de falas do WPF para no ponteiro zero)
        a += [f"sProjectTextBank{b}:"] + [f"{TAB}.4byte sProjectText{b}_{i}" for i in range(len(msgs))] + [f"{TAB}.4byte 0"]
        for i, m in enumerate(msgs):
            a += [f"sProjectText{b}_{i}:", f"{TAB}.byte " + ", ".join(str(v) for v in m)]
        a.append(f"{TAB}.align 2")
    out.write_text(NL.join(a) + NL, encoding="utf-8")
    ld = tree / "ld_script.ld"
    t = ld.read_text(encoding="utf-8")
    obj = "build/asm/text_project.o(.rodata);"
    if obj not in t:
        anchor = "build/asm/maps_area_tables.o(.rodata);"
        assert anchor in t, "ld_script sem maps_area_tables (rode tools/maps_build.py --asm antes)"
        ld.write_text(t.replace(anchor, f"{anchor}{NL}        {obj}", 1), encoding="utf-8")
    return sum(len(m) for _, ms in banks for m in ms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=str(TEXT))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--show", nargs=2, type=int)
    a = ap.parse_args()
    banks = dict(load_banks(Path(a.text)))
    if a.check:
        print(f"{len(banks)} bancos do projeto: " + ", ".join(f"{b} ({len(m)} falas)" for b, m in banks.items()))
    if a.show:
        print(banks[a.show[0]][a.show[1]].hex(" "))


if __name__ == "__main__":
    main()
