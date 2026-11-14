package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Bounded, paint-only library departure. No live document layout on animation frames. */
public final class LibraryDeparture extends JPanel {
    public enum Kind { CARD, HEADER, SIDEBAR }
    public record Part(JComponent component, Kind kind) {}
    private static final double DURATION_MS=728;
    private final JRootPane root;
    private final JComponent scene;
    private final Component previousGlass, previousFocus;
    private final boolean previousVisible;
    private final int sceneWidth,sceneHeight;
    private final double rasterScale;
    private final double arrivalRasterScale;
    private record Sprite(BufferedImage image,int x,int y,Kind kind,double delay) {}
    private final List<Sprite> sprites=new ArrayList<>();
    private final Timer timer;
    private long started;
    private final ComponentAdapter resize;
    private Runnable destination;
    private List<LayoutMotionPanel> shells=List.of();
    private JButton destinationDefault;
    private BufferedImage departure,arrival;
    private double elapsed,paintAverage;
    private boolean finished;

    public static void play(JComponent library,List<Part> parts,Runnable prepare,Runnable destination) {
        JRootPane root=SwingUtilities.getRootPane(library);
        if(root!=null && root.getGlassPane() instanceof LibraryDeparture && root.getGlassPane().isVisible())return;
        if(root==null || !library.isShowing() || root.getGlassPane().isVisible()) {
            prepare.run();destination.run();return;
        }
        start(root,parts,prepare,destination);
    }

    static LibraryDeparture start(JRootPane root,List<Part> parts,Runnable prepare,Runnable destination) {
        if(!(root.getContentPane() instanceof JComponent scene) || scene.getWidth()<1 || scene.getHeight()<1) {
            prepare.run();destination.run();return null;
        }
        LibraryDeparture motion;
        try {motion=new LibraryDeparture(root,scene,parts);}
        catch(OutOfMemoryError unavailable) {
            // Allocation is capped below; an already exhausted heap must still allow navigation.
            prepare.run();destination.run();return null;
        }
        root.setGlassPane(motion);motion.setVisible(true);motion.setSize(scene.getSize());
        motion.destination=destination;
        try {
            // Only the empty, real shell is prepared. PDF opening stays behind the completion gate.
            LayoutMotionPanel.prepareNavigation(scene,prepare);
            motion.destinationDefault=root.getDefaultButton();root.setDefaultButton(null);
            motion.shells=LayoutMotionPanel.navigationShells(scene);
            motion.arrival=motion.snapshot(motion.arrivalRasterScale);
        } catch(OutOfMemoryError unavailable) {
            motion.finish();return null;
        } catch(RuntimeException | Error failure) {
            motion.finish(false);throw failure;
        }
        motion.requestFocusInWindow();
        motion.started=System.nanoTime();motion.timer.start();
        return motion;
    }

