# J.A.R.V.I.S. — Advanced AI Hand Gesture Laptop Control System

[![Target OS](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-00f0ff.svg)](https://microsoft.com)
[![Python Version](https://img.shields.io/badge/Python-3.11.9-00a8ff.svg)](https://python.org)
[![Computer Vision](https://img.shields.io/badge/Vision-MediaPipe%20%2B%20OpenCV-00ff88.svg)](https://mediapipe.dev)
[![GUI Engine](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt-ffd700.svg)](https://qt.io)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](#)

A real-time, futuristic Windows desktop application inspired by Tony Stark's **JARVIS** interface. Control your laptop using optical hand tracking through your webcam—without physical mouse or keyboard interaction for normal daily operations.

---

## Table of Contents
1. [Key Features](#key-features)
2. [Interface & HUD Design](#interface--hud-design)
3. [Architecture Overview](#architecture-overview)
4. [Supported Windows & Python Versions](#supported-windows--python-versions)
5. [Installation & Setup (Windows CMD / PowerShell)](#installation--setup)
6. [Running the Application](#running-the-application)
7. [Gesture Reference Table](#gesture-reference-table)
8. [Control Modes](#control-modes)
9. [Configuring Applications & Shortcuts](#configuring-applications--shortcuts)
10. [Safety & Failsafes](#safety--failsafes)
11. [Troubleshooting](#troubleshooting)
12. [Known Limitations](#known-limitations)
13. [Manual Test Verification Checklist](#manual-test-verification-checklist)
14. [Packaging with PyInstaller](#packaging-with-pyinstaller)

---

## Key Features

- **Live Optical Hand Tracking**: Uses Google MediaPipe to track 21 3D hand landmarks in real time with rotation-invariant finger extension analysis.
- **Virtual Cursor & Motion Smoothing**:
  - **1€ Filter (One Euro Filter)**: Mathematically eliminates low-speed hand tremor while dynamically removing lag during ballistic motions.
  - **Adaptive EMA & Standard EMA**: Alternative smoothing modes for varied preferences.
  - **Deadzone Filtering**: Suppresses sub-pixel optical jitter when holding the hand steady to click small buttons or hyperlinks.
  - **Anti-Slip Click Stabilization**: Locks cursor movement during the initial pinch contact window (150ms) so clicking small targets never slides off.
- **Full Ergonomic Mouse Control**:
  - **Ergonomic Tracking Landmarks**: Choose between Index Fingertip, Index Knuckle/MCP (ultra-stable), Index Joint/PIP, or Palm Center (relaxed open hand).
  - **Absolute or Relative Control**: Absolute screen coordinate mapping or Relative trackpad/joystick mode for relaxed wrist control.
  - **Independent X/Y Sensitivity**: Configure horizontal and vertical sensitivities independently to match wide aspect-ratio monitors.
  - **Scale-Invariant Pinch-to-Click**: Normalizes pinch distance against the user's palm scale, providing reliable, consistent clicks at any camera distance.
  - **Separate Hysteresis Thresholds**: Separate pinch activation and release thresholds prevent false double-clicks.
  - **Hold for Drag & Drop**: Hold pinch beyond threshold duration for drag-and-drop.
  - **Right-Click**: Configurable gesture (Thumb-Middle pinch or Index-Middle pinch).
  - **Vertical Scroll**: Two-finger vertical movement with click suppression.
- **Interactive Calibration Wizard**:
  - Step-by-step in-UI wizard for selecting webcams, positioning at optimal distance, recording your natural hand movement ROI, testing cursor smoothness in an isolated sandbox, auto-tuning pinch thresholds, and saving preferences.
- **Stark Industries HUD**:
  - Rotating Arc Reactor visualization with pulsing core and telemetry crosshairs.
  - Real-time measured camera FPS gauge.
  - Optical targeting reticles and skeleton connection overlay with holographic styling.
  - Dynamic proximity progress bar showing distance to pinch click.
- **Application Launcher**:
  - Configurable Windows application launcher (Google Chrome, VS Code, Notepad, File Explorer, Windows Settings, Blender, Godot).
  - Validates paths before launching via safe `subprocess` calls (no raw shell string execution).
- **Windows System Controls**:
  - Master volume control via `pycaw` with multimedia virtual key fallback.
  - Desktop navigation: Alt+Tab window switcher, minimize active window, show desktop.
- **Multi-Tier Safety Architecture**:
  - Control strictly disabled by default at startup.
  - Global `[ESC]` emergency stop hotkey and prominent GUI emergency button.
  - Automatic drag-and-drop cancellation on emergency stop, pause, or tracking loss.
  - Hand stabilization delay (prevents clicks when hand first enters camera frame).
  - Cooldown timers preventing rapid mode toggles.
- **Optional Voice Module**: Whitelisted hands-free voice triggers (e.g., "open chrome", "increase volume", "pause").

---

## Interface & HUD Design

```
+--------------------------------------------------------------------------------------------------+
| STARK INDUSTRIES // J.A.R.V.I.S. MK-IV              [FPS: 30.2]  [STATUS: ACTIVE]  [⚙ SETTINGS]  |
+--------------------------------------------------------------------------------------------------+
|                                                   |  [ARC REACTOR CORE]   [AUDIO: 65% ||||||....]|
|  +---------------------------------------------+  |  [Rotating Rings]     [VOL-] [VOL+] [MUTE]   |
|  | LIVE WEBCAM FEED W/ HOLOGRAPHIC OVERLAYS    |  |----------------------------------------------|
|  | - Glowing Cyan Skeleton & Landmark Nodes    |  |  APPLICATION LAUNCHER                        |
|  | - Active Box ROI Targeting Brackets         |  |  [CHROME]  [VS CODE]  [NOTEPAD]  [EXPLORER]  |
|  | - Fingertip Reticle & Pinch Distance Vector |  |----------------------------------------------|
|  | - Scanning Hologram Grid                    |  |  JARVIS COMMAND & EVENT STREAM               |
|  +---------------------------------------------+  |  [18:42:01] System Initialized               |
|                                                   |  [18:42:04] Optical Tracking Stably Acquired |
|  [OPTICAL TELEMETRY]                              |  [18:42:05] [GESTURE] Left Click Triggered   |
|  Hand: RIGHT | Gesture: CURSOR_MOVE | Pinch: 75%  |  [18:42:08] [AUDIO] Volume Adjusted to 68%   |
+--------------------------------------------------------------------------------------------------+
| MODE: [MOUSE CONTROL]  [APP LAUNCHER]  [SYSTEM CONTROL] | [ALT+TAB] [MIN] | [ENABLE] [PAUSE] [ESC]|
+--------------------------------------------------------------------------------------------------+
```

---

## Architecture Overview

```
JARVIS-Gesture/
├── main.py                     # Application bootstrap & entry point
├── requirements.txt            # Python dependencies
├── config.json                 # Persistent configuration preferences
├── README.md                   # Complete documentation
├── .gitignore                  # Git exclusions
├── app/
│   ├── __init__.py             # Module namespace
│   ├── logger.py               # Rotating file & GUI event broadcast logger
│   ├── settings_manager.py     # JSON configuration loader, validator, and defaults
│   ├── safety_controller.py    # Safety gates, cooldowns, and emergency stop logic
│   ├── hand_tracker.py         # MediaPipe 21-landmark tracking & HUD graphics
│   ├── gesture_recognizer.py   # Discrete/continuous gesture recognition & debouncing
│   ├── virtual_mouse.py        # Screen coordinate mapping, EMA smoothing, PyAutoGUI
│   ├── app_launcher.py         # Path validation & subprocess application runner
│   ├── system_controls.py      # Windows master audio (pycaw) & desktop navigation
│   ├── camera_worker.py        # High-performance async QThread video acquisition loop
│   ├── voice_commander.py      # Optional speech recognition module
│   ├── theme.py                # Futuristic Iron Man Stark QSS stylesheet
│   ├── hud_widgets.py          # Arc Reactor, GlowCard, WebcamHUD, Audio visualizer
│   ├── startup_screen.py       # Diagnostic boot sequence & reactor spin-up screen
│   ├── settings_dialog.py      # User settings modal window
│   └── main_window.py          # Central dashboard integration window
└── tests/
    ├── test_gesture_logic.py   # Hand extension, pinch hysteresis, and debouncing tests
    ├── test_virtual_mouse.py   # Coordinate scaling, active margins, and EMA tests
    ├── test_safety.py          # Safe startup, emergency stops, drag cancellation tests
    ├── test_settings.py        # Config loading, sanitization, and defaults tests
    ├── test_app_launcher.py    # App validation and launch throttling tests
    ├── test_system_controls.py # Audio volume clamping and mute toggle tests
    └── test_gui_init.py        # Headless PySide6 window initialization test
```

---

## Supported Windows & Python Versions

- **Supported OS**: Windows 10 (64-bit) / Windows 11 (64-bit).
- **Supported Python**: Python 3.10, 3.11, or 3.12 (64-bit).
  - *Recommended & verified version*: **Python 3.11.9**.

---

## Installation & Setup

Open **Windows Command Prompt (cmd.exe)** or **PowerShell**:

### 1. Clone or Navigate to the Project Directory
```cmd
cd /d D:\hologram
```

### 2. Create a Virtual Environment
```cmd
python -m venv .venv
```

### 3. Activate the Virtual Environment
- **CMD**:
  ```cmd
  .venv\Scripts\activate.bat
  ```
- **PowerShell**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```

### 4. Install Dependencies
```cmd
pip install -r requirements.txt
```

---

## Running the Application

With the virtual environment activated, run:

```cmd
python main.py
```

### Startup Procedure:
1. The **JARVIS Boot Screen** will display an Arc Reactor spin-up and diagnostic checks.
2. The application will transition automatically to the **Main Dashboard**.
3. **Safety Gate Notice**: Hand tracking is live in the camera viewport immediately, but **Desktop Control is DISABLED by default**.
4. Click **`⚡ ENABLE CONTROL`** on the bottom control bar to allow virtual mouse and desktop interactions.

---

## Gesture Reference Table

| Gesture Name | Hand Pose Description | Triggered Action | Mode Required |
|---|---|---|---|
| **Cursor Tracking** | Index finger extended; other fingers curled | Smooth cursor movement to fingertip position | `MOUSE MODE` |
| **Left Click** | Thumb tip and Index finger tip pinch together (distance < threshold) | Sends single left click with debouncing | `MOUSE MODE` |
| **Drag and Drop** | Hold thumb & index pinch continuously for > 0.45 seconds | Locks left mouse down (`mouseDown`); moves item; releases on pinch open | `MOUSE MODE` |
| **Right Click** | Pinch thumb tip to Middle finger tip (or index + middle pinch) | Sends single right click | `MOUSE MODE` |
| **Vertical Scroll** | Index & Middle fingers extended together; move hand up/down | Scrolls page up (hand moving up) or down (hand moving down) | `MOUSE MODE` |
| **Safe Pause** | Open Palm (all 5 fingers extended and held for 0.5s) | Enters `PAUSED MODE`; halts all OS inputs | Any Mode |
| **Emergency Stop** | Closed Fist (all fingers clenched and held for 0.7s) | Immediately halts all inputs, releases mouse drag, cuts control | Any Mode |
| **Cycle Apps** | Two-finger scroll in `APP LAUNCH MODE` | Cycles through configured applications | `APP LAUNCH MODE` |
| **Launch App** | Index pinch in `APP LAUNCH MODE` | Launches currently highlighted application | `APP LAUNCH MODE` |
| **Volume Control** | Two-finger vertical scroll in `SYSTEM CONTROL MODE` | Adjusts master volume up/down | `SYSTEM CONTROL MODE` |

---

## How to Calibrate the Cursor

For the most comfortable, effortless virtual mouse experience:

1. Launch JARVIS (`python main.py`).
2. Click the **`🎯 CALIBRATE`** button in the top header (or inside `⚙ CONFIGURATION`).
3. Follow the 5-step wizard:
   - **Step 1 (Positioning)**: Hold your hand at your natural resting desk posture (~1.5 to 2.5 ft from your webcam). Confirm the distance meter turns green (`OPTIMAL DISTANCE`).
   - **Step 2 (Movement Region / ROI)**: Click `RECORD NATURAL RANGE` and move your hand across the comfortable bounds of your arm's reach. JARVIS fits a personalized active rectangle to prevent arm strain.
   - **Step 3 (Precision & Smoothing)**: Test cursor movement inside the isolated target sandbox without taking over your desktop. Try switching the tracking point to **`Index Knuckle / MCP`** or **`Palm Center`** to avoid keeping your finger pointed rigidly!
   - **Step 4 (Pinch-to-Click)**: Pinch naturally. Click `AUTO-CALIBRATE PINCH THRESHOLD` to lock in your hand's personal pinch distance.
   - **Step 5 (Save)**: Click `SAVE CALIBRATION & APPLY TO JARVIS`.

---

## Recommended Starting Settings

For users who previously found gesture control tiring or imprecise:

| Setting | Recommended Value | Why |
|---|---|---|
| **Smoothing Algorithm** | `1€ Filter (One Euro)` | Eliminates stationary tremor while allowing zero-lag fast movements. |
| **Low-Speed Filter (Min Cutoff)** | `1.00 Hz` | Rock-solid precision when aiming at small buttons. |
| **High-Speed Factor (Beta)** | `0.050` | Automatically opens up the filter when you flick your wrist quickly. |
| **Ergonomic Tracking Point** | `Index Knuckle / MCP` or `Palm Center` | Eliminates finger strain; allows you to relax your hand into a loose, comfortable posture. |
| **Horizontal / Vertical Sensitivity** | `2.2x` | Full screen reach with compact, relaxed wrist movement. |
| **Anti-Slip Click Stabilization** | `Enabled (150 ms)` | Freezes cursor drift during the pinch squeeze so clicks never slip off targets. |
| **Scale-Normalized Pinch** | `Enabled (Threshold: 0.320)` | Reliable clicks whether your hand is close to or far from the webcam. |
| **Micro-Tremor Deadzone** | `4.0 px` | Ignores involuntary physiological muscle tremor when hovering. |

---

Switch between modes using the bottom toolbar or gesture shortcuts:

1. **MOUSE MODE (`MOUSE CONTROL`)**: Normal desktop cursor navigation, clicking, dragging, and web scrolling.
2. **APP LAUNCH MODE (`APP LAUNCHER`)**: Navigate through configured software without touching the desktop; pinch to launch.
3. **SYSTEM CONTROL MODE (`SYSTEM CONTROL`)**: Raise/lower Windows master volume, mute audio, and switch windows.
4. **PAUSED MODE**: Optical tracking remains active in preview, but gesture actions are blocked.
5. **EMERGENCY STOP**: Total system lock. Press **`ESC`** on physical keyboard or click **`EMERGENCY STOP`** on the GUI.

---

## Configuring Applications & Shortcuts

Click the **`⚙ CONFIGURATION`** button in the top right to open the Settings Dialog:
1. Navigate to the **`APPLICATIONS`** tab.
2. View existing registered applications (Google Chrome, VS Code, Notepad, File Explorer, Windows Settings).
3. Click **`+ ADD APPLICATION`** or **`BROWSE EXECUTABLE...`** to select an `.exe` file on your system.
4. Toggle the **`ENABLED`** checkbox to activate or deactivate specific apps.
5. Click **`SAVE & APPLY`**.

Settings are automatically stored in `config.json` in the workspace root.

---

## Safety & Failsafes

Because this application controls physical OS inputs, multiple safety layers are active:
- **Default Disabled State**: Input generation is off at startup until the user clicks `ENABLE CONTROL`.
- **Keyboard Kill Switch**: Pressing **`Escape` (`ESC`)** instantly drops virtual control and terminates any drag.
- **Drag Cancellation**: Active mouse drags are immediately released if the hand leaves camera view, if emergency stop is triggered, or if control is paused.
- **Click Debouncing**: Rapid clicks are limited by a configurable cooldown timer (default: 0.35s) with hysteresis to prevent accidental double-clicks.
- **Hand Stabilization Guard**: When a hand enters the camera frame, actions are delayed by 0.3s until the landmark positions stabilize.
- **No Arbitrary Commands**: Voice commands and application launching accept only validated executable paths or strict whitelisted verbs.

---

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| **Camera shows "NO SIGNAL" or fails to open** | Webcam in use by another app or permissions blocked | Check Windows Settings > Privacy & Security > Camera. Ensure no other application (Zoom, Teams, Browser) is using the camera. Select another camera index in `⚙ CONFIGURATION`. |
| **Cursor jumps or jitters** | Low lighting or high cursor sensitivity | Ensure adequate room lighting. Open Settings and increase **Cursor Smoothing** slider (0.75 - 0.85) or reduce **Cursor Sensitivity**. |
| **Pinch click triggers unintentionally** | Hand is held too close or pinch threshold is too wide | In Settings, lower the **Pinch Distance Threshold** slider (e.g. 0.045). |
| **Audio volume doesn't change** | Windows audio endpoint initialization issue | Check Windows default playback device. The built-in pycaw module automatically falls back to Windows multimedia keys. |
| **App fails to launch** | Executable is installed in a non-standard directory | Open Settings, browse to the actual location of `chrome.exe` or `Code.exe` on your drive, and click Save. |

---

## Known Limitations

- **Lighting & Occlusion**: MediaPipe hand detection relies on visible finger contrast; performance may degrade in very low light or when fingers overlap extensively.
- **Single Active Webcam**: Only one webcam device stream can be processed at a time.
- **Laptop Webcams with Fixed Exposure**: Some low-cost laptop webcams apply heavy motion blur in dim light, which can affect rapid hand gestures. Keep ambient lighting consistent for best responsiveness.

---

## Manual Test Verification Checklist

Use this checklist to verify your hardware setup:

- [x] **Webcam Tracking**: Launch app, ensure live feed appears, verify cyan skeleton and fingertip reticles follow your hand.
- [x] **Enable Gate**: Verify that moving hand does NOT move OS cursor until clicking `ENABLE CONTROL`.
- [x] **Cursor Movement**: Extend index finger; verify OS cursor smoothly tracks fingertip across screen.
- [x] **Left Click**: Pinch thumb and index finger; verify click registers on desktop icons or web links.
- [x] **Drag & Drop**: Pinch and hold on a window title bar for 0.5s; verify window moves with hand, then releases when pinch opens.
- [x] **Vertical Scroll**: Extend index and middle fingers together; move hand up/down in a web browser; verify smooth scrolling.
- [x] **Right Click**: Pinch thumb and middle finger; verify context menu opens.
- [x] **Safe Pause**: Hold open palm for 0.5s; verify status updates to `PAUSED MODE`.
- [x] **Emergency Stop**: Press physical `ESC` key or clench fist; verify immediate input halt and red emergency badge.
- [x] **Application Launch**: Click `APP LAUNCHER` mode, cycle apps, pinch to launch Notepad or Explorer.

---

## Packaging with PyInstaller

To build a standalone Windows executable (`.exe`):

1. Install PyInstaller into the virtual environment:
   ```cmd
   pip install pyinstaller
   ```

2. Build the executable with all assets and MediaPipe models bundled:
   ```cmd
   pyinstaller --noconsole --name "JARVIS-Gesture" --add-data "config.json;." --collect-all mediapipe --collect-all PySide6 main.py
   ```

3. The compiled binary will be located in the `dist\JARVIS-Gesture\` folder. Run `dist\JARVIS-Gesture\JARVIS-Gesture.exe`.

---

*Engineered with Stark Industries precision for Windows 10 & 11.*
