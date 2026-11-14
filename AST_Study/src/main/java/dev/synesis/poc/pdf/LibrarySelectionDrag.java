package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryMotionClock;
import javax.swing.JComponent;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.List;

/** Bounded, paint-only gather. After 240 ms only pointer events repaint one cached stack. */
final class LibrarySelectionDrag implements LibraryMotionClock.Task,AutoCloseable {
    static final int MAX_SPRITES=12;
    static final long DURATION=240_000_000L;
    record Sprite(BufferedImage image,Point origin) {
        Sprite {origin=new Point(origin);}
    }
    private final JComponent surface;
    private List<Sprite> sprites;
    private BufferedImage stack;
    private Point pointer;
    private final long started=System.nanoTime();
    private double progress;
    private List<Sprite> returnSprites;
    private boolean returning;
    private long returned;
    private Runnable finished;

    LibrarySelectionDrag(JComponent surface,List<Sprite> sprites,BufferedImage stack,Point pointer) {
        this.surface=surface;this.sprites=List.copyOf(sprites.subList(0,Math.min(MAX_SPRITES,sprites.size())));
        this.returnSprites=this.sprites;
        this.stack=stack;this.pointer=new Point(pointer);
        if(LibraryMotionClock.reduced() || !LibraryMotionClock.add(this)){progress=1;this.sprites=List.of();}
        repaint(bounds());
    }

    void move(Point point) {
        if(stack==null || pointer.equals(point))return;
        Rectangle dirty=bounds();pointer.setLocation(point);dirty.add(bounds());repaint(dirty);
    }

    boolean isReturning() {return returning;}

    void returnToOrigins(Runnable finished) {
        this.finished=finished;returning=true;returned=System.nanoTime();sprites=returnSprites;progress=.999;
        repaint(bounds());
        if(LibraryMotionClock.reduced() || !LibraryMotionClock.add(this)){close();finished.run();}
    }

    @Override public boolean advance(long now) {
        if(stack==null)return false;
        Rectangle dirty=bounds();
        if(returning) {
            progress=1-Math.max(0,Math.min(1,(now-returned)/(double)DURATION));
            repaint(dirty);
            if(progress<=0){Runnable done=finished;close();if(done!=null)done.run();return false;}
            return true;
        }
        progress=Math.max(0,Math.min(1,(now-started)/(double)DURATION));
        if(progress>=1)sprites=List.of(); // Release all individual captures as soon as gathering ends.
        dirty.add(bounds());repaint(dirty);
        return progress<1;
    }

    private Rectangle bounds() {
        if(stack==null)return new Rectangle();
        Rectangle result=new Rectangle(pointer.x-84,pointer.y-84,168,168);
        for(Sprite sprite:sprites)result.add(new Rectangle(sprite.origin.x-84,sprite.origin.y-84,168,168));
        return result;
    }

    private void repaint(Rectangle dirty) {
        Rectangle clipped=dirty.intersection(new Rectangle(0,0,surface.getWidth(),surface.getHeight()));
        if(!clipped.isEmpty())surface.repaint(clipped.x,clipped.y,clipped.width,clipped.height);
    }

    void paint(Graphics2D graphics) {
        if(stack==null)return;
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            double reveal=returning?0:Math.max(0,Math.min(1,(progress-.75)*4));
            if(progress<1) {
                g.setComposite(AlphaComposite.SrcOver.derive((float)(1-reveal)));
                for(int i=sprites.size()-1;i>=0;i--) {
                    Sprite sprite=sprites.get(i);
                    double t=returning?1-LibraryMotionClock.ease(1-progress):LibraryMotionClock.ease(Math.max(0,Math.min(1,(progress-i*.012)/(1-i*.012))));
                    int x=(int)Math.round(sprite.origin.x+(pointer.x-sprite.origin.x)*t);
                    int y=(int)Math.round(sprite.origin.y+(pointer.y-sprite.origin.y)*t);
                    double scale=1-.14*t;
                    int w=Math.max(1,(int)Math.round(sprite.image.getWidth()*scale));
                    int h=Math.max(1,(int)Math.round(sprite.image.getHeight()*scale));
                    g.drawImage(sprite.image,x-w/2,y-h/2,w,h,null);
                }
            }
            if(reveal>0 || sprites.isEmpty()) {
                g.setComposite(AlphaComposite.SrcOver.derive(sprites.isEmpty()?1f:(float)reveal));
                g.drawImage(stack,pointer.x-stack.getWidth()/2,pointer.y-stack.getHeight()/2,null);
            }
        } finally {g.dispose();}
    }

    @Override public void close() {
        Rectangle dirty=bounds();LibraryMotionClock.remove(this);
        sprites=List.of();returnSprites=List.of();stack=null;finished=null;repaint(dirty);
    }
}