    private LibraryDeparture(JRootPane root,JComponent scene,List<Part> parts) {
        this.root=root;this.scene=scene;
        previousGlass=root.getGlassPane();previousVisible=previousGlass.isVisible();
        destinationDefault=root.getDefaultButton();
        previousFocus=KeyboardFocusManager.getCurrentKeyboardFocusManager().getFocusOwner();
        sceneWidth=scene.getWidth();sceneHeight=scene.getHeight();
        long pixels=pixelBudget(Runtime.getRuntime().maxMemory());
        rasterScale=Math.min(1,Math.sqrt(pixels/(double)((long)sceneWidth*sceneHeight)));
        GraphicsConfiguration configuration=scene.getGraphicsConfiguration();
        double deviceScale=configuration==null?1:Math.max(configuration.getDefaultTransform().getScaleX(),configuration.getDefaultTransform().getScaleY());
        arrivalRasterScale=Math.min(Math.max(1,Math.min(2,deviceScale)),
            Math.sqrt(arrivalPixelBudget(Runtime.getRuntime().maxMemory())/(double)((long)sceneWidth*sceneHeight)));
        departure=snapshot(rasterScale);
        Rectangle viewport=new Rectangle(0,0,sceneWidth,sceneHeight);
        List<Rectangle> erased=new ArrayList<>();
        for(Part part:parts) {
            JComponent component=part.component();
            if(part.kind()==Kind.CARD || !component.isVisible()
                    || !SwingUtilities.isDescendingFrom(component,scene))continue;
            Rectangle visible=component.getVisibleRect();
            if(visible.isEmpty())continue;
            Rectangle bounds=SwingUtilities.convertRectangle(component,visible,scene).intersection(viewport);
            if(bounds.isEmpty())continue;
            sprites.add(capture(bounds,part.kind(),part.kind()==Kind.HEADER?0:20));
            erased.add(bounds);
        }
        Graphics2D erase=departure.createGraphics();
        try {
            erase.scale(rasterScale,rasterScale);erase.setColor(Color.WHITE);
            for(Rectangle bounds:erased)erase.fillRect(bounds.x,bounds.y,bounds.width,bounds.height);
        }finally{erase.dispose();}
        sprites.sort(Comparator.comparingInt(sprite->sprite.kind().ordinal()));
        setDoubleBuffered(true);
        setOpaque(true);setBackground(Color.WHITE);setFocusable(true);setFocusTraversalKeysEnabled(false);
        enableEvents(AWTEvent.KEY_EVENT_MASK);
        MouseAdapter block=new MouseAdapter(){};addMouseListener(block);addMouseMotionListener(block);
        addMouseWheelListener(MouseWheelEvent::consume);
        getAccessibleContext().setAccessibleName("학습 화면으로 이동 중");
        timer=new Timer(16,event->advance(System.nanoTime()));timer.setCoalesce(true);
        resize=new ComponentAdapter(){@Override public void componentResized(ComponentEvent event){
            if(scene.getWidth()!=sceneWidth || scene.getHeight()!=sceneHeight)finish();
        }};
        scene.addComponentListener(resize);
    }

    static long pixelBudget(long heap) {return Math.min(900_000L,Math.max(120_000L,heap/192));}
    static long arrivalPixelBudget(long heap) {return Math.min(4_000_000L,Math.max(120_000L,heap/32));}

    private Sprite capture(Rectangle bounds,Kind kind,double delay) {
        int x=(int)Math.floor(bounds.x*rasterScale),y=(int)Math.floor(bounds.y*rasterScale);
        int right=Math.min(departure.getWidth(),(int)Math.ceil((bounds.x+bounds.width)*rasterScale));
        int bottom=Math.min(departure.getHeight(),(int)Math.ceil((bounds.y+bounds.height)*rasterScale));
        BufferedImage tile=new BufferedImage(Math.max(1,right-x),Math.max(1,bottom-y),BufferedImage.TYPE_INT_RGB);
        Graphics2D copy=tile.createGraphics();
        try {
            copy.setComposite(AlphaComposite.Src);
            copy.drawImage(departure,0,0,right-x,bottom-y,x,y,right,bottom,null);
        }finally{copy.dispose();}
        return new Sprite(tile,x,y,kind,delay);
    }

    private BufferedImage snapshot(double scale) {
        BufferedImage image=new BufferedImage(Math.max(1,(int)Math.ceil(sceneWidth*scale)),
            Math.max(1,(int)Math.ceil(sceneHeight*scale)),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();
        RepaintManager manager=RepaintManager.currentManager(scene);boolean buffered=manager.isDoubleBufferingEnabled();
        try {
            // Fill every raster pixel before scaling: ceil-rounded edges otherwise retain RGB black.
            g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());
            manager.setDoubleBufferingEnabled(false);g.scale(scale,scale);
            scene.printAll(g);
        }finally{g.dispose();manager.setDoubleBufferingEnabled(buffered);}
        return image;
    }

    void advance(long now) {
        if(finished)return;
        elapsed=(now-started)/1_000_000d;
        if(elapsed>=DURATION_MS){finish();return;}
        // Each source is independent: release it as soon as its last visible frame has passed.
        if(elapsed>=DURATION_MS*.52)departure=null;
        if(elapsed>=DURATION_MS*.7)sprites.clear();
        repaint();
    }

    private static double progress(double ms,double delay,double duration) {
        return Math.max(0,Math.min(1,(ms-delay)/duration));
    }
    // Zero velocity and acceleration at both ends, without spring simulation.
    private static double smooth(double t){return t*t*t*(t*(t*6-15)+10);}
    static double arrivalScale(double p){return .92+.08*smooth(p);}

