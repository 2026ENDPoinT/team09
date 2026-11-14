package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.*;
import javax.swing.Timer;

/** Paint-only zoom; temporary low-resolution dissolve images, never a second page cache. EDT-owned. */
final class PdfZoomMotion {
    private static final long ZOOM_NS=180_000_000L, FADE_NS=160_000_000L;
    private static final long PREVIEW_BUDGET=4L<<20;
    private record Fade(BufferedImage image,long started) {}
    private final Map<Integer,Fade> fades=new LinkedHashMap<>();
    private final Runnable repaint;
    private final Timer timer;
    private Runnable completion;
    private double scale=1,from=1,to=1,pivotX,pivotY;
    private long zoomStarted;

    PdfZoomMotion(Runnable repaint) {
        this.repaint=repaint;
        timer=new Timer(16,e->tick());timer.setCoalesce(true);
    }
    boolean zooming(){return completion!=null;}
    void zoom(double target,double x,double y,Runnable done) {
        from=scale;to=target;pivotX=x;pivotY=y;zoomStarted=System.nanoTime();completion=done;
        clearFades();timer.start();
    }
    void transform(Graphics2D g) {
        if(zooming()){g.translate(pivotX,pivotY);g.scale(scale,scale);g.translate(-pivotX,-pivotY);}
    }
    private void tick() {
        long now=System.nanoTime();
        if(zooming()) {
            double t=Math.min(1,(now-zoomStarted)/(double)ZOOM_NS),ease=1-Math.pow(1-t,3);
            scale=from+(to-from)*ease;
            if(t>=1) {
                Runnable done=completion;completion=null;scale=1;done.run();
            }
        }
        for(Iterator<Fade> it=fades.values().iterator();it.hasNext();) {
            Fade fade=it.next();if(now-fade.started()>=FADE_NS){fade.image().flush();it.remove();}
        }
        repaint.run();
        if(!zooming()&&fades.isEmpty())timer.stop();
    }
    static BufferedImage preview(BufferedImage old) {
        double factor=Math.min(1,Math.sqrt(262144d/((double)old.getWidth()*old.getHeight())));
        int w=Math.max(1,(int)(old.getWidth()*factor)),h=Math.max(1,(int)(old.getHeight()*factor));
        BufferedImage image=new BufferedImage(w,h,BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(old,0,0,w,h,null);g.dispose();return image;
    }
    void dissolve(int page,BufferedImage image) {
        remove(page);
        long bytes=bytes(image);
        for(Iterator<Fade> it=fades.values().iterator();retainedBytes()+bytes>PREVIEW_BUDGET&&it.hasNext();) {
            it.next().image().flush();it.remove();
        }
        fades.put(page,new Fade(image,System.nanoTime()));timer.start();
    }
    long retainedBytes(){return fades.values().stream().mapToLong(f->bytes(f.image())).sum();}
    private static long bytes(BufferedImage image){return 4L*image.getWidth()*image.getHeight();}
    void paint(Graphics2D g,int page,BufferedImage image,Rectangle box) {
        // Draw the opaque new image first, then fade away the old preview: no white flash.
        g.drawImage(image,box.x,box.y,box.width,box.height,null);
        Fade fade=fades.get(page);
        if(fade!=null) {
            float remaining=(float)Math.max(0,1-(System.nanoTime()-fade.started())/(double)FADE_NS);
            Composite previous=g.getComposite();
            g.setComposite(AlphaComposite.SrcOver.derive(remaining));
            g.drawImage(fade.image(),box.x,box.y,box.width,box.height,null);g.setComposite(previous);
        }
    }
    void remove(int page){Fade old=fades.remove(page);if(old!=null)old.image().flush();}
    private void clearFades(){for(Fade fade:fades.values())fade.image().flush();fades.clear();}
    void clear(){timer.stop();completion=null;scale=1;clearFades();}
}
