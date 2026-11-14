package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import java.awt.*;
import java.awt.geom.RoundRectangle2D;

/** One short-lived paint timer for tab ink and its travelling underline. */
public final class StudyTabStrip extends JPanel {
    private static final long DURATION = 190_000_000L;
    private final Timer motion = new Timer(16, event -> advance());
    private Tab selected;
    private long started;
    private double left, right, fromLeft, fromRight;
    private float opacity, fromOpacity;
    private boolean pending;

    public StudyTabStrip() {
        super(new FlowLayout(FlowLayout.LEFT, 4, 0));
        setBackground(Color.WHITE);
        motion.setCoalesce(true);
    }

    private void selectionChanged() {
        if (pending) return;
        pending = true;
        SwingUtilities.invokeLater(() -> {
            pending = false;
            if (motion.isRunning()) advance();
            selected = selectedTab();
            fromLeft = left; fromRight = right; fromOpacity = opacity;
            for (Component child : getComponents()) if (child instanceof Tab tab) tab.fromInk = tab.ink;
            if (!isShowing() || right <= left) { snap(); return; }
            started = System.nanoTime();
            motion.restart();
        });
    }

    private Tab selectedTab() {
        for (Component child : getComponents()) if (child instanceof Tab tab && tab.isSelected() && tab.isVisible()) return tab;
        return null;
    }

    private void snap() {
        Tab previous=selected;double oldLeft=left,oldRight=right;float oldOpacity=opacity;
        motion.stop(); selected = selectedTab();
        if (selected != null) {
            left = selected.getX() + (selected.getWidth() - 40) / 2d;
            right = left + 40;
        }
        opacity = selected == null ? 0 : 1;
        for (Component child : getComponents()) if (child instanceof Tab tab) tab.setInk(tab == selected ? 1 : 0);
        if(previous!=selected||oldLeft!=left||oldRight!=right||oldOpacity!=opacity)repaint();
    }

    private void advance() {
        if (!isShowing()) { snap(); return; }
        double t = Math.min(1, (System.nanoTime() - started) / (double) DURATION);
        double smooth = t * t * (3 - 2 * t);
        double remaining = 1 - t;
        double quick = 1 - remaining * remaining * remaining;
        if (selected != null) {
            double target = selected.getX() + (selected.getWidth() - 40) / 2d;
            double fromCenter = (fromLeft + fromRight) / 2;
            double distance = target + 20 - fromCenter;
            // Fast takeoff with a small, single elastic settle; no spring simulation.
            double q = t - 1;
            double settle = 1 + 1.45 * q * q * q + .45 * q * q;
            double center = fromCenter + distance * settle;
            double pulse = 4 * t * (1 - t);
            double width = (fromRight - fromLeft) + (40 - (fromRight - fromLeft)) * quick
                + Math.min(10, Math.abs(distance) * .08) * pulse * pulse;
            left = center - width / 2;
            right = center + width / 2;
        }
        opacity = (float) (fromOpacity + ((selected == null ? 0 : 1) - fromOpacity) * smooth);
        for (Component child : getComponents()) if (child instanceof Tab tab)
            tab.setInk((float) (tab.fromInk + ((tab == selected ? 1 : 0) - tab.fromInk) * smooth));
        // Only this small header strip is dirty; no document layout or bitmap capture.
        repaint();
        if (t >= 1) motion.stop();
    }

    @Override public void doLayout() {
        super.doLayout();
        if (!motion.isRunning()) snap();
    }

    @Override protected void paintChildren(Graphics graphics) {
        super.paintChildren(graphics);
        if (opacity <= 0 || right <= left) return;
        Graphics2D g = (Graphics2D) graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setComposite(AlphaComposite.SrcOver.derive(opacity));
            g.setColor(MistWorkspaceTheme.INK);
            int bottom = selected == null ? 40 : selected.getY() + selected.getHeight();
            g.fill(new RoundRectangle2D.Double(left, bottom - 2, right - left, 2, 2, 2));
        } finally { g.dispose(); }
    }

    @Override public void removeNotify() { motion.stop(); super.removeNotify(); }

    public static class Tab extends JToggleButton {
        private float ink=Float.NaN, fromInk;
        public Tab(String title) {
            super(title);
            setOpaque(false); setContentAreaFilled(false); setBorder(new EmptyBorder(0,12,0,12));
            setPreferredSize(new Dimension(88,40)); setFocusPainted(false); setRolloverEnabled(true);
            setFont(LibraryDesign.medium(14)); putClientProperty("synesis.preserveFont",true);
            setInk(0);
            addItemListener(event -> {
                if (getParent() instanceof StudyTabStrip strip) strip.selectionChanged();
                else setInk(isSelected() ? 1 : 0);
            });
        }
        private void setInk(float value) {
            if(ink==value)return;
            ink = value;
            Color muted = new Color(0x323337), active = MistWorkspaceTheme.INK;
            setForeground(new Color(
                Math.round(muted.getRed() + (active.getRed() - muted.getRed()) * value),
                Math.round(muted.getGreen() + (active.getGreen() - muted.getGreen()) * value),
                Math.round(muted.getBlue() + (active.getBlue() - muted.getBlue()) * value)));
        }
    }
}
