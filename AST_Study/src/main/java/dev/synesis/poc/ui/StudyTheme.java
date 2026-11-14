package dev.synesis.poc.ui;

import dev.synesis.poc.UiFonts;

import javax.swing.*;
import javax.swing.border.AbstractBorder;
import javax.swing.border.EmptyBorder;
import javax.swing.plaf.basic.BasicButtonUI;
import java.awt.*;

/** Shared colors and native Swing surfaces from the Lecture Study Workspace design. */
public final class StudyTheme {
    public static final Color PAPER = Color.WHITE;
    public static final Color CANVAS = Color.WHITE;
    public static final Color SURFACE = new Color(0xfafaf8);
    public static final Color LINE = new Color(0xdfe3e8);
    public static final Color INK = new Color(0x182234);
    public static final Color MUTED = new Color(0x6d7785);
    public static final Color ACCENT = new Color(0x76243d);
    public static final Color ACCENT_DARK = new Color(0x58182d);
    public static final Color ACCENT_SOFT = new Color(0xf4e9ed);
    public static final Color WARM = new Color(0xeeeae3);
    public static final Color ALERT = new Color(0xd45151);
    private static final java.util.concurrent.ConcurrentMap<Integer,Font> FONTS=new java.util.concurrent.ConcurrentHashMap<>();

    private StudyTheme() {}

    public static Font font(int style, int size) {
        if(size<1 || size>128 || style<0 || style>3)return new Font(UiFonts.FAMILY,style,size);
        return FONTS.computeIfAbsent(size*4+(style&3),key->new Font(UiFonts.FAMILY,style,size));
    }

    public static RoundedPanel panel(int radius, Color fill) {
        return new RoundedPanel(new BorderLayout(), radius, fill, LINE);
    }

    public static void button(AbstractButton button, boolean primary) {
        button(button,primary?ACCENT:PAPER,primary?PAPER:INK,primary?ACCENT:LINE);
    }

    public static void darkButton(AbstractButton button) { button(button,INK,PAPER,INK); }

    public static void comboBox(JComboBox<String> combo) {
        combo.setUI(new PlainComboBoxUI() {
            @Override protected JButton createArrowButton() {
                JButton arrow = new JButton() {
                    @Override protected void paintComponent(Graphics graphics) {
                        Graphics2D g=(Graphics2D)graphics.create();
                        try {
                            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                            g.setColor(combo.isEnabled()?MUTED:LINE);
                            int x=getWidth()/2, y=getHeight()/2;
                            g.drawLine(x-4,y-2,x,y+2);
                            g.drawLine(x,y+2,x+4,y-2);
                        } finally {g.dispose();}
                    }
                };
                arrow.setPreferredSize(new Dimension(26,34));
                arrow.setOpaque(false);
                arrow.setContentAreaFilled(false);
                arrow.setBorderPainted(false);
                arrow.setFocusable(false);
                return arrow;
            }
        });
        DefaultListCellRenderer renderer=new DefaultListCellRenderer();
        combo.setRenderer((list,value,index,selected,focused)->{
            JLabel label=(JLabel)renderer.getListCellRendererComponent(list,value,index,selected,focused);
            label.setFont(font(Font.PLAIN,13));
            label.setVerticalAlignment(SwingConstants.CENTER);
            label.setBorder(new EmptyBorder(2,10,2,4));
            if(index<0) {
                label.setBackground(PAPER);
                label.setForeground(combo.isEnabled()?INK:MUTED);
            }
            return label;
        });
        combo.setFont(font(Font.PLAIN,13));
        combo.setBackground(PAPER);
        combo.setForeground(INK);
        combo.setBorder(new RoundBorder(8,3));
        combo.setOpaque(true);
    }

    private static void button(AbstractButton button,Color fill,Color foreground,Color outline) {
        boolean colored=!PAPER.equals(fill);
        button.setUI(new BasicButtonUI() {
            @Override public void paint(Graphics graphics, JComponent component) {
                Graphics2D g = (Graphics2D) graphics.create();
                try {
                    g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                    Color background = button.getModel().isPressed()
                        ? (colored ? fill.darker() : ACCENT_SOFT)
                        : button.getModel().isRollover() ? (colored ? fill.darker() : SURFACE) : fill;
                    g.setColor(background);
                    g.fillRoundRect(0, 0, component.getWidth()-1, component.getHeight()-1, 16, 16);
                    g.setColor(outline);
                    g.drawRoundRect(0, 0, component.getWidth()-1, component.getHeight()-1, 16, 16);
                } finally { g.dispose(); }
                super.paint(graphics, component);
            }
        });
        button.setOpaque(false);
        button.setContentAreaFilled(false);
        button.setBorder(new EmptyBorder(9, 16, 9, 16));
        button.setFont(font(Font.PLAIN, 13));
        button.setForeground(foreground);
        button.setFocusPainted(false);
        button.setRolloverEnabled(true);
        button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
    }

    public static final class RoundBorder extends AbstractBorder {
        private final int radius, padding;
        public RoundBorder(int radius, int padding) { this.radius = radius; this.padding = padding; }
        @Override public Insets getBorderInsets(Component component) {
            return new Insets(padding, padding, padding, padding);
        }
        @Override public Insets getBorderInsets(Component component, Insets insets) {
            insets.set(padding, padding, padding, padding); return insets;
        }
        @Override public void paintBorder(Component component, Graphics graphics, int x, int y, int width, int height) {
            Graphics2D g = (Graphics2D) graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(LINE);
                g.drawRoundRect(x, y, width-1, height-1, radius, radius);
            } finally { g.dispose(); }
        }
    }

    public static class RoundedPanel extends JPanel {
        private final int radius;
        private final Color fill;
        private Color outline;
        public RoundedPanel(LayoutManager layout, int radius, Color fill, Color outline) {
            super(layout); this.radius = radius; this.fill = fill; this.outline = outline;
            setOpaque(false);
        }
        public void setOutline(Color color) { outline = color; repaint(); }
        @Override protected void paintComponent(Graphics graphics) {
            Graphics2D g = (Graphics2D) graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(fill);
                Rectangle damage=g.getClipBounds();
                var shape=new java.awt.geom.RoundRectangle2D.Double(0,0,getWidth()-1,getHeight()-1,radius,radius);
                if(damage!=null&&shape.contains(damage))g.fillRect(damage.x,damage.y,damage.width,damage.height);
                else g.fillRoundRect(0, 0, getWidth()-1, getHeight()-1, radius, radius);
            } finally { g.dispose(); }
            super.paintComponent(graphics);
        }
        @Override protected void paintBorder(Graphics graphics) { }
        @Override public void paint(Graphics graphics) {
            super.paint(graphics);
            if (outline == null) return;
            Rectangle damage=graphics.getClipBounds();
            if(damage!=null&&new java.awt.geom.RoundRectangle2D.Double(3,3,getWidth()-6,getHeight()-6,
                    Math.max(0,radius-6),Math.max(0,radius-6)).contains(damage))return;
            Graphics2D g = (Graphics2D) graphics.create();
            try {
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(outline);
                if(ACCENT.equals(outline))g.setStroke(new BasicStroke(2f));
                g.drawRoundRect(0, 0, getWidth()-1, getHeight()-1, radius, radius);
            } finally { g.dispose(); }
        }
    }
}
