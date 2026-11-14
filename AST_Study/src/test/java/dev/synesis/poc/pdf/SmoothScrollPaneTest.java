package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.SmoothScrollPane;
import javax.swing.JPanel;
import javax.swing.JScrollBar;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import java.awt.Dimension;
import java.awt.Toolkit;
import java.awt.event.MouseEvent;
import java.awt.event.MouseWheelEvent;

/** Wheel distance is preserved and applied without a delayed animation. */
final class SmoothScrollPaneTest {
    static void run() throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            JPanel longView = new JPanel();
            longView.setPreferredSize(new Dimension(150, 5000));
            SmoothScrollPane pane = new SmoothScrollPane(longView);
            pane.setSize(220, 180);
            pane.doLayout();
            JScrollBar bar = pane.getVerticalScrollBar();
            bar.setUnitIncrement(24);
            if (bar.getMaximum() - bar.getVisibleAmount() < 1000) throw new AssertionError("Long scroll area");
            wheel(pane, 2);
            if (bar.getValue() != 36) throw new AssertionError("First wheel movement must be immediate at PDF speed");
            wheel(pane, 1); // The second notch should extend the first movement.
            if (bar.getValue() != 54) throw new AssertionError("Shared PDF wheel distance changed");
            eventDelay(300);
            if (bar.getValue() != 54) throw new AssertionError("Delayed scroll animation remains");
            wheel(pane, 3);
            bar.setValue(700); // User drags scrollbar or a page-link changes the position.
            eventDelay(300);
            if (bar.getValue() != 700) throw new AssertionError("Direct navigation must cancel animation");
        });
    }

    private static void wheel(SmoothScrollPane pane, int rotation) {
        pane.dispatchEvent(new MouseWheelEvent(pane, MouseEvent.MOUSE_WHEEL,
            System.currentTimeMillis(), 0, 40, 40, 0, false,
            MouseWheelEvent.WHEEL_UNIT_SCROLL, 3, rotation));
    }

    private static void eventDelay(int milliseconds) {
        var loop = Toolkit.getDefaultToolkit().getSystemEventQueue().createSecondaryLoop();
        Timer wait = new Timer(milliseconds, event -> loop.exit());
        wait.setRepeats(false);
        wait.start();
        loop.enter();
    }
}
