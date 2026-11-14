package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;

/** Paint-only overflow hints; never intercept selection, dragging or wheel input. */
public class FadeScrollPane extends UnifiedScrollPane {
    private boolean verticalOverflowShadow;
    private static final int SHADOW_HEIGHT=35;
    private int verticalShadowHeight=SHADOW_HEIGHT;
    private static final Color SHADOW=new Color(255,255,255,255),CLEAR=new Color(255,255,255,0);
    /** Compact lists can use a shorter hint without changing the shared study-view default. */
    public void setVerticalOverflowShadowHeight(int height) {
        if(height<1)throw new IllegalArgumentException("Shadow height must be positive");
        if(verticalShadowHeight==height)return;
        verticalShadowHeight=height;repaint();
    }
    public void setVerticalOverflowShadow(boolean enabled) {
        if(verticalOverflowShadow==enabled)return;
        verticalOverflowShadow=enabled;
        if(enabled)getViewport().addChangeListener(event->{
            if(!verticalOverflowShadow)return;
            Rectangle r=getViewport().getBounds();
            repaint(r.x,r.y,r.width,verticalShadowHeight);
            repaint(r.x,r.y+Math.max(0,r.height-verticalShadowHeight),r.width,verticalShadowHeight);
        });
        repaint();
    }
    @Override public void paint(Graphics graphics) {
        super.paint(graphics);
        if(!verticalOverflowShadow)return;
        JViewport viewport=getViewport();Rectangle r=viewport.getBounds();
        int y=viewport.getViewPosition().y;
        int remaining=viewport.getViewSize().height-viewport.getExtentSize().height-y;
        if(r.width<=0||r.height<=0||y<=0&&remaining<=0)return;
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.clip(r);int height=Math.min(verticalShadowHeight,r.height);
            if(y>0&&!Boolean.TRUE.equals(getClientProperty("synesis.pinnedToolbar"))){g.setPaint(new GradientPaint(0,r.y,SHADOW,0,r.y+height,CLEAR));g.fillRect(r.x,r.y,r.width,height);}
            if(remaining>0){
                int bottom=r.y+r.height;
                int solid=Math.min(3,height),gradient=height-solid;
                if(gradient>0){
                    g.setPaint(new GradientPaint(0,bottom-height,CLEAR,0,bottom-solid,SHADOW));
                    g.fillRect(r.x,bottom-height,r.width,gradient);
                }
                g.setColor(Color.WHITE);
                g.fillRect(r.x,bottom-solid,r.width,solid);
            }
        } finally {g.dispose();}
    }
    public FadeScrollPane(Component view) { super(view); }
    public FadeScrollPane(Component view,int verticalPolicy,int horizontalPolicy) {
        super(view,verticalPolicy,horizontalPolicy);
    }
    @Override protected JViewport createViewport() { return new OverflowViewport(); }

    /** Keep content pixels separate from the fixed overflow hints. Opt-in for planner views. */
    public void setScrollCacheEnabled(boolean enabled) {
        ((OverflowViewport)getViewport()).setCacheEnabled(enabled);
    }
    @Override protected boolean isPaintingOrigin(){return getViewport() instanceof ScrollCacheViewport v&&v.isCacheEnabled()||super.isPaintingOrigin();}

    /** Reuse unchanged pixels in expensive vertical study views; retain full painting for edge masks. */
    public void setVerticalScrollReuseEnabled(boolean enabled) {
        getViewport().putClientProperty("synesis.verticalScrollReuse",enabled);
        if(getViewport() instanceof OverflowViewport viewport)viewport.updateScrollMode();
    }

    private static final class OverflowViewport extends ScrollCacheViewport {
        OverflowViewport() {
            // Scrolling can use blit copies. Repaint the fixed edge masks as well.
            setScrollMode(SIMPLE_SCROLL_MODE);
            addChangeListener(event->{updateScrollMode();if(!isCacheEnabled()&&getScrollMode()==SIMPLE_SCROLL_MODE)repaint();});
        }
        private void updateScrollMode(){
            if(isCacheEnabled())return;
            boolean horizontalFade=getParent() instanceof JScrollPane scroll
                &&scroll.getHorizontalScrollBarPolicy()!=HORIZONTAL_SCROLLBAR_NEVER
                &&getViewSize().width>getExtentSize().width;
            int mode=Boolean.TRUE.equals(getClientProperty("synesis.verticalScrollReuse"))&&!horizontalFade?BLIT_SCROLL_MODE:SIMPLE_SCROLL_MODE;
            if(getScrollMode()!=mode){setScrollMode(mode);repaint();}
        }
        @Override public void paint(Graphics graphics) {
            super.paint(graphics);
            Component view=getView();
            if(view==null || getWidth()<=0 || getHeight()<=0)return;
            if(getParent() instanceof JScrollPane scroll
                    && scroll.getHorizontalScrollBarPolicy()==HORIZONTAL_SCROLLBAR_NEVER)return;
            int x=getViewPosition().x;
            int right=Math.max(0,getViewSize().width-getExtentSize().width);
            if(right<=0)return;
            Color color=getBackground();
            if(view.isOpaque())color=view.getBackground();
            Graphics2D g=(Graphics2D)graphics.create();
            try {
                int fade=Math.min(26,Math.max(1,getWidth()/5));
                if(x>0)paintEdge(g,0,fade,color,Math.min(1,x/(float)fade),true);
                if(x<right)paintEdge(g,getWidth()-fade,fade,color,Math.min(1,(right-x)/(float)fade),false);
            } finally {g.dispose();}
        }
        private void paintEdge(Graphics2D g,int x,int width,Color color,float strength,boolean left) {
            Color veil=new Color(color.getRed(),color.getGreen(),color.getBlue(),Math.round(215*strength));
            Color clear=new Color(color.getRed(),color.getGreen(),color.getBlue(),0);
            g.setPaint(new GradientPaint(x,0,left?veil:clear,x+width,0,left?clear:veil));
            g.fillRect(x,0,width,getHeight());
        }
    }
}
