package dev.synesis.poc.ui;

import java.awt.*;
import javax.swing.*;

/** Keeps the existing overlay geometry without shrinking and expanding an unchanged viewport on every layout. */
class PlannerOverlayScrollLayout extends ScrollPaneLayout {
    private LayoutData rendered;
    private record LayoutData(int width,int height,Insets insets,Insets viewportInsets,boolean leftToRight,
                              int verticalPolicy,int horizontalPolicy,Dimension viewPreferred,Dimension headerPreferred,
                              Dimension barPreferred,Rectangle viewport,Rectangle header,Rectangle bar,boolean barVisible){}
    private LayoutData data(JScrollPane pane){
        return new LayoutData(pane.getWidth(),pane.getHeight(),pane.getInsets(),
                pane.getViewportBorder()==null?new Insets(0,0,0,0):pane.getViewportBorder().getBorderInsets(pane),
                pane.getComponentOrientation().isLeftToRight(),pane.getVerticalScrollBarPolicy(),pane.getHorizontalScrollBarPolicy(),
                viewport==null||viewport.getView()==null?null:viewport.getView().getPreferredSize(),
                colHead==null?null:colHead.getPreferredSize(),vsb==null?null:vsb.getPreferredSize(),
                viewport==null?null:viewport.getBounds(),colHead==null?null:colHead.getBounds(),
                vsb==null?null:vsb.getBounds(),vsb!=null&&vsb.isVisible());
    }
    @Override public void layoutContainer(Container parent){
        JScrollPane pane=(JScrollPane)parent;LayoutData next=data(pane);
        if(next.equals(rendered))return;
        super.layoutContainer(parent);
        // These planner panes use a right-hand thumb over the grid, rather than a reserved stripe.
        if(vsb!=null&&vsb.isVisible()){
            Rectangle view=viewport.getBounds();int right=vsb.getX()+vsb.getWidth();
            viewport.setBounds(view.x,view.y,right-view.x,view.height);
            if(colHead!=null){Rectangle header=colHead.getBounds();colHead.setBounds(header.x,header.y,right-header.x,header.height);}
            if(upperRight!=null)upperRight.setBounds(0,0,0,0);
        }
        // The viewport grows over the thumb after Swing's standard layout.
        // Lay out both views at that final width before painting; otherwise
        // the header can retain the narrower width and leave Sunday clipped.
        if(viewport!=null)viewport.doLayout();
        if(colHead!=null)colHead.doLayout();
        rendered=data(pane);
    }
}
