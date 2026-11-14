package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.event.ChangeListener;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.beans.PropertyChangeListener;
import java.util.IdentityHashMap;
import java.util.Map;

/** Opt-in, viewport-sized pixel reuse. Fixed decorations must paint after super.paint().
 * Transparent viewports retain direct compositing against their changing background. */
public class ScrollCacheViewport extends JViewport {
    private boolean cacheEnabled,contentDirty=true;
    private RenderingHints paintHints;
    private BufferedImage pixels;
    private Point paintedPosition;
    private Dimension paintedViewSize;
    private double pixelScaleX,pixelScaleY;
    private final Map<Component,ButtonModel> observed=new IdentityHashMap<>();
    private final ChangeListener changed=e->contentChanged();
    private final FocusListener focus=new FocusAdapter(){
        @Override public void focusGained(FocusEvent e){contentChanged();}
        @Override public void focusLost(FocusEvent e){contentChanged();}
    };
    private final ComponentListener geometry=new ComponentAdapter(){
        @Override public void componentResized(ComponentEvent e){contentChanged();}
        @Override public void componentMoved(ComponentEvent e){if(e.getComponent()!=getView())contentChanged();}
        @Override public void componentShown(ComponentEvent e){contentChanged();}
        @Override public void componentHidden(ComponentEvent e){contentChanged();}
    };
    private final PropertyChangeListener properties=e->{
        if("model".equals(e.getPropertyName())&&e.getSource() instanceof AbstractButton button){
            ButtonModel old=observed.put(button,button.getModel());
            if(old!=null)old.removeChangeListener(changed);
            if(button.getModel()!=null)button.getModel().addChangeListener(changed);
        }
        contentChanged();
    };
    private final ContainerListener children=new ContainerAdapter(){
        @Override public void componentAdded(ContainerEvent e){observe(e.getChild(),true);contentChanged();}
        @Override public void componentRemoved(ContainerEvent e){observe(e.getChild(),false);contentChanged();}
    };
    public ScrollCacheViewport(){
        setScrollMode(SIMPLE_SCROLL_MODE);
        addHierarchyListener(e->{if((e.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&!isShowing())releaseCache();});
        addPropertyChangeListener(e->contentChanged());
    }
    public final boolean isCacheEnabled(){return cacheEnabled;}
    public void setCacheEnabled(boolean enabled){
        if(cacheEnabled==enabled)return;
        cacheEnabled=enabled;
        observe(getView(),enabled);releaseCache();repaint();
    }
    /** An edit between a wheel event and its paint must not copy obsolete pixels. */
    private void contentChanged(){contentDirty=true;}
    /** Custom painters call this when visual state changes without a Swing property/model event. */
    public static void invalidateContent(Component component){
        for(Component c=component;c!=null;c=c.getParent())if(c instanceof ScrollCacheViewport view)view.contentChanged();
    }
    private void observe(Component c,boolean add){
        if(c==null||observed==null)return;
        if(add){
            if(observed.containsKey(c))return;
            ButtonModel model=c instanceof AbstractButton b?b.getModel():null;observed.put(c,model);
            c.addPropertyChangeListener(properties);
            c.addFocusListener(focus);c.addComponentListener(geometry);
            if(model!=null)model.addChangeListener(changed);
            if(c instanceof JViewport viewport)viewport.addChangeListener(changed);
            if(c instanceof Container box){box.addContainerListener(children);for(Component child:box.getComponents())observe(child,true);}
        }else{
            if(!observed.containsKey(c))return;
            ButtonModel model=observed.remove(c);c.removePropertyChangeListener(properties);
            c.removeFocusListener(focus);c.removeComponentListener(geometry);
            if(model!=null)model.removeChangeListener(changed);
            if(c instanceof JViewport viewport)viewport.removeChangeListener(changed);
            if(c instanceof Container box){box.removeContainerListener(children);for(Component child:box.getComponents())observe(child,false);}
        }
    }
    @Override public void setView(Component view){
        observe(getView(),false);releaseCache();super.setView(view);
        if(cacheEnabled)observe(view,true);
    }
    @Override public void addNotify(){super.addNotify();if(cacheEnabled)observe(getView(),true);}
    @Override public void removeNotify(){observe(getView(),false);releaseCache();super.removeNotify();}
    private void releaseCache(){if(pixels!=null)pixels.flush();pixels=null;paintedPosition=null;paintedViewSize=null;}
    @Override public void setViewPosition(Point position){
        // A pending hover/selection repaint must also be included when a scroll
        // and content update share the same frame.
        boolean dirtyBefore=cacheEnabled&&!position.equals(getViewPosition())&&(contentDirty||dirty(getView(),RepaintManager.currentManager(this)));
        super.setViewPosition(position);
        if(dirtyBefore)contentChanged();
    }
    private boolean dirty(Component c,RepaintManager manager){
        if(c instanceof JComponent jc&&!manager.getDirtyRegion(jc).isEmpty())return true;
        if(c instanceof Container box)for(Component child:box.getComponents())if(child.isVisible()&&dirty(child,manager))return true;
        return false;
    }
    @Override protected boolean isPaintingOrigin(){return cacheEnabled||super.isPaintingOrigin();}
    @Override public void paint(Graphics graphics){
        boolean use=cacheEnabled&&isOpaque()&&graphics instanceof Graphics2D&&getView()!=null&&getWidth()>0&&getHeight()>0;
        double sx=1,sy=1;
        if(use){
            Graphics2D g=(Graphics2D)graphics;var t=g.getTransform();sx=t.getScaleX();sy=t.getScaleY();
            // Fractional device pixels cannot be shifted without changing glyph
            // and edge sampling. Retain the original renderer at those scales.
            use=t.getShearX()==0&&t.getShearY()==0&&sx>=1&&sy>=1
                &&sx==Math.rint(sx)&&sy==Math.rint(sy)
                &&t.getTranslateX()==Math.rint(t.getTranslateX())&&t.getTranslateY()==Math.rint(t.getTranslateY())
                &&g.getComposite() instanceof AlphaComposite composite&&composite.getRule()==AlphaComposite.SRC_OVER&&composite.getAlpha()==1
                &&getWidth()*sx*getHeight()*sy<=8_000_000
                &&(getView().getHeight()>getHeight()||getView().getWidth()>getWidth());
        }
        // Own the backing image instead of JViewport's backing-store branch:
        // that branch replaces the caller's nonrectangular clip during a copy,
        // which leaks pixels through the planner's rounded calendar corners.
        if(getScrollMode()!=SIMPLE_SCROLL_MODE)setScrollMode(SIMPLE_SCROLL_MODE);
        if(!use){releaseCache();super.paint(graphics);return;}
        Graphics2D g=(Graphics2D)graphics;RenderingHints hints=g.getRenderingHints();
        int width=getWidth(),height=getHeight(),pw=(int)(width*sx),ph=(int)(height*sy);
        if(pixels!=null&&(pixels.getWidth()!=pw||pixels.getHeight()!=ph||pixelScaleX!=sx||pixelScaleY!=sy||!hints.equals(paintHints)))releaseCache();
        paintHints=hints;pixelScaleX=sx;pixelScaleY=sy;
        Point position=getViewPosition();Dimension size=getViewSize();Rectangle full=new Rectangle(0,0,width,height);
        Rectangle clip=g.getClipBounds();if(clip==null)clip=full;else clip=clip.intersection(full);
        boolean fresh=pixels==null;
        if(fresh)pixels=new BufferedImage(pw,ph,BufferedImage.TYPE_INT_RGB);
        int dx=paintedPosition==null?0:position.x-paintedPosition.x,dy=paintedPosition==null?0:position.y-paintedPosition.y;
        boolean moved=dx!=0||dy!=0;
        boolean redraw=fresh||!size.equals(paintedViewSize)||moved&&(contentDirty||dx!=0&&dy!=0||Math.abs(dx)>=width||Math.abs(dy)>=height);
        Rectangle damage=redraw?full:clip;
        if(moved&&!redraw){
            Graphics2D copy=pixels.createGraphics();copy.copyArea(0,0,pw,ph,(int)(-dx*sx),(int)(-dy*sy));copy.dispose();
            damage=dy>0?new Rectangle(0,height-dy,width,dy):dy<0?new Rectangle(0,0,width,-dy)
                :dx>0?new Rectangle(width-dx,0,dx,height):new Rectangle(0,0,-dx,height);
        }
        Graphics2D buffer=pixels.createGraphics();
        try{
            buffer.setRenderingHints(hints);buffer.setColor(g.getColor());buffer.setFont(g.getFont());
            buffer.scale(sx,sy);buffer.setClip(damage);super.paint(buffer);
        }finally{buffer.dispose();}
        // Keep the original shape clip and composite when presenting the cache.
        g.drawImage(pixels,0,0,width,height,null);
        paintedPosition=position;paintedViewSize=size;
        if(redraw||clip.contains(full))contentDirty=false;
    }
}
