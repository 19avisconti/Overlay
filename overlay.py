"""
overlay.py — click-through transparent NSWindow + animated text overlay.

Architecture:
  OverlayView (full-screen transparent container)
  ├── TextLayer (_main)   current chunk · full opacity · top-center cell
  └── TextLayer (_ghost)  next chunk preview · PREVIEW_ALPHA · just below _main
                          first line only · CAGradientLayer mask: transparent at
                          bottom → opaque at top (hides size differences, seamless
                          animation when ghost slides up to become the new main)

Both layers use identical font-sizing logic. Because the algorithm is deterministic,
the ghost already has the correct font when it reaches the main position — no jump.
"""

import objc
import AppKit
import Quartz

# ── Layout constants ──────────────────────────────────────────────────────────
CELL_PADDING    = 20    # padding inside each text cell on each side
NOTCH_OFFSET    = 30    # shift both cells down to clear the camera notch
GHOST_CLOSE     = 40    # pixels to lift ghost above its natural position
PREVIEW_ALPHA   = 0.5   # layer alpha of the ghost (gradient provides the vertical fade)
ANIM_DURATION   = 0.35  # seconds for the slide-up transition
GHOST_MAX_LINES = 1     # ghost displays this many lines
FONT_SIZE_MIN   = 16
FONT_SIZE_MAX   = 300


class TextLayer(AppKit.NSView):
    """
    Layer-backed NSView that draws a single text chunk, auto-sized to fill its cell.

    role='main'  — centered vertically, all lines.
    role='ghost' — top-aligned (sits close to _main), first GHOST_MAX_LINES lines.
                   OverlayView applies a CAGradientLayer mask: bottom=transparent,
                   top=opaque, so the preview fades in naturally as it slides up.
    """

    def initWithFrame_(self, frame):
        self = objc.super(TextLayer, self).initWithFrame_(frame)
        if self is None:
            return None
        self._text = ""
        self._role = "main"   # "main" | "ghost"
        self.setWantsLayer_(True)
        return self

    @objc.python_method
    def setText_(self, text):
        self._text = text
        self.setNeedsDisplay_(True)

    def isOpaque(self):
        return False

    def drawRect_(self, dirty_rect):
        if not self._text:
            return

        b = self.bounds()
        w, h     = b.size.width, b.size.height
        avail_w  = w - CELL_PADDING * 2
        avail_h  = h - CELL_PADDING * 2
        is_ghost = self._role == "ghost"

        font_size = self._best_font_size(self._text, avail_w, avail_h)
        font      = AppKit.NSFont.boldSystemFontOfSize_(font_size)

        shadow = AppKit.NSShadow.alloc().init()
        shadow.setShadowBlurRadius_(6)
        shadow.setShadowOffset_((2, -4))
        shadow.setShadowColor_(AppKit.NSColor.colorWithWhite_alpha_(0.0, 0.7))

        attrs = {
            AppKit.NSFontAttributeName: font,
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.colorWithWhite_alpha_(0.95, 0.8),
            AppKit.NSShadowAttributeName: shadow,
        }

        lines   = self._wrap_text(self._text, font, avail_w)
        if is_ghost:
            lines = lines[:GHOST_MAX_LINES]

        line_h  = font.ascender() - font.descender()
        total_h = line_h * len(lines)

        # Ghost snaps to top so its text sits close to the bottom of _main.
        # Main centers its text block vertically in the cell.
        if is_ghost:
            start_y = h - CELL_PADDING - font.ascender()
        else:
            start_y = h / 2 + total_h / 2 - font.ascender()

        for i, line in enumerate(lines):
            attr_str = (AppKit.NSAttributedString.alloc()
                        .initWithString_attributes_(line, attrs))
            x = w / 2 - attr_str.size().width / 2
            y = start_y - i * line_h
            attr_str.drawAtPoint_((x, y))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @objc.python_method
    def _wrap_text(self, text, font, avail_w):
        words = text.split()
        lines, current = [], []
        attrs = {AppKit.NSFontAttributeName: font}
        for word in words:
            candidate = " ".join(current + [word])
            cw = (AppKit.NSAttributedString.alloc()
                  .initWithString_attributes_(candidate, attrs)
                  .size().width)
            if cw <= avail_w:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
        return lines or [text]

    @objc.python_method
    def _best_font_size(self, text, avail_w, avail_h):
        """Binary-search for the largest font where the full text fits in avail_w × avail_h."""
        lo, hi, best = float(FONT_SIZE_MIN), float(FONT_SIZE_MAX), float(FONT_SIZE_MIN)
        while hi - lo > 1:
            mid   = (lo + hi) / 2
            font  = AppKit.NSFont.boldSystemFontOfSize_(mid)
            lines = self._wrap_text(text, font, avail_w)
            attrs = {AppKit.NSFontAttributeName: font}
            max_w = max(
                AppKit.NSAttributedString.alloc()
                .initWithString_attributes_(line, attrs).size().width
                for line in lines
            )
            total_h = (font.ascender() - font.descender()) * len(lines)
            if max_w <= avail_w and total_h <= avail_h:
                best = mid
                lo   = mid
            else:
                hi = mid
        return best


