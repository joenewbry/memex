#!/usr/bin/env python3
"""Create custom Terminal.app profiles for each Digital Surface Labs project."""

import plistlib
import subprocess
import os

from AppKit import NSColor, NSFont
from Foundation import NSKeyedArchiver


def color_data(r, g, b, a=1.0):
    """Convert RGB floats (0-1) to archived NSColor data."""
    c = NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
    return bytes(NSKeyedArchiver.archivedDataWithRootObject_(c))


def font_data(name="MenloRegular", size=13):
    """Convert font spec to archived NSFont data."""
    f = NSFont.fontWithName_size_(name, size)
    if not f:
        f = NSFont.fontWithName_size_("Menlo-Regular", size)
    return bytes(NSKeyedArchiver.archivedDataWithRootObject_(f))


def make_profile(name, bg, fg, bold, cursor, selection, ansi_normal, ansi_bright):
    """Build a complete Terminal.app profile dict."""
    p = {
        "name": name,
        "type": "Window Settings",
        "ProfileCurrentVersion": 2.07,
        "BackgroundColor": color_data(*bg),
        "TextColor": color_data(*fg),
        "TextBoldColor": color_data(*bold),
        "CursorColor": color_data(*cursor),
        "SelectionColor": color_data(*selection),
        "Font": font_data("MenloRegular", 13),
        "FontWidthSpacing": 1.0,
        "FontHeightSpacing": 1.0,
        "UseBrightBold": True,
        "CursorBlink": False,
        "CursorType": 0,
        "ShowRepresentedURLInTitle": True,
        "ShowRepresentedURLPathInTitle": True,
        "ShowActiveProcessInTitle": True,
        "ShowWindowSettingsNameInTitle": True,
        "columnCount": 120,
        "rowCount": 36,
        "ShouldLimitScrollback": 0,
        "ScrollbackLines": 10000,
        "BackgroundBlur": 0.0,
        "BackgroundAlphaInactive": 1.0,
        "BackgroundSettingsForInactiveWindows": False,
    }

    ansi_keys_normal = [
        "ANSIBlackColor", "ANSIRedColor", "ANSIGreenColor", "ANSIYellowColor",
        "ANSIBlueColor", "ANSIMagentaColor", "ANSICyanColor", "ANSIWhiteColor",
    ]
    ansi_keys_bright = [
        "ANSIBrightBlackColor", "ANSIBrightRedColor", "ANSIBrightGreenColor",
        "ANSIBrightYellowColor", "ANSIBrightBlueColor", "ANSIBrightMagentaColor",
        "ANSIBrightCyanColor", "ANSIBrightWhiteColor",
    ]

    for i, key in enumerate(ansi_keys_normal):
        p[key] = color_data(*ansi_normal[i])
    for i, key in enumerate(ansi_keys_bright):
        p[key] = color_data(*ansi_bright[i])

    return p


def save_profile(profile, directory):
    """Save as .terminal file."""
    path = os.path.join(directory, profile["name"] + ".terminal")
    with open(path, "wb") as f:
        plistlib.dump(profile, f)
    print(f"  Created: {path}")
    return path


# ── Color Schemes ──────────────────────────────────────────────
# RULE: Vibrant/bright color = BACKGROUND, dark text on top.
# Exceptions: Memex, Modern Newspaper, Open Arcade (kept as-is).

profiles = {}

# 1. Memex — white bg, black text (KEEP AS-IS)
profiles["Memex"] = make_profile(
    name="Memex",
    bg=(1.0, 1.0, 1.0),
    fg=(0.12, 0.12, 0.12),
    bold=(0.0, 0.0, 0.0),
    cursor=(0.2, 0.4, 0.85),
    selection=(0.82, 0.88, 1.0),
    ansi_normal=[
        (0.15, 0.15, 0.15), (0.7, 0.1, 0.1), (0.1, 0.5, 0.1),
        (0.55, 0.45, 0.0), (0.1, 0.25, 0.7), (0.5, 0.1, 0.5),
        (0.0, 0.45, 0.5), (0.5, 0.5, 0.5),
    ],
    ansi_bright=[
        (0.35, 0.35, 0.35), (0.85, 0.2, 0.2), (0.15, 0.65, 0.15),
        (0.7, 0.6, 0.0), (0.2, 0.4, 0.85), (0.65, 0.25, 0.65),
        (0.0, 0.6, 0.65), (0.25, 0.25, 0.25),
    ],
)

