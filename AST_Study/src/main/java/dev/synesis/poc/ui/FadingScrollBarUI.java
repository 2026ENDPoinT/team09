package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.plaf.ComponentUI;
import javax.swing.plaf.basic.BasicScrollBarUI;
import java.awt.*;
import java.awt.event.AdjustmentListener;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;

/** A scroll thumb that appears during movement and fades after the user stops. */
public final class FadingScrollBarUI extends BasicScrollBarUI {
    private static final int FADE_IN_MS = 100;
    private static final int IDLE_MS = 300;
    private static final int FADE_OUT_MS = 500;
    private final Color thumbColor;
    private final float idleOpacity;

    private float opacity;
    private float fromOpacity;
    private float targetOpacity;
    private long transitionStarted;
    private int transitionDuration;
    private Timer transition;
    private Timer idle;
    private AdjustmentListener adjustment;
    private MouseAdapter mouse;
    private boolean dragging;
    private boolean hovered;
    private boolean idleReady;

    public FadingScrollBarUI() { this(Color.BLACK,0f); }

    public FadingScrollBarUI(Color thumbColor,float idleOpacity) {
        this.thumbColor=thumbColor;
        this.idleOpacity=Math.max(0f,Math.min(1f,idleOpacity));
        opacity=this.idleOpacity;targetOpacity=this.idleOpacity;
    }

    public static ComponentUI createUI(JComponent component) {
        return new FadingScrollBarUI();
    }

    @Override public void installUI(JComponent component) {
        super.installUI(component);
        scrollbar.setOpaque(false);
        transition = new Timer(16, event -> advance());
        idle = new Timer(IDLE_MS, event -> {
            idle.stop();
            idleReady = true;
            if (!dragging && !hovered && !(transition.isRunning() && targetOpacity == 1f))
                animateTo(idleOpacity, FADE_OUT_MS);
        });
        idle.setRepeats(false);
        adjustment = event -> activity();
        scrollbar.addAdjustmentListener(adjustment);
        mouse = new MouseAdapter() {
            @Override public void mouseEntered(MouseEvent event) {
                hovered = true;
                activity();
            }
            @Override public void mouseExited(MouseEvent event) {
                hovered = false;
                if (!dragging) idle.restart();
            }
            @Override public void mousePressed(MouseEvent event) {
                dragging = true;
                idleReady = false;
                idle.stop();
                animateTo(1f, FADE_IN_MS);
            }
            @Override public void mouseReleased(MouseEvent event) {
                dragging = false;
                if (!hovered) idle.restart();
            }
        };
        scrollbar.addMouseListener(mouse);
    }

    @Override public void uninstallUI(JComponent component) {
        if (transition != null) transition.stop();
        if (idle != null) idle.stop();
        if (adjustment != null) scrollbar.removeAdjustmentListener(adjustment);
        if (mouse != null) scrollbar.removeMouseListener(mouse);
        super.uninstallUI(component);
    }

    private void activity() {
        idleReady = false;
        if (targetOpacity != 1f || opacity < 1f && !transition.isRunning())
            animateTo(1f, FADE_IN_MS);
        if (hovered || dragging) idle.stop();
        else idle.restart();
    }

    private void animateTo(float target, int milliseconds) {
        if (opacity == target) {
            targetOpacity = target;
            transition.stop();
            return;
        }
        fromOpacity = opacity;
        targetOpacity = target;
        transitionDuration = milliseconds;
        transitionStarted = System.nanoTime();
        transition.start();
        repaintThumb();
    }

    private void advance() {
        float fraction = (float) Math.min(1d,
            (System.nanoTime() - transitionStarted) / (transitionDuration * 1_000_000d));
        opacity = fromOpacity + (targetOpacity - fromOpacity) * fraction;
        repaintThumb();
        if (fraction >= 1f) {
            transition.stop();
            if (targetOpacity == 1f && idleReady && !dragging && !hovered)
                animateTo(idleOpacity, FADE_OUT_MS);
        }
    }

    @Override protected JButton createDecreaseButton(int orientation) { return hiddenButton(); }
    private void repaintThumb(){
        ScrollCacheViewport.invalidateContent(scrollbar);
        Rectangle damage=new Rectangle(thumbRect);damage.grow(2,2);
        if(!thumbRect.isEmpty())scrollbar.repaint(damage);
    }
    @Override protected JButton createIncreaseButton(int orientation) { return hiddenButton(); }

    @Override public Dimension getPreferredSize(JComponent component) {
        Dimension size = super.getPreferredSize(component);
        if (scrollbar.getOrientation() == JScrollBar.VERTICAL)
            size.width = Math.max(6, Math.round(size.width * .6f));
        else
            size.height = Math.max(6, Math.round(size.height * .6f));
        return size;
    }

    private static JButton hiddenButton() {
        JButton button = new JButton();
        button.setPreferredSize(new Dimension(0, 0));
        button.setMinimumSize(new Dimension(0, 0));
        button.setMaximumSize(new Dimension(0, 0));
        button.setVisible(false);
        return button;
    }

    @Override protected void paintTrack(Graphics graphics, JComponent component, Rectangle bounds) {
        // Keep the scrollable area and hit target, but leave its track transparent.
    }

    @Override protected void paintThumb(Graphics graphics, JComponent component, Rectangle bounds) {
        if (opacity <= 0f || bounds.isEmpty() || !scrollbar.isEnabled()) return;
        Graphics2D g = (Graphics2D) graphics.create();
        try {
            g.setComposite(AlphaComposite.SrcOver.derive(opacity));
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.setColor(thumbColor);
            int inset = 2;
            int x = bounds.x + (scrollbar.getOrientation() == JScrollBar.VERTICAL ? inset : 1);
            int y = bounds.y + (scrollbar.getOrientation() == JScrollBar.HORIZONTAL ? inset : 1);
            int width = Math.max(1, bounds.width - (scrollbar.getOrientation() == JScrollBar.VERTICAL ? inset * 2 : 2));
            int height = Math.max(1, bounds.height - (scrollbar.getOrientation() == JScrollBar.HORIZONTAL ? inset * 2 : 2));
            g.fillRoundRect(x, y, width, height, Math.min(width, 10), Math.min(height, 10));
            if(Color.WHITE.equals(thumbColor)) {
                // A subtle contour keeps the white thumb visible on the white chat gutter.
                g.setComposite(AlphaComposite.SrcOver.derive(opacity*.45f));
                g.setColor(new Color(0x8b929e));
                g.drawRoundRect(x,y,Math.max(0,width-1),Math.max(0,height-1),Math.min(width,10),Math.min(height,10));
            }
        } finally {
            g.dispose();
        }
    }
}
