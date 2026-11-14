package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import javax.swing.*;
import javax.swing.border.AbstractBorder;
import javax.swing.border.Border;
import javax.swing.plaf.BorderUIResource;
import javax.swing.plaf.ComponentUI;
import javax.swing.plaf.basic.BasicPopupMenuUI;
import javax.swing.plaf.basic.BasicSeparatorUI;

/** Shared surface for expanded selections and action menus. */
public final class RoundedPopupMenuUI extends BasicPopupMenuUI {
    public static final Color DIVIDER = new Color(0xe6e6e6);
    static final Border PADDING = new BorderUIResource.EmptyBorderUIResource(6, 6, 6, 6);
    private static final float OUTLINE = .3f;

    public static ComponentUI createUI(JComponent component) {
        return new RoundedPopupMenuUI();
    }

    @Override public void installDefaults() {
        super.installDefaults();
        LookAndFeel.installProperty(popupMenu, "opaque", false);
        if (popupMenu.getBorder() == null || popupMenu.getBorder() instanceof javax.swing.plaf.UIResource)
            popupMenu.setBorder(PADDING);
    }

    @Override public void paint(Graphics graphics, JComponent component) {
        paintSurface((Graphics2D) graphics, 0, 0, component.getWidth(), component.getHeight(), Color.WHITE);
    }

    public static void paintSurface(Graphics2D graphics, int x, int y, int width, int height, Color fill) {
        if (width <= 0 || height <= 0) return;
        Graphics2D g = (Graphics2D) graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            float inset = OUTLINE / 2;
            var surface = new RoundRectangle2D.Float(x + inset, y + inset, width - OUTLINE, height - OUTLINE, 12, 12);
            g.setColor(fill);
            g.fill(surface);
            g.setColor(Color.BLACK);
            g.setStroke(new BasicStroke(OUTLINE));
            g.draw(surface);
        } finally {
            g.dispose();
        }
    }

    @Override public Popup getPopup(JPopupMenu menu, int x, int y) {
        styleRows(menu);
        Popup popup = super.getPopup(menu, x, y);
        // A popup beyond its owner can be hosted in a separate Swing window.
        Window window = SwingUtilities.getWindowAncestor(menu);
        Component invoker = menu.getInvoker();
        if (window instanceof JWindow && (invoker == null || window != SwingUtilities.getWindowAncestor(invoker))
                && window.getGraphicsConfiguration().isTranslucencyCapable()) {
            window.setBackground(new Color(0, 0, 0, 0));
        }
        return popup;
    }

    private static void styleRows(JPopupMenu menu) {
        Component[] rows = menu.getComponents();
        boolean nextIsItem = false;
        for (int i = rows.length - 1; i >= 0; i--) {
            Component row = rows[i];
            if (!row.isVisible()) continue;
            if (row instanceof JMenuItem item) {
                item.setBackground(Color.WHITE);
                Border border = item.getBorder();
                if (border instanceof ItemDivider divider) {
                    divider.lineBelow = nextIsItem;
                } else {
                    item.setBorder(new ItemDivider(border, item.isBorderPainted(), nextIsItem));
                    item.setBorderPainted(true);
                }
            } else if (row instanceof JPopupMenu.Separator separator && !(separator.getUI() instanceof DividerUI)) {
                separator.setUI(new DividerUI());
            }
            nextIsItem = row instanceof JMenuItem;
        }
    }

    private static final class DividerUI extends BasicSeparatorUI {
        @Override public void paint(Graphics graphics, JComponent component) {
            graphics.setColor(DIVIDER);
            int y = component.getHeight() / 2;
            graphics.drawLine(0, y, component.getWidth() - 1, y);
        }
        @Override public Dimension getPreferredSize(JComponent component) {
            return new Dimension(0, 1);
        }
    }

    private static final class ItemDivider extends AbstractBorder {
        private final Border original;
        private final boolean painted;
        private boolean lineBelow;

        ItemDivider(Border original, boolean painted, boolean lineBelow) {
            this.original = original;
            this.painted = painted;
            this.lineBelow = lineBelow;
        }

        @Override public Insets getBorderInsets(Component component, Insets insets) {
            if (original == null) insets.set(0, 0, 0, 0);
            else {
                Insets previous = original.getBorderInsets(component);
                insets.set(previous.top, previous.left, previous.bottom, previous.right);
            }
            return insets;
        }

        @Override public void paintBorder(Component component, Graphics graphics, int x, int y, int width, int height) {
            if (painted && original != null) original.paintBorder(component, graphics, x, y, width, height);
            if (lineBelow) {
                graphics.setColor(DIVIDER);
                graphics.drawLine(x + 4, y + height - 1, x + width - 5, y + height - 1);
            }
            if (((JMenuItem) component).isArmed() && width > 4 && height > 4) {
                graphics.setColor(Color.GRAY);
                graphics.drawRoundRect(x + 1, y + 1, width - 3, height - 3, 6, 6);
            }
        }
    }
}