# 2. OpenClaw — FLIPPED: bright orange lobster background
profiles["OpenClaw"] = make_profile(
    name="OpenClaw",
    bg=(1.0, 0.45, 0.18),
    fg=(0.18, 0.06, 0.0),
    bold=(0.1, 0.03, 0.0),
    cursor=(0.45, 0.15, 0.02),
    selection=(0.85, 0.33, 0.1),
    ansi_normal=[
        (0.12, 0.04, 0.0), (0.55, 0.0, 0.0), (0.0, 0.35, 0.0),
        (0.45, 0.3, 0.0), (0.1, 0.1, 0.5), (0.45, 0.0, 0.3),
        (0.0, 0.3, 0.35), (0.45, 0.2, 0.1),
    ],
    ansi_bright=[
        (0.3, 0.12, 0.04), (0.7, 0.05, 0.0), (0.0, 0.45, 0.05),
        (0.55, 0.4, 0.0), (0.15, 0.15, 0.6), (0.55, 0.05, 0.4),
        (0.0, 0.4, 0.45), (0.55, 0.3, 0.15),
    ],
)

# 3. Open Arcade — retro gaming (KEEP AS-IS)
profiles["Open Arcade"] = make_profile(
    name="Open Arcade",
    bg=(0.03, 0.03, 0.07),
    fg=(0.0, 1.0, 0.27),
    bold=(0.3, 1.0, 0.5),
    cursor=(1.0, 1.0, 0.0),
    selection=(0.08, 0.2, 0.08),
    ansi_normal=[
        (0.1, 0.1, 0.15), (1.0, 0.2, 0.2), (0.0, 0.85, 0.25),
        (1.0, 1.0, 0.0), (0.2, 0.4, 1.0), (1.0, 0.0, 1.0),
        (0.0, 1.0, 1.0), (0.9, 0.9, 0.9),
    ],
    ansi_bright=[
        (0.3, 0.3, 0.35), (1.0, 0.4, 0.4), (0.2, 1.0, 0.4),
        (1.0, 1.0, 0.4), (0.4, 0.6, 1.0), (1.0, 0.4, 1.0),
        (0.4, 1.0, 1.0), (1.0, 1.0, 1.0),
    ],
)

# 4. Buddy — FLIPPED: light coffee/latte background
profiles["Buddy"] = make_profile(
    name="Buddy",
    bg=(0.84, 0.68, 0.5),
    fg=(0.18, 0.12, 0.06),
    bold=(0.1, 0.06, 0.02),
    cursor=(0.38, 0.25, 0.12),
    selection=(0.72, 0.56, 0.38),
    ansi_normal=[
        (0.12, 0.08, 0.03), (0.55, 0.05, 0.0), (0.0, 0.35, 0.05),
        (0.45, 0.35, 0.0), (0.1, 0.15, 0.5), (0.45, 0.05, 0.35),
        (0.0, 0.32, 0.35), (0.48, 0.35, 0.22),
    ],
    ansi_bright=[
        (0.3, 0.22, 0.12), (0.65, 0.1, 0.05), (0.05, 0.45, 0.1),
        (0.55, 0.45, 0.0), (0.15, 0.2, 0.6), (0.55, 0.1, 0.42),
        (0.0, 0.42, 0.44), (0.55, 0.42, 0.28),
    ],
)

# 5. Ramp — FLIPPED: bright pink/magenta background
profiles["Ramp"] = make_profile(
    name="Ramp",
    bg=(1.0, 0.47, 0.78),
    fg=(0.15, 0.02, 0.1),
    bold=(0.08, 0.0, 0.05),
    cursor=(0.45, 0.1, 0.3),
    selection=(0.85, 0.35, 0.65),
    ansi_normal=[
        (0.1, 0.0, 0.06), (0.5, 0.0, 0.1), (0.0, 0.35, 0.1),
        (0.5, 0.35, 0.0), (0.1, 0.05, 0.55), (0.45, 0.0, 0.35),
        (0.0, 0.3, 0.38), (0.5, 0.2, 0.38),
    ],
    ansi_bright=[
        (0.28, 0.08, 0.18), (0.6, 0.05, 0.15), (0.0, 0.45, 0.15),
        (0.6, 0.45, 0.0), (0.15, 0.1, 0.65), (0.55, 0.05, 0.45),
        (0.0, 0.4, 0.48), (0.6, 0.3, 0.48),
    ],
)

