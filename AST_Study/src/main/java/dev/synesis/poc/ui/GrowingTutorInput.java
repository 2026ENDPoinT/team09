package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.border.EmptyBorder;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;
import java.awt.*;
import java.awt.event.ComponentAdapter;
import java.awt.event.ComponentEvent;
import java.awt.event.ContainerAdapter;
import java.awt.event.ContainerEvent;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import javax.swing.text.View;

/** Bottom-anchored composer: one to four wrapped lines plus the existing attachment strip. */
public final class GrowingTutorInput extends MistWorkspaceTheme.Panel {
    private static final int GAP=8,MIN_TEXT_HEIGHT=36;
    private final JTextArea text;
    private final JScrollPane scroll;
    private final JPanel attachments,actions;
    private final Timer animation=new Timer(16,event->animate());
    private double height=96;
    private int targetHeight=96,textHeight=MIN_TEXT_HEIGHT,attachmentHeight;
    private long lastFrame;
    private boolean queued,disposed;
    private long textRevision,measuredRevision=-1;
    private int measuredWidth=-1,lastWidth=-1,lastViewportWidth=-1;
    private Font measuredFont;

    public GrowingTutorInput(JTextArea text,JScrollPane scroll,JPanel attachments,JPanel actions){
        this(text,scroll,attachments,actions,Color.WHITE,MistWorkspaceTheme.LINE);
    }
    public GrowingTutorInput(JTextArea text,JScrollPane scroll,JPanel attachments,JPanel actions,Color fill,Color outline){
        super(null,12,fill,outline);
        this.text=text;this.scroll=scroll;this.attachments=attachments;this.actions=actions;
        putClientProperty("mist.shadow","input");setBorder(new EmptyBorder(12,12,12,12));
        add(attachments);add(scroll);add(actions);
        text.getDocument().addDocumentListener(new DocumentListener(){
            public void insertUpdate(DocumentEvent event){textRevision++;refresh();}
            public void removeUpdate(DocumentEvent event){textRevision++;refresh();}
            public void changedUpdate(DocumentEvent event){textRevision++;refresh();}
        });
        text.addPropertyChangeListener("font",event->refresh());
        addComponentListener(new ComponentAdapter(){
            @Override public void componentResized(ComponentEvent event){
                int width=getWidth();if(width!=lastWidth){lastWidth=width;refresh();}
            }
        });
        scroll.getViewport().addComponentListener(new ComponentAdapter(){
            @Override public void componentResized(ComponentEvent event){
                int width=scroll.getViewport().getWidth();
                if(width!=lastViewportWidth){lastViewportWidth=width;refresh();}
            }
        });
        focusOnBlankSpace(this,text);
    }

    /** Coalesce paste/remove/document events before calculating their final height. */
    public void refresh(){
        if(queued||disposed)return;
        queued=true;SwingUtilities.invokeLater(()->{
            queued=false;if(disposed)return;
            if(measure()){revalidate();repaint();}
        });
    }
    private boolean measure(){
        int previousTextHeight=textHeight,previousAttachmentHeight=attachmentHeight;
        Insets padding=getInsets(),textInsets=text.getInsets();
        int width=Math.max(80,getWidth()-padding.left-padding.right-textInsets.left-textInsets.right);
        if(scroll.getVerticalScrollBar().isVisible())width-=scroll.getVerticalScrollBar().getPreferredSize().width;
        // A height-only animation does not change wrapping. Reuse the measured text height.
        if(measuredRevision!=textRevision||measuredWidth!=width||!text.getFont().equals(measuredFont)){
            View view=text.getUI().getRootView(text);
            view.setSize(Math.max(1,width),Float.MAX_VALUE);
            int natural=(int)Math.ceil(view.getPreferredSpan(View.Y_AXIS))+textInsets.top+textInsets.bottom;
            int line=text.getFontMetrics(text.getFont()).getHeight();
            textHeight=Math.max(MIN_TEXT_HEIGHT,Math.min(line*4+textInsets.top+textInsets.bottom,natural));
            measuredRevision=textRevision;measuredWidth=width;measuredFont=text.getFont();
        }
        attachmentHeight=attachments.isVisible()?attachments.getPreferredSize().height:0;
        int next=padding.top+padding.bottom+textHeight+GAP+actions.getPreferredSize().height
            +(attachmentHeight>0?attachmentHeight+GAP:0);
        if(next==targetHeight)return textHeight!=previousTextHeight||attachmentHeight!=previousAttachmentHeight;
        targetHeight=next;
        if(!isShowing()||getWidth()<=0){height=next;animation.stop();}
        else if(!animation.isRunning()){lastFrame=System.nanoTime();animation.start();}
        return true;
    }
    private void animate(){
        long now=System.nanoTime();double elapsed=(now-lastFrame)/1_000_000_000d;lastFrame=now;
        int previousHeight=(int)Math.round(height);
        height+=(targetHeight-height)*(1-Math.exp(-elapsed/.055));
        if(Math.abs(targetHeight-height)<.5){height=targetHeight;animation.stop();}
        if(previousHeight!=(int)Math.round(height)){revalidate();repaint();}
    }
    @Override public Dimension getPreferredSize(){return new Dimension(240,(int)Math.round(height));}
    @Override public Dimension getMinimumSize(){return new Dimension(0,96);}
    @Override public void doLayout(){
        Insets padding=getInsets();int width=Math.max(0,getWidth()-padding.left-padding.right);
        int actionHeight=actions.getPreferredSize().height;
        int actionY=getHeight()-padding.bottom-actionHeight;
        actions.setBounds(padding.left,actionY,width,actionHeight);
        int textY=actionY-GAP-textHeight;
        scroll.setBounds(padding.left,textY,width,textHeight);
        attachments.setBounds(padding.left,textY-GAP-attachmentHeight,width,attachmentHeight);
    }
    public void dispose(){disposed=true;animation.stop();}
    @Override public void removeNotify(){animation.stop();height=targetHeight;super.removeNotify();}

    /** Extend focus across blank composer space, while preserving all real controls. */
    public static void focusOnBlankSpace(Component component,JTextArea text){
        if(component instanceof AbstractButton||component instanceof JComboBox<?>||component instanceof JScrollBar){
            if(!component.isCursorSet())component.setCursor(Cursor.getDefaultCursor());
            return;
        }
        if(component instanceof javax.swing.text.JTextComponent)return;
        if(component==text)return;
        // Install once, including components added later (for example attachment rows).
        if(component instanceof JComponent jc){
            if(jc.getClientProperty("synesis.composerFocus")==text)return;
            jc.putClientProperty("synesis.composerFocus",text);
        }
        component.setCursor(Cursor.getPredefinedCursor(Cursor.TEXT_CURSOR));
        component.addMouseListener(new MouseAdapter(){
            @Override public void mousePressed(MouseEvent event){
                if(!SwingUtilities.isLeftMouseButton(event)||event.isConsumed())return;
                // Finish the clicked container's focus handling and window activation first.
                SwingUtilities.invokeLater(()->{
                    if(!text.isShowing()||!text.isEnabled()||!text.isEditable())return;
                    if(!text.requestFocusInWindow())text.requestFocus();
                });
            }
        });
        if(component instanceof Container parent){
            for(Component child:parent.getComponents())focusOnBlankSpace(child,text);
            parent.addContainerListener(new ContainerAdapter(){
                @Override public void componentAdded(ContainerEvent event){focusOnBlankSpace(event.getChild(),text);}
            });
        }
    }
}
