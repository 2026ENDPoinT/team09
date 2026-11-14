package dev.synesis.poc.ui;

import javax.swing.*;
import javax.swing.plaf.LayerUI;
import java.awt.*;
import java.awt.event.MouseAdapter;
import java.awt.image.BufferedImage;

/** Library sidebar destinations only. Keeps a single bounded preview, never the study navigation. */
public final class LibrarySectionMotion extends LayerUI<JPanel> implements LibraryMotionClock.Task {
    private final JPanel view;
    private final JLayer<JPanel> layer;
    private BufferedImage picture;
    private Runnable pending;
    private boolean outgoing,documents;
    private long started;
    private int width,height;
    private double progress;
    public LibrarySectionMotion(JPanel view) {
        this.view=view;layer=new JLayer<>(view,this);
        layer.getGlassPane().addMouseListener(new MouseAdapter(){});
        layer.getGlassPane().addMouseMotionListener(new MouseAdapter(){});
        layer.getGlassPane().addMouseWheelListener(event->event.consume());
        layer.addHierarchyListener(event->{if(!layer.isShowing())cancel();});
    }
    public JLayer<JPanel> component(){return layer;}
    public boolean active(){return picture!=null;}
    public void change(Runnable action,boolean documents) {
        if(!view.isShowing()||LibraryMotionClock.reduced()){cancel();action.run();return;}
        if(outgoing&&picture!=null){pending=action;this.documents=documents;return;}
        cancel();width=view.getWidth();height=view.getHeight();
        if(width<=0||height<=0){action.run();return;}
        try {picture=capture();}catch(OutOfMemoryError unavailable){action.run();return;}
        pending=action;this.documents=documents;outgoing=true;progress=0;started=System.nanoTime();
        layer.getGlassPane().setVisible(true);
        if(!LibraryMotionClock.add(this)){finish();return;}
        layer.repaint();
    }
    private BufferedImage capture() {
        long budget=Math.min(400_000L,Math.max(120_000L,Runtime.getRuntime().maxMemory()/256));
        double scale=Math.min(1,Math.sqrt(budget/(double)((long)width*height)));
        BufferedImage image=new BufferedImage(Math.max(1,(int)(width*scale)),Math.max(1,(int)(height*scale)),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();
        RepaintManager manager=RepaintManager.currentManager(view);boolean buffering=manager.isDoubleBufferingEnabled();
        try {manager.setDoubleBufferingEnabled(false);g.scale(image.getWidth()/(double)width,image.getHeight()/(double)height);view.printAll(g);}
        finally {g.dispose();manager.setDoubleBufferingEnabled(buffering);}
        return image;
    }
    @Override public boolean advance(long now) {
        if(!layer.isShowing()){cancel();return false;}
        if(view.getWidth()!=width||view.getHeight()!=height){finish();return false;}
        double time=(now-started)/(outgoing?170_000_000d:580_000_000d);
        progress=LibraryMotionClock.ease(time);
        if(time>=1) {
            if(outgoing) {
                Runnable next=pending;pending=null;releasePicture();
                next.run();layout(view);
                layer.getGlassPane().setVisible(false);
                // Documents use their own staggered live cards; no duplicate scene capture/fade.
                if(documents){cancel();return false;}
                try {picture=capture();}catch(OutOfMemoryError unavailable){cancel();return false;}
                outgoing=false;started=now;progress=0;
            } else {cancel();return false;}
        }
        layer.repaint();return true;
    }
    private static void layout(Container parent) {
        parent.doLayout();for(Component child:parent.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);
    }
    private void releasePicture(){if(picture!=null)picture.flush();picture=null;}
    private void finish(){Runnable next=pending;cancel();if(next!=null)next.run();}
    public void cancel() {
        LibraryMotionClock.remove(this);releasePicture();pending=null;outgoing=false;
        layer.getGlassPane().setVisible(false);layer.repaint();
    }
    @Override public void paint(Graphics graphics,JComponent component) {
        if(picture==null){super.paint(graphics,component);return;}
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setColor(view.getBackground());g.fillRect(0,0,component.getWidth(),component.getHeight());
            float alpha=(float)(outgoing?1-progress:progress);
            double scale=outgoing?1-.005*progress:.992+.008*progress;
            int w=(int)Math.round(width*scale),h=(int)Math.round(height*scale);
            int x=(width-w)/2,y=(height-h)/2+(int)Math.round(outgoing?-7*progress:11*(1-progress));
            g.setComposite(AlphaComposite.SrcOver.derive(alpha));g.drawImage(picture,x,y,w,h,null);
        } finally {g.dispose();}
    }
}
