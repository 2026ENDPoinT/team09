package dev.synesis.poc.pdf;

import java.awt.*;
import javax.swing.text.Element;
import javax.swing.text.html.InlineView;

/** Native inline text keeps selection, copying and wrapping; only its paper is rounded. */
final class StudyInlineCode extends InlineView {
    StudyInlineCode(Element element) { super(element); }

    @Override public Color getBackground() { return null; }
    @Override public Color getForeground(){
        Color color=super.getForeground();
        return getContainer() instanceof javax.swing.JComponent c&&Boolean.TRUE.equals(c.getClientProperty("synesis.assistantDark"))
            ?AssistantChatTheme.TEXT:color;
    }

    @Override public void paint(Graphics graphics,Shape allocation) {
        Graphics2D g=(Graphics2D)graphics.create();
        Rectangle r=allocation.getBounds();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            boolean assistantDark=getContainer() instanceof javax.swing.JComponent c
                && Boolean.TRUE.equals(c.getClientProperty("synesis.assistantDark"));
            g.setColor(assistantDark?AssistantChatTheme.INLINE_CODE:Color.decode(StudyCodeBlock.INLINE_BACKGROUND));
            Shape paper=new java.awt.geom.RoundRectangle2D.Float(
                r.x+.05f,r.y+.05f,Math.max(0,r.width-.1f),Math.max(0,r.height-.1f),7,7);
            g.fill(paper);
            g.setColor(assistantDark?AssistantChatTheme.INLINE_CODE:new Color(0x8e8e8e));
            g.setStroke(new BasicStroke(.1f));
            g.draw(paper);
        } finally {g.dispose();}
        super.paint(graphics,allocation);
    }
}
