package dev.synesis.poc;

import javax.swing.JFrame;
import java.awt.AWTEvent;
import java.awt.EventQueue;
import java.awt.Toolkit;
import java.awt.event.MouseEvent;
import java.lang.ref.WeakReference;

/** Compensates for the stale title-bar inset in macOS native fullscreen. */
final class MacFullscreenMouseFix extends EventQueue {
    private final WeakReference<JFrame> frame;
    private volatile boolean fullscreen;
    private boolean installed;

    MacFullscreenMouseFix(JFrame frame) {
        this.frame = new WeakReference<>(frame);
    }

    void install() {
        if (installed || !System.getProperty("os.name", "").toLowerCase(java.util.Locale.ROOT).contains("mac")) return;
        Toolkit.getDefaultToolkit().getSystemEventQueue().push(this);
        installed = true;
    }

    void setFullscreen(boolean fullscreen) {
        this.fullscreen = fullscreen;
    }

    void close() {
        fullscreen = false;
        frame.clear();
    }

    @Override protected void dispatchEvent(AWTEvent event) {
        JFrame target = frame.get();
        if (fullscreen && target != null && event instanceof MouseEvent mouse && mouse.getSource() == target) {
            int staleTitleBar = target instanceof FullscreenFrame fullscreenFrame
                ? fullscreenFrame.peerTitleBarInset() : target.getInsets().top;
            if (staleTitleBar > 0) mouse.translatePoint(0, staleTitleBar);
        }
        super.dispatchEvent(event);
    }
}
