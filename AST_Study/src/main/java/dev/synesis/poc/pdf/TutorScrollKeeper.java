package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import javax.swing.*;

/** One scroll owner for chat rebuilds, streaming and bubble-size animation (EDT only). */
final class TutorScrollKeeper {
    static final String ANCHOR="synesis.tutorScrollAnchor";
    private static final String OWNER="synesis.tutorScrollKeeper";
    private final JScrollPane scroll;
    private final JPanel content;
    private long interaction;
    private Position pending;
    private boolean queued,closed;
    private boolean manualScroll,mayResumeAtEnd;

    record Position(String anchor,int offset,int y,boolean followEnd,long interaction) {}

    TutorScrollKeeper(JScrollPane scroll,JPanel content) {
        this.scroll=scroll;this.content=content;
        scroll.putClientProperty(OWNER,this);
        JScrollBar bar=scroll.getVerticalScrollBar();
        bar.addMouseListener(new MouseAdapter(){
            @Override public void mousePressed(MouseEvent e){userInput();}
        });
        bar.addAdjustmentListener(e->{if(e.getValueIsAdjusting())userInput();});
        bar.addKeyListener(new KeyAdapter(){
            @Override public void keyPressed(KeyEvent e){userInput();}
        });
        scroll.addKeyListener(new KeyAdapter(){
            @Override public void keyPressed(KeyEvent e){userInput();}
        });
    }

    static TutorScrollKeeper owner(Component component) {
        for(Component at=component;at!=null;at=at.getParent())
            if(at instanceof JComponent view && view.getClientProperty(OWNER) instanceof TutorScrollKeeper keeper)
                return keeper;
        return null;
    }

    void userInput() {interaction++;pending=null;manualScroll=true;mayResumeAtEnd=true;}

    void wheelInput(double rotation) {
        if(!Double.isFinite(rotation) || rotation==0)return;
        userInput();
        // Upward subpixel input is still intent to read. It must detach even
        // before enough fractional travel has accumulated to move one pixel.
        mayResumeAtEnd=rotation>0;
    }

    Position capture(boolean forceEnd) {
        if(forceEnd){manualScroll=false;mayResumeAtEnd=false;}
        // Repeated changes before the next layout must not capture its temporary zero position.
        if(!forceEnd && pending!=null && pending.interaction()==interaction)return pending;
        JViewport viewport=scroll.getViewport();
        int y=viewport.getViewPosition().y;
        int maximum=Math.max(0,viewport.getViewSize().height-viewport.getExtentSize().height);
        String anchor=null;int offset=0;
        for(Component child:content.getComponents()) {
            if(!(child instanceof JComponent view) || !(view.getClientProperty(ANCHOR) instanceof String key))continue;
            if(anchor!=null && child.getY()>y)break;
            anchor=key;offset=y-child.getY();
        }
        boolean followEnd=forceEnd || (manualScroll?mayResumeAtEnd && y>=maximum:y>=maximum-48);
        return new Position(anchor,offset,y,followEnd,interaction);
    }

    void restore(Position position) {
        if(closed || position.interaction()!=interaction)return;
        pending=position;
        if(queued)return;
        queued=true;
        SwingUtilities.invokeLater(this::applyPending);
    }

    private void applyPending() {
        queued=false;
        Position position=pending;pending=null;
        if(closed || position==null || position.interaction()!=interaction)return;
        JViewport viewport=scroll.getViewport();
        if(viewport.getView()!=content)return;
        // Scrollbar maximum can still describe the old/empty layout after removeAll().
        // Lay out the measured content first and use its actual height instead.
        Dimension size=new Dimension(Math.max(1,viewport.getExtentSize().width),content.getPreferredSize().height);
        viewport.setViewSize(size);content.doLayout();
        int maximum=Math.max(0,size.height-viewport.getExtentSize().height);
        int y=position.y();
        if(position.anchor()!=null)
            for(Component child:content.getComponents())
                if(child instanceof JComponent view && position.anchor().equals(view.getClientProperty(ANCHOR))) {
                    y=child.getY()+position.offset();break;
                }
        viewport.setViewPosition(new Point(viewport.getViewPosition().x,
            position.followEnd()?maximum:Math.max(0,Math.min(y,maximum))));
    }

    void close(){closed=true;pending=null;}
}