    @Override protected void paintComponent(Graphics graphics) {
        if(finished || arrival==null){super.paintComponent(graphics);return;}
        long begin=System.nanoTime();
        // Draw cached sources directly to the display: avoid a low-resolution intermediate frame.
        Graphics2D frame=(Graphics2D)graphics.create();
        try {
            frame.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            frame.setComposite(AlphaComposite.Src);frame.setColor(Color.WHITE);
            frame.fillRect(0,0,sceneWidth,sceneHeight);
            if(arrival!=null) {
                double p=progress(elapsed,0,DURATION_MS*.98);
                double reveal=smooth(progress(elapsed,0,DURATION_MS*.62));
                double scale=arrivalScale(p);
                int width=(int)Math.round(sceneWidth*scale),height=(int)Math.round(sceneHeight*scale);
                int x=(sceneWidth-width)/2,y=(sceneHeight-height)/2;
                frame.setComposite(AlphaComposite.SrcOver.derive((float)reveal));
                frame.drawImage(arrival,x,y,width,height,null);
            }
            double fade=1-smooth(progress(elapsed,0,DURATION_MS*.52));
            // Outgoing chrome keeps its inexpensive old sampling; quality is spent on the growing destination.
            frame.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_NEAREST_NEIGHBOR);
            if(departure!=null && fade>0) {
                frame.setComposite(AlphaComposite.SrcOver.derive((float)fade));
                frame.drawImage(departure,0,0,sceneWidth,sceneHeight,null);
            }
            // Move the two cached chrome strips; never repaint or lay out live panels per frame.
            for(Sprite sprite:sprites) {
                double p=progress(elapsed,sprite.delay()*DURATION_MS/560,
                    DURATION_MS*(sprite.kind()==Kind.HEADER?.56:.64));
                if(p>=1)continue;
                double movement=smooth(p),x=sprite.x()/rasterScale,y=sprite.y()/rasterScale;
                double alpha=1-smooth(progress(p,.76,.24));
                int width=(int)Math.round(sprite.image().getWidth()/rasterScale),height=(int)Math.round(sprite.image().getHeight()/rasterScale);
                if(sprite.kind()==Kind.HEADER)y-=(height+20)*movement;
                else x-=(width+24)*movement;
                frame.setComposite(alpha>=.999?AlphaComposite.SrcOver:AlphaComposite.SrcOver.derive((float)alpha));
                frame.drawImage(sprite.image(),(int)Math.round(x),(int)Math.round(y),width,height,null);
            }
        }finally{frame.dispose();}
        double cost=(System.nanoTime()-begin)/1_000_000d;
        paintAverage=paintAverage==0?cost:paintAverage*.8+cost*.2;
        // Cap idle callbacks at 60Hz; leave the EDT time for input on slower machines.
        int delay=paintAverage>25?50:paintAverage>16?33:paintAverage>10?25:16;
        if(timer.getDelay()!=delay)timer.setDelay(delay);
    }

    @Override protected void processKeyEvent(KeyEvent event) {
        if(event.getID()==KeyEvent.KEY_PRESSED && event.getKeyCode()==KeyEvent.VK_ESCAPE)finish();
        event.consume();
    }

    void finish() {
        finish(true);
    }

    private void finish(boolean enter) {
        if(finished)return;finished=true;timer.stop();scene.removeComponentListener(resize);
        Runnable next=destination;destination=null;
        departure=arrival=null;sprites.clear();
        List<LayoutMotionPanel> prepared=shells;shells=List.of();
        LayoutMotionPanel.revealNavigation(prepared);
        if(root.getGlassPane()==this) {
            setVisible(false);root.setGlassPane(previousGlass);previousGlass.setVisible(previousVisible);
            root.setDefaultButton(destinationDefault);
            if(previousFocus!=null && previousFocus.isShowing())previousFocus.requestFocusInWindow();
            else scene.requestFocusInWindow();
            scene.repaint();
        }
        // Restore input and release snapshots first. No learning work runs during the motion.
        if(enter) {
            LayoutMotionPanel.resumeNavigationContent(prepared);
            if(next!=null)next.run();
        }
    }

    @Override public void removeNotify(){finish(false);super.removeNotify();}
}
