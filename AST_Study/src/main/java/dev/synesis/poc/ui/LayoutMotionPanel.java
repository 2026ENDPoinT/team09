package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Freeze rich children while only their rounded shell follows a resize gesture. */
public final class LayoutMotionPanel extends MistWorkspaceTheme.Panel {
    public static final int FADE_OUT_MS=110, RETURN_MS=110, SETTLE_MS=60;
    // EDT-only scope: initial navigation layout must not start another resize animation.
    private static int immediateLayoutDepth;
    private enum Phase { LIVE, OUT, SHELL, RETURN }
    private Phase phase=Phase.LIVE;
    private BufferedImage picture;
    private int pictureWidth,pictureHeight,holds;
    private long fadeStarted;
    private float opacity=1;
    private float fadeFrom=1;
    private float shrink,shrinkFrom;
    private boolean capturing,contentHold;
    private boolean navigationShell;
    private float entranceOpacity=1;
    private long entranceStarted;
    private final Timer entrance=new Timer(16,e->advanceEntrance());
    private boolean shadowSuppressed;
    private Object restingShadow;
    private final Color surface,outline;
    private final int radius;
    private Insets shellInsets=new Insets(0,0,0,0);
    private boolean transparentWrapper;
    private ResizeScrollAnchor scrollAnchor;
    private final Map<Object,Runnable> deferred=new LinkedHashMap<>();
    private final List<Component> hiddenChildren=new ArrayList<>();
    private final Timer fade=new Timer(16,e->advance());
    private final Timer settled=new Timer(SETTLE_MS,e->reveal());
    private final Timer contentChange=new Timer(FADE_OUT_MS,e->commitContent());
    private Runnable nextContent;
    private int outMs=FADE_OUT_MS,returnMs=RETURN_MS,pixelLimit=2_097_152;
    public void setMotionBudget(int outMs,int returnMs,int pixelLimit){
        this.outMs=Math.max(1,outMs);this.returnMs=Math.max(1,returnMs);this.pixelLimit=Math.max(1,pixelLimit);
    }
    public int fadeOutMillis(){return outMs;}

    public LayoutMotionPanel(LayoutManager layout) {this(layout,12,Color.WHITE,MistWorkspaceTheme.LINE);}
    public LayoutMotionPanel(LayoutManager layout,int radius,Color surface,Color outline) {
        super(layout,radius,surface,outline);
        this.radius=radius;this.surface=surface;this.outline=outline;
        fade.setCoalesce(true);entrance.setCoalesce(true);settled.setRepeats(false);contentChange.setRepeats(false);
    }
    /** A motion host must not add a second white surface, outline, shadow or content inset. */
    public static LayoutMotionPanel transparentHost(LayoutManager layout,Insets shellInsets) {
        LayoutMotionPanel panel=new LayoutMotionPanel(layout,0,new Color(0,0,0,0),null);
        panel.transparentWrapper=true;panel.shellInsets=(Insets)shellInsets.clone();
        panel.setBorder(BorderFactory.createEmptyBorder());panel.putClientProperty("mist.shadow",null);
        return panel;
    }
    private boolean frozen(){return phase==Phase.OUT||phase==Phase.SHELL;}
    @Override public boolean isValidateRoot(){return true;}
    @Override public void doLayout(){if(phase==Phase.LIVE||capturing)super.doLayout();}
    @Override public void setBounds(int x,int y,int width,int height) {
        Rectangle previous=getBounds();
        boolean resize=settled!=null&&!capturing&&!navigationShell&&immediateLayoutDepth==0&&isShowing()
            &&getWidth()>0&&getHeight()>0&&(width!=getWidth()||height!=getHeight());
        if(resize)freeze();
        super.setBounds(x,y,width,height);
        if(resize){if(holds==0){settled.setInitialDelay(SETTLE_MS);settled.restart();}repaint();}
        if(resize&&getParent()!=null){Rectangle dirty=previous.union(getBounds());dirty.grow(16,16);getParent().repaint(dirty.x,dirty.y,dirty.width,dirty.height);}
    }
    private void freeze() {
        if(frozen())return;
        if(scrollAnchor==null)scrollAnchor=new ResizeScrollAnchor(this);
        finishEntrance();
        settled.stop();fade.stop();
        if(phase!=Phase.RETURN||picture==null){releasePicture();capture();opacity=1;}
        if(!shadowSuppressed){restingShadow=getClientProperty("mist.shadow");putClientProperty("mist.shadow",null);shadowSuppressed=true;}
        fadeFrom=opacity;shrinkFrom=shrink;
        phase=Phase.OUT;hideChildren();fadeStarted=System.nanoTime();fade.start();
    }
    private void hold() {freeze();holds++;settled.stop();}
    private void release() {
        holds=Math.max(0,holds-1);
        // Divider release and tab completion already identify the end of the gesture.
        if(holds==0)SwingUtilities.invokeLater(this::reveal);
    }
    public static List<LayoutMotionPanel> holdTree(Component component) {
        List<LayoutMotionPanel> panels=new ArrayList<>();collect(component,panels);
        panels.forEach(LayoutMotionPanel::hold);return panels;
    }
    public static void releaseTree(List<LayoutMotionPanel> panels){panels.forEach(LayoutMotionPanel::release);}

