package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.SmoothScrollPane;
import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.util.function.Consumer;
import javax.swing.*;
import javax.swing.text.BadLocationException;
import javax.swing.text.View;

/** One cached native document/viewport per explicitly highlighted formula group. */
final class SummaryFormulaGroup extends JPanel {
    private final StudyHtmlPane text=new StudyHtmlPane(true);
    private final JScrollPane scroll=new SmoothScrollPane(text) {
        @Override protected void processMouseWheelEvent(MouseWheelEvent event) {
            if(event.isShiftDown()) {
                super.processMouseWheelEvent(event);
                return;
            }
            JScrollPane outer=(JScrollPane)SwingUtilities.getAncestorOfClass(JScrollPane.class,this);
            if(outer==null) {super.processMouseWheelEvent(event);return;}
            Point point=SwingUtilities.convertPoint(this,event.getPoint(),outer);
            outer.dispatchEvent(new MouseWheelEvent(outer,event.getID(),event.getWhen(),event.getModifiersEx(),
                point.x,point.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),
                event.isPopupTrigger(),event.getScrollType(),event.getScrollAmount(),
                event.getWheelRotation(),event.getPreciseWheelRotation()));
            event.consume();
        }
    };
    private int measuredWidth=-1;
    private Dimension measured;
    private final boolean emphasized;
    private final boolean assistantDark;

    SummaryFormulaGroup(SummarySkin.FormulaGroup group,int font,Consumer<String> navigate) {
        this(group,font,navigate,null,null);
    }
    SummaryFormulaGroup(SummarySkin.FormulaGroup group,int font,Consumer<String> navigate,
                        String document,Consumer<JScrollPane> customizeScroll) {
        this(group,font,navigate,document,customizeScroll,false);
    }
    SummaryFormulaGroup(SummarySkin.FormulaGroup group,int font,Consumer<String> navigate,
                        String document,Consumer<JScrollPane> customizeScroll,boolean assistantDark) {
        super(new BorderLayout());
        this.assistantDark=assistantDark;
        emphasized=group.emphasized();
        setOpaque(false);
        setBorder(emphasized?BorderFactory.createEmptyBorder(16,16,16,16):BorderFactory.createEmptyBorder(4,0,8,0));
        Color background=assistantDark?(emphasized?AssistantChatTheme.CODE:AssistantChatTheme.SURFACE):emphasized?SummarySkin.SOFT:Color.WHITE;
        if(assistantDark)AssistantChatTheme.configure(text);
        text.setReadingSkin(true);text.setEditable(false);text.setBackground(background);
        text.setBorder(BorderFactory.createEmptyBorder());
        text.setText(document==null?SummarySkin.formulaDocument(group.body(),font):document);
        text.addHyperlinkListener(event->{
            if(event.getEventType()==javax.swing.event.HyperlinkEvent.EventType.ACTIVATED)
                navigate.accept(event.getDescription());
        });
        scroll.setBorder(BorderFactory.createEmptyBorder());
        scroll.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED);
        scroll.setVerticalScrollBarPolicy(JScrollPane.VERTICAL_SCROLLBAR_NEVER);
        scroll.getViewport().setBackground(background);
        scroll.getHorizontalScrollBar().setUnitIncrement(dev.synesis.poc.ui.ScrollPolicy.PIXELS_PER_UNIT);
        if(customizeScroll!=null)customizeScroll.accept(scroll);
        add(scroll,BorderLayout.CENTER);
    }

    StudyHtmlPane textPane(){return text;}

    @Override public Dimension getPreferredSize() {
        int width=Math.max(1,getWidth());
        if(measured!=null && measuredWidth==width)return new Dimension(measured);
        Insets insets=getInsets();int available=Math.max(1,width-insets.left-insets.right);
        text.setPreferredSize(null);
        // HTML BodyBlockView consults the viewport during layout. Set the new
        // extent before measuring, so a narrow previous width cannot leak through.
        scroll.getViewport().setExtentSize(new Dimension(available,Math.max(1,scroll.getViewport().getHeight())));
        View root=text.getUI().getRootView(text);
        int natural=Math.max(available,(int)Math.ceil(root.getMinimumSpan(View.X_AXIS))+4);
        text.setSize(natural,Short.MAX_VALUE);
        root.setSize(Math.max(1,natural-1),Short.MAX_VALUE);
        root.setSize(natural,Short.MAX_VALUE);
        try {text.modelToView2D(text.getDocument().getLength());}
        catch(BadLocationException ignored) {}
        int height=(int)Math.ceil(root.getPreferredSpan(View.Y_AXIS))+4;
        text.setPreferredSize(new Dimension(natural,height));
        int bar=natural>available?scroll.getHorizontalScrollBar().getPreferredSize().height:0;
        measuredWidth=width;measured=new Dimension(width,height+bar+insets.top+insets.bottom);
        return new Dimension(measured);
    }

    @Override protected void paintComponent(Graphics graphics) {
        if(!emphasized) {super.paintComponent(graphics);return;}
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setColor(assistantDark?AssistantChatTheme.CODE:SummarySkin.SOFT);g.fillRoundRect(0,0,getWidth()-1,getHeight()-1,16,16);
            g.setColor(assistantDark?AssistantChatTheme.LINE:SummarySkin.LINE);g.drawRoundRect(0,0,getWidth()-1,getHeight()-1,16,16);
        } finally {g.dispose();}
        super.paintComponent(graphics);
    }
}
