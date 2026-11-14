package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import javax.swing.*;

/** A local overlay: its entire surface animates, without a native popup shadow. */
final class SummaryOutlinePopup extends JPopupMenu implements AutoCloseable {
    private static final int OPEN_MS=150,CLOSE_MS=280;
    private static final int SHADOW=8;
    private final Timer animation=new Timer(16,e->advance());
    private final AWTEventListener outside=this::outsideEvent;
    private BufferedImage frame,surface;
    private JLayeredPane layer;
    private float amount=1,from=1,target=1;
    private long started;
    private boolean visible,listening;

    SummaryOutlinePopup() {
        setOpaque(false);
        setBorder(BorderFactory.createEmptyBorder(10+SHADOW,10+SHADOW,10+SHADOW,10+SHADOW));
        animation.setCoalesce(true);
    }
    @Override public boolean isVisible() {return visible;}
    @Override public void show(Component invoker,int x,int y) {
        if(isVisible()) {setVisible(true);return;}
        JRootPane root=SwingUtilities.getRootPane(invoker);if(root==null)return;
        setInvoker(invoker);layer=root.getLayeredPane();
        Dimension size=getPreferredSize();Point at=SwingUtilities.convertPoint(invoker,x,y,layer);
        at.x=Math.max(0,Math.min(at.x,layer.getWidth()-size.width));
        at.y=Math.max(0,Math.min(at.y,layer.getHeight()-size.height));
        setBounds(at.x,at.y,size.width,size.height);
        visible=true;layer.add(this,JLayeredPane.POPUP_LAYER);layoutTree(this);
        firePopupMenuWillBecomeVisible();capture();amount=0;animate(1);
        Toolkit.getDefaultToolkit().addAWTEventListener(outside,AWTEvent.MOUSE_EVENT_MASK|AWTEvent.KEY_EVENT_MASK
            |AWTEvent.WINDOW_EVENT_MASK|AWTEvent.WINDOW_FOCUS_EVENT_MASK);
        listening=true;
    }
    @Override public void setVisible(boolean show) {
        // JPopupMenu's native PopupFactory owns an unanimated background/shadow.
        // Keep this surface in the app's layered pane instead.
        if(show) {if(visible&&target==0)animate(1);}
        else if(visible) {
            if(target==0&&animation.isRunning())return;
            if(frame==null)capture();animate(0);
        }
    }
    private void outsideEvent(AWTEvent event) {
        if(!visible)return;
        if(event instanceof MouseEvent mouse&&mouse.getID()==MouseEvent.MOUSE_PRESSED) {
            Component source=mouse.getComponent();
            if(!inside(source,this)&&!inside(source,getInvoker()))setVisible(false);
        }else if(event instanceof KeyEvent key&&key.getID()==KeyEvent.KEY_PRESSED&&key.getKeyCode()==KeyEvent.VK_ESCAPE) {
            setVisible(false);
        }else if(event instanceof WindowEvent window
                &&(window.getID()==WindowEvent.WINDOW_DEACTIVATED||window.getID()==WindowEvent.WINDOW_LOST_FOCUS)
                &&window.getWindow()==SwingUtilities.getWindowAncestor(this)) {
            // App switching must not leave even a fading menu above another app.
            hideImmediately();
        }
    }
    private static boolean inside(Component child,Component parent) {
        return parent!=null&&(child==parent||SwingUtilities.isDescendingFrom(child,parent));
    }
    private void capture() {
        releaseFrame();
        int width=Math.max(1,getWidth()),height=Math.max(1,getHeight());
        double scale=getGraphicsConfiguration()==null?1:getGraphicsConfiguration().getDefaultTransform().getScaleX();
        scale=Math.max(1,Math.min(2,scale));
        frame=new BufferedImage((int)Math.ceil(width*scale),(int)Math.ceil(height*scale),BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics=frame.createGraphics();
        try {graphics.scale(scale,scale);paintSurface(graphics);super.paintChildren(graphics);}
        finally {graphics.dispose();}
    }
    private void animate(float to) {
        from=amount;target=to;started=System.nanoTime();animation.restart();repaint();
    }
    private void advance() {
        float t=Math.min(1,(System.nanoTime()-started)/((target==0?CLOSE_MS:OPEN_MS)*1_000_000f));
        float ease=target==0?t*t*t*(t*(t*6-15)+10):1-(1-t)*(1-t)*(1-t);
        amount=from+(target-from)*ease;repaint();
        if(t>=1) {animation.stop();if(target==0)hideImmediately();else releaseFrame();}
    }
    @Override public void paint(Graphics graphics) {
        Graphics2D copy=(Graphics2D)graphics.create();
        try {
            // Composite only menu/shadow pixels over Swing's freshly painted parent.
            // A saved 1x background would blur Retina prose and replay stale scroll frames.
            copy.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            if(frame!=null) {
                copy.setComposite(AlphaComposite.SrcOver.derive(Math.max(0,Math.min(1,amount))));
                copy.clip(new RoundRectangle2D.Float(0,0,getWidth(),getHeight()*amount,18,18));
                copy.drawImage(frame,0,0,getWidth(),getHeight(),null);
            } else {paintSurface(copy);super.paintChildren(copy);}
        } finally {copy.dispose();}
    }
    private void paintSurface(Graphics2D graphics) {
        // A transparent image contains only the shadow, white panel and outline.
        // Neither document pixels nor menu text are baked into this persistent cache.
        double scale=Math.max(1,Math.min(2,Math.abs(graphics.getTransform().getScaleX())));
        int pixelsWide=Math.max(1,(int)Math.ceil(getWidth()*scale));
        int pixelsHigh=Math.max(1,(int)Math.ceil(getHeight()*scale));
        if(surface==null||surface.getWidth()!=pixelsWide||surface.getHeight()!=pixelsHigh) {
            if(surface!=null)surface.flush();
            surface=new BufferedImage(pixelsWide,pixelsHigh,BufferedImage.TYPE_INT_ARGB);
            Graphics2D image=surface.createGraphics();
            try {
                image.scale(scale,scale);
                image.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                int width=getWidth()-2*SHADOW,height=getHeight()-2*SHADOW;
                // Eight small alpha layers approximate a soft shadow; no blur filter.
                for(int spread=SHADOW;spread>0;spread--) {
                    image.setColor(new Color(0,0,0,3));
                    image.fillRoundRect(SHADOW-spread,SHADOW-spread+2,width+spread*2,height+spread*2-2,18+spread,18+spread);
                }
                dev.synesis.poc.ui.RoundedPopupMenuUI.paintSurface(image,SHADOW,SHADOW,width,height,Color.WHITE);
            } finally {image.dispose();}
        }
        graphics.drawImage(surface,0,0,getWidth(),getHeight(),null);
    }
    private static void layoutTree(Container container) {
        container.doLayout();for(Component child:container.getComponents())if(child instanceof Container nested)layoutTree(nested);
    }
    private void releaseFrame() {if(frame!=null){frame.flush();frame=null;}}
    private void hideImmediately() {
        animation.stop();releaseFrame();if(surface!=null){surface.flush();surface=null;}amount=1;target=1;
        if(listening){Toolkit.getDefaultToolkit().removeAWTEventListener(outside);listening=false;}
        if(!visible)return;
        visible=false;firePopupMenuWillBecomeInvisible();
        if(layer!=null){Rectangle bounds=getBounds();layer.remove(this);layer.repaint(bounds);layer=null;}
    }
    @Override public void close() {hideImmediately();}
}
