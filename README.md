# Linaia-Agon — Real-Time Musical Tactic Classification System

[![DOI](https://doi.org/10.5281/zenodo.20921295)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> Automated referee system for Iannis Xenakis's *Linaia-Agon* (1972).  
> Classifies musical tactics in real time via FFT and normalised Euclidean distance,  
> calculates payoffs, and displays results through a live interface.

---

## What is this?

*Linaia-Agon* (Xenakis, 1972) is a musical game for three soloists — horn, trombone and tuba — structured as a zero-sum game with three battles (α, β, γ), each containing four tactics. In the original score, two human referees are required: one to identify the tactic being played and one to calculate the payoffs.

This software automates both roles. It was developed as part of doctoral research at **Universidade de São Paulo (USP)** and the **Université Paris 8 Vincennes – Saint-Denis**, within a course on Xenakis led by Prof. Dr. Makis Solomos.

The instrumentation used in this version differs from the original: **Linos = horn in F** and **Apollon = cello + horn in F**.

---

## System Architecture

```
┌─────────────┐   mic L    ┌──────────────────┐   OSC :57120   ┌──────────────┐
│    Linos    │───────────▶│                  │───────────────▶│              │
│  (horn)     │            │  Python          │                │ SuperCollider│
└─────────────┘   mic R    │  (Classifier +   │◀───────────────│ (Game Engine)│
┌─────────────┐───────────▶│   HTTP server)   │   OSC :57200   │              │
│   Apollon   │            │                  │                └──────────────┘
│ (cello+horn)│            └──────────────────┘
└─────────────┘                    │ HTTP :8765
                                   ▼
                            ┌─────────────┐
                            │    HTML     │
                            │ (Interface) │
                            └─────────────┘
```

**SuperCollider** — game engine, payoff calculation, OSC communication  
**Python** — stereo audio capture, FFT feature extraction, Euclidean distance classifier, HTTP server  
**HTML/CSS/JS** — live visual interface (polling at 500 ms), score display, battle transitions  

---

## Classification Pipeline

For each 6-second audio window per channel:

1. **FFT** → extract 5 normalised spectral features  
   - `freq_dom` — dominant frequency (weight 1.0)  
   - `centroid` — spectral centroid (weight 0.8)  
   - `spread` — spectral spread (weight 0.6)  
   - `integral` — normalised area under FFT curve (weight 0.5)  
   - `energy` — normalised spectral energy (weight 0.3)  

2. **Euclidean distance** to reference vectors (one per tactic per scenario)

3. **Temporal voting** — mode of last 5 windows, silence votes discarded if < 60 %

Overall accuracy on reference recordings: **87 %** (78/90 tests across 5 playback speeds).

---

## Requirements

### Python
```
Python >= 3.10
pyaudio
librosa
numpy
scipy
python-osc
```

Install:
```bash
pip install pyaudio librosa numpy scipy python-osc
```

### SuperCollider
- SuperCollider >= 3.12  
- No additional Quarks required

### Audio interface
- Stereo input device (L = Linos, R = Apollon)  
- Two directional microphones recommended  
- Set `DEVICE_INDEX` in `linaia-server4.py` to your interface index

---

## How to Run

**Step 1 — Start the Python server (keep this terminal open):**
```bash
python3 linaia-server4.py
```
The terminal will list available audio input devices. Note the index of your interface and set `DEVICE_INDEX` accordingly if needed.

**Step 2 — Load SuperCollider:**  
Open `linaia-agon3.scd` in SuperCollider IDE.  
Select all (`Ctrl+A` / `Cmd+A`) and evaluate (`Shift+Enter`).

**Step 3 — Open the interface:**  
Navigate to `http://localhost:8765/` in a browser.  
The connection dot turns green when Python is reachable.

**Step 4 — Play:**  
Use `~runRound.(\alpha, 12)` in SuperCollider to start a 12-second round of battle α.  
Advance battles with `~proximaBatalha.()`.

---

## File Structure

```
linaia-agon/
├── linaia-server4.py      # Python: classifier + OSC + HTTP server
├── linaia-agon3.scd       # SuperCollider: game engine + payoff matrices
├── Inteface3.html         # HTML/JS: live interface
├── README.md
├── LICENSE
└── CITATION.cff
```

---

## OSC Protocol

| Message | Direction | Description |
|---|---|---|
| `/linaia/start` | SC → Python | Activate audio capture |
| `/linaia/stop` | SC → Python | Pause audio capture |
| `/linaia/scenario <string>` | SC → Python | Set current scenario (e.g. `alpha_Linos`) |
| `/linaia/tactic/linos <scenario> <tactic> <conf>` | Python → SC | Linos classification result |
| `/linaia/tactic/apollo <scenario> <tactic> <conf>` | Python → SC | Apollon classification result |
| `/linaia/score <linos> <apollo>` | SC → Python | Update score display |
| `/linaia/segment <n>` | SC → Python | Current segment number |

---

## Payoff Matrices

**Battle α**
```
         I    II   III   IV
I      [ -2,   0,   0,   0 ]
II     [  1,   0,  -3,  -2 ]
III    [  0,  -1,   1,  -2 ]
IV     [  0,  -1,  -2,   1 ]
```

**Battle β**
```
         V    VI  VII  VIII
V      [  1,  -2,  -2,   3 ]
VI     [  1,  -1,   0,  -2 ]
VII    [  0,   4,  -2,  -2 ]
VIII   [ -2,  -1,   5,   1 ]
```

**Battle γ**
```
        IX    X   XI  XII
IX     [  4,  -4,   2,   3 ]
X      [ -1,   2,  -1,  -3 ]
XI     [ -1,  -1,   0,   4 ]
XII    [ -3,   1,   5,  -2 ]
```

---

## Known Limitations

- Reference vectors were recorded with a specific instrumentation and set of performers — recalibration required for different instruments or players
- β Linos accuracy: 64% (freq_dom oscillates between tactics 1 and 2)
- γ Apollon accuracy: 73% (tactic 3 freq_dom unstable across the performance window)
- Choix de Combat module implemented but not yet formally tested
- Acoustic bleed between channels may affect classification in close-proximity setups

---

## Citation

If you use this software in academic work, please cite:

```bibtex
@software{bonacorsi2026linaia,
  author    = {Bonacorsi Xavier, Thayn\'a A.},
  title     = {Linaia-Agon: Real-time musical tactic classification system},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.20921295},
  url       = {https://github.com/TBonacorsi/linaia-agon}
}
```

---

## Acknowledgements

Developed within the course *Xenakis et la musique stochastique*, taught by Prof. Dr. Makis Solomos (Université Paris 8 Vincennes – Saint-Denis).  
FFT classification approach suggested by Inayê Melo.  
Inspired by the pioneering automation work of Benny Sluchin, Gérard Assayag and Mikhaïl Malt (IRCAM, 2004).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
