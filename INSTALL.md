# Installing

You build the game from the decompilation, with your own ROMs. Setup runs once; after that each build takes a few minutes.

## 1. What you need

- **Python 3.10 or newer**, with `pip install -r requirements.txt` (numpy, Pillow).
- **git**.
- **A C toolchain and `make`**, to build the agbcc compiler and the game:
  - **Linux or WSL (recommended):** `sudo apt install build-essential git python3 binutils-arm-none-eabi gcc-arm-none-eabi`
  - **macOS:** Xcode command line tools, plus the ARM binutils (for example from devkitARM).
  - **Windows without WSL:** [w64devkit](https://github.com/skeeto/w64devkit) (unzip it anywhere) and the ARM GNU toolchain (`arm-none-eabi-*`). Pass both to setup (step 3).
- **Your ROMs** in the `roms/` folder of this repository. See the levels and SHA-1 values in [README.md](README.md). `python tools/roms.py` tells you which ones it found and which level you can build.

## 2. Get this repository

```sh
git clone https://github.com/jvsdm/medabots-expansion.git
cd medabots-expansion
mkdir roms        # copy your .gba files here
```

## 3. Setup (once)

Linux, WSL or macOS:

```sh
python3 tools/setup.py
```

Windows with w64devkit:

```sh
python tools/setup.py --w64devkit C:/w64devkit/bin --arm-prefix C:/arm-gnu/bin/arm-none-eabi-
```

Setup:

1. checks Python and your ROMs;
2. downloads into `deps/`: the decompilation ([jvsdm/medabots-rokusho](https://github.com/jvsdm/medabots-rokusho), branches `main` and `expansion`), [agbcc](https://github.com/pret/agbcc) and the WPF editor sources (only its layout signatures are used);
3. builds agbcc and copies your US ROM as `baserom.gba` into both decompilation trees;
4. builds the original game once (`make compare`): this checks your ROM and your toolchain;
5. extracts the game's maps, event scripts and animations from your ROM into `data/`, then applies the project's changes from `overlay/`;
6. writes `medabots.config.json` with the paths it used.

You can run it again: it only redoes what is missing.

## 4. Build

```sh
python tools/decomp_build.py --level core      # 2 ROMs
python tools/decomp_build.py --level shingata  # 3 ROMs
python tools/decomp_build.py --level navi      # 4 ROMs (same content as the IPS patch)
```

The ROM is `build/scratch/decomp_hpNN/medabots_rokusho.gba` (NN goes up with each build; the two newest are kept). If the folder of a previous build has a save file, it is copied to the new one.

To make an IPS patch of your build: `python tools/make_ips.py criar roms/<your US ROM>.gba build/scratch/decomp_hpNN/medabots_rokusho.gba my.ips`.

## 5. Decomp mode in the WPF editor

In the [WPF editor](https://github.com/jvsdm/Medabots-Romhacking-Toolkit/releases), use **File > Open Decomp Project...** and pick this repository's folder. **Build ROM** runs `tools/decomp_build.py` and opens the new ROM.

## Problems

- `falta a ROM ...`: a ROM of the level is missing or is a different dump; compare its SHA-1 with the README.
- `w64devkit nao encontrado` (Windows): pass `--w64devkit` to setup, or set `MEDABOTS_W64DEVKIT`.
- `make compare` fails in step 4: the ROM is not the expected one, or the ARM binutils are missing.

Some messages from the tools are in Portuguese; they name the file or ROM involved.