# 6. Screen Self-Driving — FLIPPED: bright cyan/teal background
profiles["Screen Self-Driving"] = make_profile(
    name="Screen Self-Driving",
    bg=(0.0, 0.82, 0.84),
    fg=(0.02, 0.1, 0.1),
    bold=(0.0, 0.05, 0.06),
    cursor=(0.0, 0.35, 0.36),
    selection=(0.0, 0.66, 0.68),
    ansi_normal=[
        (0.01, 0.06, 0.06), (0.55, 0.0, 0.05), (0.0, 0.35, 0.12),
        (0.42, 0.35, 0.0), (0.05, 0.08, 0.5), (0.4, 0.0, 0.35),
        (0.0, 0.35, 0.38), (0.0, 0.42, 0.43),
    ],
    ansi_bright=[
        (0.0, 0.22, 0.23), (0.65, 0.05, 0.1), (0.0, 0.45, 0.18),
        (0.52, 0.45, 0.0), (0.1, 0.12, 0.6), (0.5, 0.05, 0.45),
        (0.0, 0.45, 0.48), (0.0, 0.52, 0.53),
    ],
)

# 7. Prospector — FLIPPED: gold background
profiles["Prospector"] = make_profile(
    name="Prospector",
    bg=(1.0, 0.84, 0.0),
    fg=(0.18, 0.14, 0.0),
    bold=(0.1, 0.07, 0.0),
    cursor=(0.42, 0.32, 0.0),
    selection=(0.85, 0.7, 0.0),
    ansi_normal=[
        (0.12, 0.1, 0.0), (0.55, 0.0, 0.0), (0.0, 0.35, 0.0),
        (0.45, 0.35, 0.0), (0.08, 0.08, 0.5), (0.45, 0.0, 0.3),
        (0.0, 0.3, 0.32), (0.48, 0.4, 0.0),
    ],
    ansi_bright=[
        (0.3, 0.24, 0.0), (0.65, 0.05, 0.0), (0.0, 0.45, 0.05),
        (0.55, 0.45, 0.0), (0.12, 0.12, 0.6), (0.55, 0.05, 0.38),
        (0.0, 0.4, 0.42), (0.58, 0.48, 0.0),
    ],
)

# 8. Modern Newspaper — cream/newspaper (KEEP AS-IS)
profiles["Modern Newspaper"] = make_profile(
    name="Modern Newspaper",
    bg=(1.0, 0.97, 0.91),
    fg=(0.2, 0.15, 0.1),
    bold=(0.12, 0.08, 0.04),
    cursor=(0.4, 0.3, 0.2),
    selection=(0.88, 0.83, 0.73),
    ansi_normal=[
        (0.2, 0.15, 0.1), (0.7, 0.15, 0.1), (0.2, 0.45, 0.2),
        (0.55, 0.45, 0.1), (0.15, 0.25, 0.55), (0.5, 0.15, 0.4),
        (0.1, 0.4, 0.45), (0.5, 0.45, 0.38),
    ],
    ansi_bright=[
        (0.4, 0.35, 0.28), (0.85, 0.25, 0.15), (0.3, 0.6, 0.3),
        (0.7, 0.6, 0.15), (0.25, 0.4, 0.7), (0.65, 0.25, 0.55),
        (0.15, 0.55, 0.6), (0.6, 0.55, 0.45),
    ],
)

# 9. Task Processor — FLIPPED: warm coral background (unique color)
profiles["Task Processor"] = make_profile(
    name="Task Processor",
    bg=(0.98, 0.55, 0.45),
    fg=(0.18, 0.04, 0.02),
    bold=(0.1, 0.02, 0.0),
    cursor=(0.45, 0.15, 0.1),
    selection=(0.82, 0.42, 0.32),
    ansi_normal=[
        (0.12, 0.03, 0.02), (0.5, 0.0, 0.0), (0.0, 0.35, 0.08),
        (0.48, 0.35, 0.0), (0.08, 0.08, 0.5), (0.45, 0.0, 0.32),
        (0.0, 0.3, 0.35), (0.48, 0.2, 0.15),
    ],
    ansi_bright=[
        (0.3, 0.1, 0.06), (0.6, 0.05, 0.02), (0.0, 0.45, 0.12),
        (0.58, 0.45, 0.0), (0.12, 0.12, 0.6), (0.55, 0.05, 0.4),
        (0.0, 0.4, 0.45), (0.58, 0.28, 0.2),
    ],
)

