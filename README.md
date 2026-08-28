<div align="center">

  <a href="https://www.humn.space/odd.html" target="_blank" rel="noopener noreferrer">
    <img src="assets/odd-logo.png" alt="ODD by Humnspace" width="130" height="130" style="border-radius: 50%; border: 2px solid #333333;" />
  </a>

  # ODD

  ### The Dynamic Island & Minimalist Spotlight Launcher for Windows

  [![Official Release](https://img.shields.io/badge/Official%20Release-humn.space-000000?style=for-the-badge&logo=googlechrome&logoColor=white)](https://www.humn.space/)
  [![Platform](https://img.shields.io/badge/Target-Windows%2010%20%2F%2011-000000?style=for-the-badge&logo=windows&logoColor=white)](https://www.humn.space/odd.html)
  [![Privacy](https://img.shields.io/badge/Privacy-100%25%20Offline%20%2F%20Zero%20Telemetry-000000?style=for-the-badge&logo=target&logoColor=white)](https://www.humn.space/privacy-policy.html)
  [![Design](https://img.shields.io/badge/Design-Monochrome%20Minimalism-000000?style=for-the-badge&logo=visualstudiocode&logoColor=white)](https://www.humn.space/)
  [![Ecosystem](https://img.shields.io/badge/By-Humnspace-000000?style=for-the-badge&logo=vercel&logoColor=white)](https://www.humn.space/)

  <p align="center">
    <b>Your screen's missing brain.</b><br>
    Sub-millisecond file radar, live audio visualizer with spinning vinyl disc, instant math, and screen-edge ambient widgets — unified into an elegant, distraction-free floating island.
  </p>

  <p align="center">
    <a href="https://www.humn.space/odd.html"><strong>Explore ODD on Humnspace &rarr;</strong></a> &nbsp;|&nbsp;
    <a href="https://www.humn.space/"><strong>Official Website</strong></a> &nbsp;|&nbsp;
    <a href="#-command-syntax--cheat-sheet"><strong>Command Syntax</strong></a> &nbsp;|&nbsp;
    <a href="#-feature-matrix"><strong>Features</strong></a>
  </p>

</div>

---

> [!IMPORTANT]
> **OFFICIAL RELEASE & DISTRIBUTION NOTICE**
> 
> **ODD** is designed, developed, and distributed by **[Humnspace Inc.](https://www.humn.space/)**.
> 
> The official releases, early beta access builds, and verified installer packages for Windows are distributed exclusively through the official platform at:
> 
> ### 🌐 [https://www.humn.space/](https://www.humn.space/) &bull; [https://www.humn.space/odd.html](https://www.humn.space/odd.html)
> 
> To guarantee cryptographic integrity, security updates, and authentic builds, always obtain ODD binaries directly from the official **Humnspace** portal.

---

## 🖤 Design Philosophy

Windows desktop bezels have remained static for decades. **ODD** transforms the top screen edge into an intelligent, adaptive focal point inspired by pure monochrome minimalism:

1. **Invisible Until Summoned**: Docks seamlessly to your top screen bezel or summons instantly with <kbd>Alt</kbd> + <kbd>Space</kbd>.
2. **Zero Distraction**: No saturated colors, no advertisements, no web bloat, no news feeds.
3. **Local-First & Offline**: 100% of searches, equations, notes, and automations run on bare metal with **zero telemetry**.
4. **Fluid Motion & Audio Physics**: Responsive audio frequency bars and rotating vinyl media indicators that feel alive.

---

## ⚡ Visual Architecture

```
   ┌──────────────────────────────────────────────────────────┐
   │                  ODD Top Screen Notch                     │
   └──────────────────────────┬───────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          │  [+]  Type anything...  ||||  (●)ODD │   <-- Floating Action Cluster
          └───────────────────┬───────────────────┘
                              │
          ┌───────────────────▼───────────────────┐
          │  FILE   project_deck.pdf       ↵ Open │   <-- Omnibox Search Radar
          │  f: files  |  calc: math  |  rem: ... │
          └───────────────────────────────────────┘
```

---

## ✨ Core Capabilities

### 1. 🔍 Sub-Millisecond File & App Radar
Instantaneous indexed search across applications, documents, PDFs, and local project folders without background CPU drain.
```text
f: invoice_2026.pdf           -> ↵ Opens immediately in default viewer
f: terminal                   -> ↵ Launches Windows Terminal
```

### 2. 🎵 Dynamic Island Vinyl & Live Audio Radar
When media is playing (Spotify, Windows Media, browsers), ODD elegantly morphs into an expanded media island with a spinning monochrome vinyl disc, live track telemetry, and real-time frequency equalizer waves.

### 3. 🧮 Instant Math & Unit Computation
Perform multi-step equations, currency conversions, and unit transformations directly in the pill without switching windows.
```text
calc: (240 * 1.18)            -> = 283.20
convert: 50 USD to EUR        -> ≈ €46.10
convert: 120 km to miles      -> ≈ 74.56 mi
```

### 4. ⏰ Natural Language Quick Reminders
Schedule persistent notifications using natural language phrasing.
```text
rem: submit pull request in 30m
rem: tea break at 4:15pm
```

### 5. 📋 Smart Clipboard Memory & Snippets
Instant access to copied items, persistent scratchpads, and code snippets with single-keystroke insertion.
```text
clip: recent                  -> 1-click clipboard history paste
```

### 6. ⚙️ Tactical System Controls
Direct operating system triggers right from your fingertips.
```text
sys: lock                     -> Immediately locks workstation
sys: sleep                    -> Puts PC to sleep
sys: mute                     -> Toggles system audio mute
```

---

## ⌨️ Command Syntax & Cheat Sheet

| Prefix / Trigger | Description | Example Query | Action Output |
| :--- | :--- | :--- | :--- |
| `f:` / `<search>` | Instant File & App Search | `f: quarterly_report` | Opens matching document/app |
| `calc:` | Direct Mathematical Calculation | `calc: 4096 / 16` | `= 256` |
| `rem:` | Natural Language Reminder | `rem: review code in 45m` | Triggers OS notification |
| `clip:` | Clipboard Stack Access | `clip: last` | Pastes matching clipboard item |
| `convert:` | Real-time Unit & FX Conversion | `convert: 185 cm to ft` | `≈ 6.07 ft` |
| `sys:` | Operating System Quick Trigger | `sys: lock` | Secure lock state |
| `music:` | Media Controls & Playback Radar | `music: next` | Skips to next track |

---

## 🥊 Feature Matrix

| Feature | Windows Search | PowerToys Run | Raycast (Mac) | **ODD by Humnspace** |
| :--- | :---: | :---: | :---: | :---: |
| **Top Bezel Dynamic Island** | ❌ | ❌ | ❌ | **✅ Native** |
| **Monochrome Aesthetic** | ❌ | ❌ | Partial | **✅ Pure B&W** |
| **Live Vinyl & Audio Radar** | ❌ | ❌ | ❌ | **✅ Built-in** |
| **Zero-Telemetry Guarantee** | ❌ | ✅ | ❌ | **✅ 100% Offline** |
| **RAM Footprint** | ~180MB+ | ~120MB+ | ~150MB+ | **⚡ < 30MB** |
| **Sub-10ms Cold Launch** | ❌ | Partial | ✅ | **✅ Optimized** |
| **Natural Language Actions** | ❌ | Partial | ✅ | **✅ Integrated** |

---

## 💻 System Requirements

- **Operating System**: Windows 11 (all editions) or Windows 10 64-bit (Build 19041 or higher).
- **Architecture**: x64, ARM64 native.
- **Memory**: Minimum 4 GB RAM (ODD consumes `< 30MB` in background).
- **Disk Space**: `< 50MB` local storage.
- **Network**: **No internet connection required** (runs entirely offline).

---

## 🌐 The Humnspace Ecosystem

ODD is part of the **Humnspace** suite of intentional desktop tools:

- **[ODD](https://www.humn.space/odd.html)** — Spotlight Launcher & Screen-Edge Dynamic Island.
- **[Rook](https://www.humn.space/rook.html)** — OS-Level Keyboard Command & Window Workspace Engine.
- **[Humnspace Platform](https://www.humn.space/)** — Minimalist, high-performance desktop productivity software.

---

## 🔒 Security, Privacy & Integrity

At **Humnspace**, we believe your desktop search queries, calculations, and clipboard items belong strictly to you:

- **Zero Cloud Relay**: Queries never leave your local device.
- **No Keystroke Telemetry**: No behavioral tracking, user profiling, or background diagnostic analytics.
- **Local Storage**: All preferences and clip histories are stored in encrypted or secure local configurations.
- **Verified Builds**: All production packages are signed and delivered via **[https://www.humn.space/](https://www.humn.space/)**.

---

## 🤝 Community & Support

- **Official Web Portal**: [https://www.humn.space/](https://www.humn.space/)
- **Product Landing**: [https://www.humn.space/odd.html](https://www.humn.space/odd.html)
- **Email Inquiries**: [me.humnspace@gmail.com](mailto:me.humnspace@gmail.com)
- **X (Twitter)**: [@humnspace](https://x.com/humnspace)
- **Instagram**: [@humnspace](https://www.instagram.com/humnspace)

---

## 📄 License & Intellectual Property

&copy; 2026 **Humnspace Inc.** All rights reserved.

All logos, trademarks, design patterns, and software architecture related to **ODD** and **Humnspace** are proprietary intellectual property of Humnspace Inc. Official distributions and download releases are hosted exclusively at [https://www.humn.space/](https://www.humn.space/).