    /** Commit the destination's real bounds once, before taking its navigation snapshot. */
    public static void prepareNavigation(Container scene,Runnable prepare) {
        immediateLayoutDepth++;
        try {
            settleTree(scene);
            prepare.run();
            settleTree(scene);
            layoutTree(scene);
        } finally {immediateLayoutDepth--;}
    }

    public static void layoutNow(Container scene) {
        immediateLayoutDepth++;
        try {settleTree(scene);layoutTree(scene);} finally {immediateLayoutDepth--;}
    }

    public static boolean isImmediateLayout() {return immediateLayoutDepth>0;}

    private static void settleTree(Component component) {
        if(!component.isVisible())return;
        if(component instanceof LayoutMotionPanel panel) {
            Runnable content=panel.nextContent;
            List<Runnable> tasks=new ArrayList<>(panel.deferred.values());panel.deferred.clear();
            panel.reset();
            if(content!=null)content.run();
            tasks.forEach(Runnable::run);
        }
        if(component instanceof Container container)
            for(Component child:container.getComponents())settleTree(child);
    }

    /** Keep real panel geometry, but omit rich children from the one-time preview paint. */
    public static List<LayoutMotionPanel> navigationShells(Component scene) {
        List<LayoutMotionPanel> panels=new ArrayList<>();collect(scene,panels);
        panels.forEach(panel->panel.navigationShell=true);
        return panels;
    }

    public static void revealNavigation(List<LayoutMotionPanel> panels) {
        panels.forEach(panel->panel.navigationShell=false);
        panels.forEach(Component::repaint);
    }

    public static void resumeNavigationContent(List<LayoutMotionPanel> panels) {
        panels.forEach(panel->{
            List<Runnable> tasks=new ArrayList<>(panel.deferred.values());panel.deferred.clear();
            tasks.forEach(Runnable::run);panel.startEntrance();panel.repaint();
        });
    }

