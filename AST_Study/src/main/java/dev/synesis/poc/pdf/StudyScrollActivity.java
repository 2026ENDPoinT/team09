package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.UnifiedScrollPane;
import java.awt.event.*;
import java.util.function.Consumer;
import javax.swing.*;
import javax.swing.event.ChangeListener;

/** Pauses decorative height motion during direct scrolling, without delaying the scroll input. */
final class StudyScrollActivity implements AutoCloseable {
    private static final int QUIET_MILLIS=180;
    private final JScrollPane scroll;
    private final Consumer<Boolean> changed;
    private final Timer idle=new Timer(QUIET_MILLIS,e->settle());
    private boolean active,pressed,closed;
    private final MouseWheelListener wheel=e->pulse();
    private final MouseAdapter mouse=new MouseAdapter(){
        @Override public void mousePressed(MouseEvent e){pressed=true;pulse();}
        @Override public void mouseReleased(MouseEvent e){pressed=false;pulse();}
    };
    private final KeyAdapter key=new KeyAdapter(){@Override public void keyPressed(KeyEvent e){pulse();}};
    private final ChangeListener adjusting=e->{if(adjusting())pulse();};
    private final HierarchyListener visibility=this::visibilityChanged;

    StudyScrollActivity(JScrollPane scroll,Consumer<Boolean> changed){
        this.scroll=scroll;this.changed=changed;idle.setRepeats(false);
        if(scroll instanceof UnifiedScrollPane unified)unified.addWheelInputListener(wheel);
        else scroll.addMouseWheelListener(wheel);
        scroll.addHierarchyListener(visibility);
        for(JScrollBar bar:new JScrollBar[]{scroll.getVerticalScrollBar(),scroll.getHorizontalScrollBar()}){
            bar.addMouseListener(mouse);bar.addKeyListener(key);bar.getModel().addChangeListener(adjusting);
        }
    }
    boolean active(){return active;}
    private boolean adjusting(){return scroll.getVerticalScrollBar().getValueIsAdjusting()||scroll.getHorizontalScrollBar().getValueIsAdjusting();}
    private void pulse(){
        if(closed)return;
        if(!active){active=true;changed.accept(true);}idle.restart();
    }
    private void settle(){
        if(closed)return;
        if(pressed||adjusting()){idle.restart();return;}
        if(active){active=false;changed.accept(false);}
    }
    private void visibilityChanged(HierarchyEvent event){
        if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)==0||scroll.isShowing()||closed)return;
        pressed=false;idle.stop();
        if(active){active=false;changed.accept(false);}
    }
    @Override public void close(){
        closed=true;idle.stop();
        if(scroll instanceof UnifiedScrollPane unified)unified.removeWheelInputListener(wheel);
        else scroll.removeMouseWheelListener(wheel);
        scroll.removeHierarchyListener(visibility);
        for(JScrollBar bar:new JScrollBar[]{scroll.getVerticalScrollBar(),scroll.getHorizontalScrollBar()}){
            bar.removeMouseListener(mouse);bar.removeKeyListener(key);bar.getModel().removeChangeListener(adjusting);
        }
    }
}