class OverlayView(AppKit.NSView):
    """
    Full-screen transparent container.
    _main  — current chunk at the top-center 3×3 cell, full opacity.
    _ghost — next-chunk preview just below _main, with a gradient mask.
    """

    def initWithFrame_(self, frame):
        self = objc.super(OverlayView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._chunks    = []
        self._index     = 0
        self._animating = False

        self._main  = TextLayer.alloc().initWithFrame_(AppKit.NSZeroRect)
        self._ghost = TextLayer.alloc().initWithFrame_(AppKit.NSZeroRect)
        self._ghost._role = "ghost"
        self._ghost.setAlphaValue_(PREVIEW_ALPHA)

        self.setWantsLayer_(True)
        self.addSubview_(self._main)
        self.addSubview_(self._ghost)
        return self

    # ── Public API ────────────────────────────────────────────────────────────

    def setChunks_(self, chunks):
        self._chunks = list(chunks)
        self._index  = 0
        self._refresh_layout()
        self._update_content()

    def showNext(self):
        if not self._chunks or self._animating:
            return
        self._index = (self._index + 1) % len(self._chunks)
        self._animate_forward()

    def showPrevious(self):
        if not self._chunks or self._animating:
            return
        self._index = (self._index - 1) % len(self._chunks)
        self._main.setAlphaValue_(1.0)
        self._ghost.setAlphaValue_(PREVIEW_ALPHA)
        self._refresh_layout()
        self._update_content()

    # ── Layout ────────────────────────────────────────────────────────────────

    def isOpaque(self):
        return False

    def drawRect_(self, dirty_rect):
        pass

    def setFrameSize_(self, size):
        objc.super(OverlayView, self).setFrameSize_(size)
        if hasattr(self, "_main"):
            self._refresh_layout()

    @objc.python_method
    def _cell_frame(self):
        b = self.bounds()
        w, h = b.size.width, b.size.height
        cw, ch = w / 3, h / 3
        return AppKit.NSMakeRect(w / 3, 2 * h / 3 - NOTCH_OFFSET, cw, ch)

    @objc.python_method
    def _ghost_frame(self):
        b = self.bounds()
        w, h = b.size.width, b.size.height
        cw, ch = w / 3, h / 3
        return AppKit.NSMakeRect(w / 3, h / 3 - NOTCH_OFFSET + GHOST_CLOSE, cw, ch)

    @objc.python_method
    def _exit_frame(self):
        b = self.bounds()
        w, h = b.size.width, b.size.height
        cw, ch = w / 3, h / 3
        return AppKit.NSMakeRect(w / 3, h + ch, cw, ch)

    @objc.python_method
    def _refresh_layout(self):
        self._main.setFrame_(self._cell_frame())
        self._ghost.setFrame_(self._ghost_frame())
        self._apply_gradient_mask(self._ghost)

    @objc.python_method
    def _update_content(self):
        if not self._chunks:
            return
        self._main.setText_(self._chunks[self._index])
        self._ghost.setText_(self._chunks[(self._index + 1) % len(self._chunks)])

    # ── Gradient mask ─────────────────────────────────────────────────────────

    @objc.python_method
    def _apply_gradient_mask(self, view):
        """
        Attach a CAGradientLayer mask to view's backing layer.
        On macOS, CALayer origin is bottom-left, so startPoint=(0.5,0) is the
        bottom and endPoint=(0.5,1) is the top.
          colors[0] at bottom → transparent (alpha=0)
          colors[1] at top    → opaque     (alpha=1)
        The ghost text is top-aligned, so it appears clearly at the top of the
        frame and fades to nothing at the bottom.
        """
        b  = view.bounds()
        cs = Quartz.CGColorSpaceCreateDeviceGray()
        mask = Quartz.CAGradientLayer.layer()
        mask.setFrame_(AppKit.NSMakeRect(0, 0, b.size.width, b.size.height))
        mask.setColors_([
            Quartz.CGColorCreate(cs, [0.0, 0.0]),  # bottom: transparent
            Quartz.CGColorCreate(cs, [0.0, 1.0]),  # top:    opaque
        ])
        mask.setStartPoint_((0.5, 0.0))
        mask.setEndPoint_((0.5, 1.0))
        view.layer().setMask_(mask)

    # ── Animation ─────────────────────────────────────────────────────────────

    @objc.python_method
    def _animate_forward(self):
        self._animating = True
        cell  = self._cell_frame()
        exit_ = self._exit_frame()

        def animate(ctx):
            ctx.setDuration_(ANIM_DURATION)
            self._ghost.animator().setFrame_(cell)
            self._ghost.animator().setAlphaValue_(1.0)
            self._main.animator().setFrame_(exit_)
            self._main.animator().setAlphaValue_(0.0)

        def after():
            # Swap roles.
            self._main, self._ghost = self._ghost, self._main
            self._main._role  = "main"
            self._ghost._role = "ghost"

            # New main arrived via animation — remove its gradient mask.
            self._main.layer().setMask_(None)

            # Reposition and prep the new ghost before it becomes visible.
            self._ghost.setAlphaValue_(0.0)
            self._ghost.setFrame_(self._ghost_frame())
            self._apply_gradient_mask(self._ghost)

            self._update_content()
            self._main.setNeedsDisplay_(True)
            self._ghost.setNeedsDisplay_(True)
            self._ghost.setAlphaValue_(PREVIEW_ALPHA)
            self._main.setAlphaValue_(1.0)
            self._animating = False

        AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(animate, after)


def create_overlay_window():
    """
    Create a borderless, click-through, always-on-top window covering the
    main screen. Returns (NSWindow, OverlayView).
    """
    screen = AppKit.NSScreen.mainScreen()
    frame  = screen.frame() if screen else AppKit.NSMakeRect(0, 0, 1920, 1080)

    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        frame,
        AppKit.NSWindowStyleMaskBorderless,
        AppKit.NSBackingStoreBuffered,
        False,
    )

    window.setLevel_(AppKit.NSStatusWindowLevel)
    window.setIgnoresMouseEvents_(True)
    window.setOpaque_(False)
    window.setHasShadow_(False)
    window.setBackgroundColor_(AppKit.NSColor.clearColor())
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        | AppKit.NSWindowCollectionBehaviorStationary
    )
    window.setReleasedWhenClosed_(False)
    window.setSharingType_(AppKit.NSWindowSharingNone)

    view = OverlayView.alloc().initWithFrame_(frame)
    window.setContentView_(view)

    return window, view
