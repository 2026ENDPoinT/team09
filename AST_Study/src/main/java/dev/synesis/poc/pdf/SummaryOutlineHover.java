package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.util.function.BooleanSupplier;
import javax.swing.*;
import javax.swing.event.*;

/** Button hover/click lifecycle. No listeners on the document or its scrollbars. */
final class SummaryOutlineHover implements AutoCloseable {
    private final JScrollPane host;
    private final JButton button;
    private final JPopupMenu popup;
    private final Runnable refresh,selectCurrent;
    private final BooleanSupplier available;
    private final Timer reveal,dismiss;
    private boolean hovered,hoverOpened,closed;

    SummaryOutlineHover(JScrollPane host,JButton button,JPopupMenu popup,BooleanSupplier available,Runnable refresh,Runnable selectCurrent) {
        this.host=host;this.button=button;this.popup=popup;this.available=available;
        this.refresh=refresh;this.selectCurrent=selectCurrent;
        reveal=new Timer(140,e->open(true));reveal.setRepeats(false);
        dismiss=new Timer(260,e->{if(hoverOpened)popup.setVisible(false);});dismiss.setRepeats(false);
        button.addMouseListener(new MouseAdapter(){
            @Override public void mouseEntered(MouseEvent e) {
                hovered=true;dismiss.stop();if(!popup.isVisible())reveal.restart();else popup.setVisible(true);
            }
            @Override public void mouseExited(MouseEvent e) {hovered=false;reveal.stop();if(hoverOpened)dismiss.restart();}
            @Override public void mousePressed(MouseEvent e) {reveal.stop();}
        });
        popup.addPopupMenuListener(new PopupMenuListener(){
            public void popupMenuWillBecomeVisible(PopupMenuEvent e) {}
            public void popupMenuWillBecomeInvisible(PopupMenuEvent e) {reset();}
            public void popupMenuCanceled(PopupMenuEvent e) {reset();}
        });
        host.addHierarchyListener(e->{
            if((e.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&!host.isShowing())closePopup();
        });
    }
    void trackPopup(Component component) {
        component.addMouseListener(new MouseAdapter(){
            @Override public void mouseEntered(MouseEvent e) {dismiss.stop();reveal.stop();if(popup.isVisible())popup.setVisible(true);}
            @Override public void mouseExited(MouseEvent e) {if(hoverOpened)dismiss.restart();}
        });
        if(component instanceof Container container)for(Component child:container.getComponents())trackPopup(child);
    }
    private void open(boolean hover) {
        if(closed||hover&&!hovered||!host.isShowing()||!available.getAsBoolean())return;
        if(popup.isVisible()){popup.setVisible(true);return;}
        refresh.run();if(popup.getComponentCount()==0)return;
        int width=Math.max(100,Math.min(290,host.getWidth()-24));
        int limit=Math.max(60,Math.min(540,host.getHeight()-20));
        Insets padding=popup.getInsets();JComponent content=(JComponent)popup.getComponent(0);
        int insideWidth=Math.max(1,width-padding.left-padding.right);
        int naturalHeight=content.getPreferredSize().height;
        if(content instanceof JScrollPane scroll&&scroll.getViewport().getView()!=null) {
            Dimension view=scroll.getViewport().getView().getPreferredSize();
            Insets border=scroll.getInsets();
            naturalHeight=view.height+border.top+border.bottom;
            Insets viewportInsets=scroll.getViewport().getInsets();
            naturalHeight+=viewportInsets.top+viewportInsets.bottom;
            if(scroll.getViewportBorder()!=null) {
                Insets edge=scroll.getViewportBorder().getBorderInsets(scroll);
                naturalHeight+=edge.top+edge.bottom;
            }
            int scrollbar=view.height+padding.top+padding.bottom>limit?scroll.getVerticalScrollBar().getPreferredSize().width:0;
            if(scroll.getHorizontalScrollBarPolicy()==JScrollPane.HORIZONTAL_SCROLLBAR_ALWAYS
                    ||scroll.getHorizontalScrollBarPolicy()!=JScrollPane.HORIZONTAL_SCROLLBAR_NEVER
                    &&view.width>insideWidth-border.left-border.right-scrollbar)
                naturalHeight+=scroll.getHorizontalScrollBar().getPreferredSize().height;
        }
        int height=Math.min(limit,Math.max(1,naturalHeight)+padding.top+padding.bottom);
        content.setPreferredSize(new Dimension(insideWidth,Math.max(1,height-padding.top-padding.bottom)));
        popup.setPopupSize(width,height);
        hoverOpened=hover;
        popup.show(button,button.getWidth()-width,button.getHeight()+4);
        SwingUtilities.invokeLater(selectCurrent);
    }
    void explicitOpen() {
        reveal.stop();dismiss.stop();
        if(popup.isVisible()) {
            if(hoverOpened){hoverOpened=false;popup.setVisible(true);}else popup.setVisible(false);
        }else open(false);
    }
    private void reset() {reveal.stop();dismiss.stop();hoverOpened=false;}
    private void closePopup() {
        reset();if(popup instanceof SummaryOutlinePopup animated)animated.close();else popup.setVisible(false);
    }
    @Override public void close() {closed=true;closePopup();}
}
