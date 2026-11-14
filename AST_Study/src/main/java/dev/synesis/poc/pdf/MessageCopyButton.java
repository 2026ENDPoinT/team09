package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.awt.datatransfer.StringSelection;
import java.awt.geom.RoundRectangle2D;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Copies the original message, independently of rendered Markdown and metadata. */
final class MessageCopyButton extends JButton {
    private final float scale;

    MessageCopyButton(String label, Color color, Supplier<String> text, Consumer<String> failure) {
        this(label,color,text,failure,1f);
    }

    MessageCopyButton(String label, Color color, Supplier<String> text, Consumer<String> failure,float scale) {
        this.scale=scale;
        setToolTipText(label);
        getAccessibleContext().setAccessibleName(label);
        setForeground(color);
        int size=Math.round(24*scale);
        setPreferredSize(new Dimension(size,size));
        setBorder(BorderFactory.createEmptyBorder());
        setOpaque(false);setContentAreaFilled(false);setBorderPainted(false);setFocusPainted(false);
        setRolloverEnabled(true);setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        addActionListener(event->{
            String value=text.get();
            if(value==null||value.isBlank())return;
            try {
                Toolkit.getDefaultToolkit().getSystemClipboard().setContents(new StringSelection(value),null);
                setToolTipText("복사했어요");
            } catch(IllegalStateException | SecurityException unavailable) {
                failure.accept("클립보드를 잠시 사용할 수 없어요.");
            }
        });
    }

    @Override protected void paintComponent(Graphics graphics) {
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.translate((getWidth()-24*scale)/2d,(getHeight()-24*scale)/2d);
            g.scale(scale,scale);
            if(getModel().isRollover()||getModel().isPressed()||isFocusOwner()) {
                g.setColor(new Color(getForeground().getRed(),getForeground().getGreen(),getForeground().getBlue(),getModel().isPressed()?45:24));
                g.fillRoundRect(1,1,22,22,7,7);
            }
            g.setColor(getForeground());
            if(!isEnabled())g.setComposite(AlphaComposite.SrcOver.derive(.35f));
            g.setStroke(new BasicStroke(1.3f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.draw(new RoundRectangle2D.Double(9,8,9,11,2,2));
            g.drawLine(6,15,6,6);g.drawLine(6,6,14,6);
        } finally {g.dispose();}
    }
}
