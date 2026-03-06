#!/usr/bin/env python3
"""
Overlay — click-through text overlay with keyboard cycling.

Controls (global hotkeys, work even when other apps are focused):
  Command + Shift   next chunk      (⌘ + ⇧, either side)
  Option  + Shift   previous chunk  (⌥ + ⇧, either side)
  The two chords are mutually exclusive — holding both ⌘ and ⌥ fires neither.

A menu-bar icon (◈) provides a Quit option since the window is click-through.

NOTE: Requires Accessibility permission for global hotkeys.
Since this runs via Terminal, add Terminal.app (not Python) to the list:
  System Settings → Privacy & Security → Accessibility → click + → Terminal
Then relaunch.
"""

import os
import AppKit
from Foundation import NSObject, NSOperationQueue
import objc
from pynput import keyboard as kb

from overlay import create_overlay_window

# ── Load script ───────────────────────────────────────────────────────────────

def load_chunks(path, sentences_per_chunk=2):
    """Read a text file (one sentence per line) and group into chunks."""
    with open(path) as f:
        sentences = [line.strip() for line in f if line.strip()]
    return [
        "  ".join(sentences[i : i + sentences_per_chunk])
        for i in range(0, len(sentences), sentences_per_chunk)
    ]

_here = os.path.dirname(os.path.abspath(__file__))
CHUNKS = load_chunks(os.path.join(_here, "script.txt"), sentences_per_chunk=2)

class AppDelegate(NSObject):

    def applicationDidFinishLaunching_(self, notification):
        # Hide from Dock and app switcher
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

        self._window, self._view = create_overlay_window()
        self._view.setChunks_(CHUNKS)
        self._window.makeKeyAndOrderFront_(None)

        self._setup_hotkeys()
        self._setup_status_item()

    # ── Hotkeys ───────────────────────────────────────────────────────────────

    @objc.python_method
    def _setup_hotkeys(self):
        """
        Command + Shift (either side) → next chunk.
        Option  + Shift (either side) → previous chunk.
        Mutually exclusive: if both ⌘ and ⌥ are held, neither fires.

        `key not in _pressed` guard blocks OS key-repeat so each physical
        tap fires exactly once. pynput callbacks run on a background thread;
        UI updates are dispatched to the main thread via NSOperationQueue.
        """
        view = self._view
        _pressed    = set()
        _SHIFT_KEYS = {kb.Key.shift, kb.Key.shift_l, kb.Key.shift_r}
        _CMD_KEYS   = {kb.Key.cmd_l, kb.Key.cmd_r}
        _OPT_KEYS   = {kb.Key.alt_l, kb.Key.alt_r}

        def on_press(key):
            if key in _pressed:     # ignore OS key-repeat
                return
            _pressed.add(key)
            has_shift = bool(_pressed & _SHIFT_KEYS)
            has_cmd   = bool(_pressed & _CMD_KEYS)
            has_opt   = bool(_pressed & _OPT_KEYS)
            if has_shift and has_cmd and not has_opt:
                NSOperationQueue.mainQueue().addOperationWithBlock_(view.showNext)
            elif has_shift and has_opt and not has_cmd:
                NSOperationQueue.mainQueue().addOperationWithBlock_(view.showPrevious)

        def on_release(key):
            _pressed.discard(key)

        self._listener = kb.Listener(on_press=on_press, on_release=on_release, suppress=False)
        self._listener.start()

    # ── Status bar ────────────────────────────────────────────────────────────

    @objc.python_method
    def _setup_status_item(self):
        """Menu-bar icon with a Quit item (only way to exit a click-through app)."""
        self._status_item = (
            AppKit.NSStatusBar.systemStatusBar()
            .statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        )
        self._status_item.button().setTitle_("◈")

        menu = AppKit.NSMenu.alloc().init()
        quit_item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", "q"
        )
        menu.addItem_(quit_item)
        self._status_item.setMenu_(menu)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def applicationWillTerminate_(self, notification):
        if hasattr(self, "_listener"):
            self._listener.stop()


if __name__ == "__main__":
    app = AppKit.NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()
