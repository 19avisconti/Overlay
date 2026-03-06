# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A macOS menu-bar app that displays a click-through text overlay covering the main screen. Text chunks are cycled with global keyboard shortcuts. Built with Python + pyobjc (direct AppKit bindings), mirroring the Swift overlay mechanics from the `flow` Spotify lyrics project.

## Running

```bash
pip install -r requirements.txt
python main.py
```

On first run, macOS will prompt for **Accessibility permission** (required for global key monitoring). Grant it in System Settings → Privacy & Security → Accessibility, then relaunch.

## Controls

| Key | Action |
|-----|--------|
| → or Space | Next chunk |
| ← | Previous chunk |
| Menu bar ◈ → Quit | Exit (window is click-through so there's no other way) |

## Architecture

**`main.py`** — entry point and `AppDelegate`
- Sets activation policy to `.accessory` (hides from Dock/app switcher)
- Installs a global `NSEvent` key monitor (`addGlobalMonitorForEventsMatchingMask_handler_`) for → / ← / Space
- Creates the menu-bar status item with a Quit option

**`overlay.py`** — `OverlayView` (NSView subclass) + `create_overlay_window()`
- `create_overlay_window()` returns a `(NSWindow, OverlayView)` pair configured with the key overlay flags (see below)
- `OverlayView.drawRect_()` handles all drawing: binary-search font sizing, word-wrapping, centering, and drop shadow
- `setChunks_()` / `showNext()` / `showPrevious()` are the public API

## Key overlay window flags

These are the properties that make the window work as a transparent overlay (ported directly from the Swift `OverlayWindow`):

```python
window.setLevel_(AppKit.NSStatusWindowLevel)           # float above normal windows
window.setIgnoresMouseEvents_(True)                    # click-through
window.setOpaque_(False)                               # allow transparent background
window.setBackgroundColor_(AppKit.NSColor.clearColor())
window.setCollectionBehavior_(
    NSWindowCollectionBehaviorCanJoinAllSpaces          # visible on all Spaces
    | NSWindowCollectionBehaviorFullScreenAuxiliary     # visible over fullscreen apps
    | NSWindowCollectionBehaviorStationary             # doesn't move with Mission Control
)
```

## Editing content

Put your text chunks in the `CHUNKS` list in `main.py`. The font auto-scales to fill the screen.

## pyobjc notes

- ObjC method `someMethod:withArg:` → Python `someMethod_withArg_()`
- Helper methods on NSView subclasses should use `@objc.python_method` to prevent pyobjc from registering them with the ObjC runtime
- `NSRect` structs are accessed as `.size.width`, `.size.height`, `.origin.x`, `.origin.y`
- `font.ascender()` and `font.descender()` are called as methods (descender is negative)