# 10. Global Data — FLIPPED: ocean blue background
profiles["Global Data"] = make_profile(
    name="Global Data",
    bg=(0.18, 0.58, 0.82),
    fg=(0.02, 0.08, 0.14),
    bold=(0.0, 0.04, 0.1),
    cursor=(0.05, 0.22, 0.38),
    selection=(0.12, 0.45, 0.68),
    ansi_normal=[
        (0.01, 0.05, 0.08), (0.5, 0.0, 0.05), (0.0, 0.3, 0.08),
        (0.42, 0.32, 0.0), (0.05, 0.05, 0.45), (0.4, 0.0, 0.32),
        (0.0, 0.28, 0.32), (0.05, 0.25, 0.38),
    ],
    ansi_bright=[
        (0.05, 0.2, 0.28), (0.6, 0.05, 0.1), (0.0, 0.4, 0.12),
        (0.52, 0.42, 0.0), (0.1, 0.1, 0.55), (0.5, 0.05, 0.4),
        (0.0, 0.38, 0.42), (0.08, 0.32, 0.48),
    ],
)

# 11. Alice 001 — FLIPPED: lavender/purple background
profiles["Alice 001"] = make_profile(
    name="Alice 001",
    bg=(0.74, 0.58, 0.98),
    fg=(0.1, 0.04, 0.2),
    bold=(0.06, 0.02, 0.14),
    cursor=(0.32, 0.18, 0.52),
    selection=(0.6, 0.44, 0.82),
    ansi_normal=[
        (0.08, 0.03, 0.16), (0.55, 0.0, 0.1), (0.0, 0.32, 0.08),
        (0.48, 0.38, 0.0), (0.12, 0.05, 0.5), (0.42, 0.0, 0.38),
        (0.0, 0.28, 0.35), (0.35, 0.25, 0.5),
    ],
    ansi_bright=[
        (0.22, 0.12, 0.35), (0.65, 0.05, 0.15), (0.0, 0.42, 0.12),
        (0.58, 0.48, 0.0), (0.18, 0.1, 0.6), (0.52, 0.05, 0.48),
        (0.0, 0.38, 0.45), (0.42, 0.32, 0.6),
    ],
)

# 12. Directory — clean minimal gray (KEEP AS-IS)
profiles["Directory"] = make_profile(
    name="Directory",
    bg=(0.1, 0.1, 0.1),
    fg=(0.82, 0.82, 0.82),
    bold=(1.0, 1.0, 1.0),
    cursor=(0.6, 0.6, 0.6),
    selection=(0.22, 0.22, 0.22),
    ansi_normal=[
        (0.15, 0.15, 0.15), (0.85, 0.3, 0.3), (0.3, 0.75, 0.35),
        (0.8, 0.7, 0.25), (0.35, 0.5, 0.85), (0.7, 0.4, 0.7),
        (0.3, 0.7, 0.72), (0.82, 0.82, 0.82),
    ],
    ansi_bright=[
        (0.38, 0.38, 0.38), (1.0, 0.45, 0.45), (0.45, 0.9, 0.5),
        (0.95, 0.85, 0.35), (0.5, 0.65, 1.0), (0.85, 0.55, 0.85),
        (0.45, 0.85, 0.88), (1.0, 1.0, 1.0),
    ],
)

# ── Save all profiles ──────────────────────────────────────────

out_dir = os.path.expanduser("~/Desktop/Terminal Profiles")
os.makedirs(out_dir, exist_ok=True)

print(f"Creating {len(profiles)} Terminal profiles in: {out_dir}\n")

paths = []
for name, profile in profiles.items():
    path = save_profile(profile, out_dir)
    paths.append(path)

print(f"\nDone! {len(paths)} profiles created.")
print("\nTo install: double-click each .terminal file, or run:")
print(f'  open "{out_dir}/"*.terminal')
