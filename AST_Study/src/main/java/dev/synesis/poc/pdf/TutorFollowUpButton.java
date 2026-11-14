package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import java.awt.*;
import javax.swing.*;
import javax.swing.border.EmptyBorder;

/** Clickable, width-aware question using the same vector math renderer as tutor prose. */
final class TutorFollowUpButton extends JButton {
    private final String question;
    private final Icon arrow;
    private final StudyHtmlPane label = new StudyHtmlPane(true);
    private Font measuredFont;
    private int measuredWidth = -1;
    private int naturalWidth;
    private float textHeight;

    TutorFollowUpButton(String question, int availableWidth) {
        // The native button paints its usual chrome; the full label is painted below.
        this.question = question;
        arrow = MistWorkspaceTheme.icon("arrow", 12);
        MistWorkspaceTheme.button(this, true);
        label.setEditable(false);
        label.setFocusable(false);
        label.setOpaque(false);
        label.setBorder(null);
        label.setMargin(new Insets(0,0,0,0));
        setBorder(new EmptyBorder(6, 12, 6, 36));
        setAlignmentX(Component.LEFT_ALIGNMENT);
        setActionCommand(question);
        setToolTipText(question);
        getAccessibleContext().setAccessibleName(question);
        reflowWidth(availableWidth);
    }

    void reflowWidth(int availableWidth) {
        Font font = getFont();
        FontMetrics metrics = getFontMetrics(font);
        Insets padding = getInsets();
        boolean fontChanged = !font.equals(measuredFont);
        if (fontChanged) {
            naturalWidth = metrics.stringWidth(question) + padding.left + padding.right;
            label.setFont(font);
            label.setText("<html><head><style>body{margin:0;font-family:'"+font.getFamily()
                +"';font-size:"+font.getSize()+"pt;color:#45474c;}p{margin:0;}"
                +"</style></head><body>"+StudyMarkdown.render(question,font.getSize())+"</body></html>");
        }
        int width = Math.max(1, Math.min(availableWidth, Math.max(160, naturalWidth)));
        int textWidth = Math.max(1, width - padding.left - padding.right);
        if (textWidth == measuredWidth && !fontChanged) return;
        measuredWidth = textWidth;
        measuredFont = font;
        label.setSize(textWidth, Short.MAX_VALUE);
        textHeight = label.getPreferredSize().height;
        label.setSize(textWidth,(int)Math.ceil(textHeight));
        int height = Math.max(28, (int) Math.ceil(textHeight) + padding.top + padding.bottom);
        setPreferredSize(new Dimension(width, height));
        setMinimumSize(new Dimension(0, height));
        setMaximumSize(new Dimension(width, height));
        revalidate();
        repaint();
    }

    @Override protected void paintComponent(Graphics graphics) {
        super.paintComponent(graphics);
        Graphics2D g = (Graphics2D) graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
            Graphics2D textGraphics=(Graphics2D)g.create(getInsets().left,
                Math.max(0,(getHeight()-label.getHeight())/2),label.getWidth(),label.getHeight());
            try {
                if(!isEnabled())textGraphics.setComposite(AlphaComposite.SrcOver.derive(.55f));
                label.paint(textGraphics);
            } finally {textGraphics.dispose();}
            arrow.paintIcon(this, g, getWidth() - 24, (getHeight() - 12) / 2);
        } finally {
            g.dispose();
        }
    }
}