    /** Late PDF pixels use the same entrance as the already loaded navigation panels. */
    public static void fadeInContent(Component content) {
        for(Component current=content;current!=null;current=current.getParent())
            if(current instanceof LayoutMotionPanel panel){panel.startEntrance();return;}
    }
    private void startEntrance() {
        if(!isShowing()||navigationShell||phase!=Phase.LIVE)return;
        if(Boolean.getBoolean("synesis.reduceMotion")||Boolean.TRUE.equals(UIManager.get("synesis.reduceMotion")))return;
        entranceOpacity=0;entranceStarted=System.nanoTime();entrance.start();repaint();
    }
    private void advanceEntrance() {
        if(!isShowing()||phase!=Phase.LIVE){finishEntrance();return;}
        float progress=(float)Math.min(1,(System.nanoTime()-entranceStarted)/168_000_000d);
        entranceOpacity=progress*progress*(3-2*progress);
        if(progress>=1)finishEntrance();
        repaint();
    }
    private void finishEntrance(){entrance.stop();entranceOpacity=1;}
    @Override protected void paintChildren(Graphics graphics) {
        if(capturing||entranceOpacity>=1){super.paintChildren(graphics);return;}
        // Only composite existing content; no layout, PDF rasterization or snapshot per frame.
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            float inherited=g.getComposite() instanceof AlphaComposite alpha?alpha.getAlpha():1;
            g.setComposite(AlphaComposite.SrcOver.derive(inherited*entranceOpacity));
            super.paintChildren(g);
        }finally{g.dispose();}
    }
    private static void collect(Component component,List<LayoutMotionPanel> panels) {
        if(!component.isVisible())return;
        if(component instanceof LayoutMotionPanel panel){panels.add(panel);return;}
        if(component instanceof Container container)
            for(Component child:container.getComponents())collect(child,panels);
    }
    /** Coalesce expensive view rebuilds; their underlying source/model state keeps updating. */
    public static boolean defer(Component component,Object key,Runnable task) {
        for(Component current=component;current!=null;current=current.getParent())
            if(current instanceof LayoutMotionPanel panel&&(panel.navigationShell||panel.phase!=Phase.LIVE)) {
                panel.deferred.put(key,task);return true;
            }
        return false;
    }
    public void changeContent(Runnable change) {
        if(immediateLayoutDepth>0||navigationShell||!isShowing()){change.run();return;}
        nextContent=change;
        if(!contentHold){contentHold=true;hold();}
        contentChange.restart();
    }
    private void commitContent() {
        Runnable change=nextContent;nextContent=null;
        if(change!=null)change.run();
        if(contentHold){contentHold=false;release();}
    }
    private void reveal() {
        if(holds>0||!frozen())return;
        if(!isShowing()||getWidth()<1||getHeight()<1){reset();return;}
        settled.stop();fade.stop();
        phase=Phase.LIVE;restoreChildren();
        // Descendants retain their old bounds during the gesture; commit the final layout once.
        layoutTree(this);
        List<Runnable> tasks=new ArrayList<>(deferred.values());deferred.clear();tasks.forEach(Runnable::run);
        if(!tasks.isEmpty())layoutTree(this);
        if(scrollAnchor!=null)scrollAnchor.restore();
        // Render the final bounds once, then grow these cached pixels with the shell.
        // The return starts immediately on release; rich content is not laid out per frame.
        releasePicture();capture();hideChildren();
        phase=Phase.RETURN;shrinkFrom=shrink;opacity=0;fadeStarted=System.nanoTime();fade.start();repaintScene();
    }
    private static void layoutTree(Container container) {
        container.doLayout();
        for(Component child:container.getComponents())
            if(child.isVisible()&&child instanceof Container nested)layoutTree(nested);
    }
    private void capture() {
        if(getWidth()<1||getHeight()<1||!isShowing())return;
        pictureWidth=getWidth();pictureHeight=getHeight();
        // Transient fade pixels only: a fixed pixel budget, independent of Retina scale.
        double scale=Math.min(1,Math.sqrt(pixelLimit/Math.max(1,pictureWidth*(double)pictureHeight)));
        picture=new BufferedImage(Math.max(1,(int)Math.ceil(pictureWidth*scale)),
            Math.max(1,(int)Math.ceil(pictureHeight*scale)),BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics=picture.createGraphics();capturing=true;
        try {graphics.scale(scale,scale);super.paint(graphics);}
        finally {capturing=false;graphics.dispose();}
    }
    private void advance() {
        boolean returning=phase==Phase.RETURN;
        float t=Math.min(1,(System.nanoTime()-fadeStarted)/((returning?returnMs:outMs)*1_000_000f));
        float eased=t*t*(3-2*t);
        opacity=returning?eased:fadeFrom*(1-eased);
        shrink=returning?shrinkFrom*(1-eased):shrinkFrom+(1-shrinkFrom)*eased;
        if(t>=1){
            fade.stop();
            if(returning){
                phase=Phase.LIVE;shrink=0;opacity=1;restoreShadow();restoreChildren();
                List<Runnable> tasks=new ArrayList<>(deferred.values());deferred.clear();tasks.forEach(Runnable::run);
                if(scrollAnchor!=null){scrollAnchor.restore();scrollAnchor=null;}
                revalidate();
            } else {phase=Phase.SHELL;shrink=1;}
            releasePicture();
        }
        repaintScene();
    }
    @Override public void paint(Graphics graphics) {
        if(!navigationShell&&(capturing||phase==null||phase==Phase.LIVE)){super.paint(graphics);return;}
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            if(Boolean.TRUE.equals(getClientProperty("synesis.smoothSnapshot")))
                g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            // Clear the entire old footprint, including rounded corners and the shrink margin.
            g.setComposite(AlphaComposite.SrcOver);g.setColor(StudyTheme.CANVAS);g.fillRect(0,0,getWidth(),getHeight());
            Insets edge=shellInsets;
            int corner=transparentWrapper?12:radius;
            double insetX=Math.min(8,getWidth()*.012)*shrink,insetY=Math.min(8,getHeight()*.012)*shrink;
            // Reserve a raster-safe gutter in the navigation snapshot, including flush screen edges.
            double borderInset=navigationShell?1.5:.5;
            double left=edge.left+borderInset+insetX,top=edge.top+borderInset+insetY;
            double width=Math.max(0,getWidth()-edge.left-edge.right-2*borderInset-2*insetX);
            double height=Math.max(0,getHeight()-edge.top-edge.bottom-2*borderInset-2*insetY);
            Shape shape=new RoundRectangle2D.Double(left,top,width,height,corner*2,corner*2);
            g.setColor(transparentWrapper?Color.WHITE:surface);g.fill(shape);
            if(!navigationShell&&picture!=null&&opacity>0) {
                Shape clip=g.getClip();
                g.clip(shape);
                g.setComposite(AlphaComposite.SrcOver.derive(Math.max(0,Math.min(1,opacity))));
                if(phase==Phase.RETURN){
                    Graphics2D content=(Graphics2D)g.create();
                    try {content.translate(insetX,insetY);content.scale(Math.max(0,(getWidth()-2*insetX)/Math.max(1d,getWidth())),Math.max(0,(getHeight()-2*insetY)/Math.max(1d,getHeight())));content.drawImage(picture,0,0,pictureWidth,pictureHeight,null);}
                    finally {content.dispose();}
                }else g.drawImage(picture,0,0,pictureWidth,pictureHeight,null);
                g.setComposite(AlphaComposite.SrcOver);g.setClip(clip);
            }
            Color line=transparentWrapper?MistWorkspaceTheme.LINE:outline;
            if(line!=null){g.setColor(shrink>0?new Color(0xbdc9da):line);g.setStroke(new BasicStroke(shrink>0?1.2f:1f));g.draw(shape);}
        } finally {g.dispose();}
    }
    private void releasePicture(){if(picture!=null)picture.flush();picture=null;}
    private void repaintScene(){
        if(getParent()!=null)getParent().repaint(getX()-16,getY()-16,getWidth()+32,getHeight()+32);
        else repaint();
    }
    private void restoreShadow(){if(shadowSuppressed){putClientProperty("mist.shadow",restingShadow);restingShadow=null;shadowSuppressed=false;}}
    private void hideChildren(){
        if(!hiddenChildren.isEmpty())return;
        for(Component child:getComponents())if(child.isVisible()){hiddenChildren.add(child);child.setVisible(false);}
    }
    private void restoreChildren(){for(Component child:hiddenChildren)if(child.getParent()==this)child.setVisible(true);hiddenChildren.clear();}
    private void reset(){scrollAnchor=null;finishEntrance();fade.stop();settled.stop();contentChange.stop();phase=Phase.LIVE;shrink=0;opacity=1;holds=0;contentHold=false;nextContent=null;releasePicture();restoreShadow();restoreChildren();}
    @Override public void addNotify(){super.addNotify();SwingUtilities.invokeLater(()->{
        if(isShowing()&&phase==Phase.LIVE){List<Runnable> tasks=new ArrayList<>(deferred.values());deferred.clear();tasks.forEach(Runnable::run);}
    });}
    @Override public void removeNotify(){reset();super.removeNotify();}
}
