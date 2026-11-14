package dev.synesis.poc.pdf;

import java.awt.BorderLayout;
import java.awt.Component;
import java.awt.Container;
import java.awt.Dimension;
import java.awt.Graphics;
import java.awt.Insets;
import java.awt.event.HierarchyEvent;
import javax.swing.JPanel;
import javax.swing.Timer;

/** A clipped settings surface whose content keeps its natural height while revealing. */
final class QuizRevealPanel extends JPanel {
    private static final long DURATION_NANOS=420_000_000L;
    private final Timer motion;
    private boolean expanded,animating;
    private double currentHeight,startHeight,targetHeight;
    private long startedAt;
    private Runnable collapsed;

    QuizRevealPanel() {
        super(new BorderLayout());
        setOpaque(false);
        motion=new Timer(16,event->tick());
        motion.setCoalesce(true);
        addHierarchyListener(event->{
            if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&!isShowing()&&animating)
                finish();
        });
        setVisible(false);
    }

    boolean isExpanded(){return expanded;}

    void setExpanded(boolean value,boolean animate){setExpanded(value,animate,null);}

    void setExpanded(boolean value,boolean animate,Runnable onCollapsed) {
        long now=System.nanoTime();
        double height=animating?sample(now):expanded?naturalSize().height:0;
        // Reopening also invalidates a callback left by an earlier close.
        collapsed=value?null:onCollapsed;
        expanded=value;
        currentHeight=height;
        startHeight=height;
        targetHeight=value?naturalSize().height:0;
        startedAt=now;
        if(value)setVisible(true);
        if(!animate||Boolean.getBoolean("synesis.reduceMotion")||!isShowing()
                ||Math.abs(targetHeight-currentHeight)<.5) {
            finish();
            return;
        }
        animating=true;
        motion.start();
        revalidate();repaint();
    }

    private Dimension naturalSize(){return super.getPreferredSize();}

    @Override public Dimension getPreferredSize() {
        Dimension natural=naturalSize();
        return new Dimension(natural.width,animating?(int)Math.ceil(currentHeight):expanded?natural.height:0);
    }

    @Override public Dimension getMinimumSize(){return new Dimension(0,getPreferredSize().height);}
    @Override public Dimension getMaximumSize(){return new Dimension(Integer.MAX_VALUE,getPreferredSize().height);}

    @Override public void doLayout() {
        super.doLayout();
        // The center is laid out at its full height, then clipped by this panel.
        // Its controls consequently slide into view instead of being compressed.
        Component center=((BorderLayout)getLayout()).getLayoutComponent(BorderLayout.CENTER);
        if(center!=null&&center.isVisible()) {
            Insets insets=getInsets();
            int width=Math.max(0,getWidth()-insets.left-insets.right);
            for(int pass=0;pass<2;pass++) {
                int height=Math.max(0,naturalSize().height-insets.top-insets.bottom);
                center.setBounds(insets.left,insets.top,width,height);
                if(center instanceof Container container)container.doLayout();
            }
        }
    }

    @Override protected void paintChildren(Graphics graphics) {
        Graphics clipped=graphics.create();
        try {clipped.clipRect(0,0,getWidth(),getHeight());super.paintChildren(clipped);}
        finally {clipped.dispose();}
    }

    private void tick() {
        if(!isShowing()){finish();return;}
        long now=System.nanoTime();
        currentHeight=sample(now);
        double natural=expanded?naturalSize().height:0;
        if(Math.abs(natural-targetHeight)>=.5) {
            // Width changes and content edits retarget from the displayed height.
            startHeight=currentHeight;targetHeight=natural;startedAt=now;
        }
        if(now-startedAt>=DURATION_NANOS){finish();return;}
        revalidate();repaint();
    }

    private double sample(long now) {
        double progress=Math.max(0,Math.min(1,(now-startedAt)/(double)DURATION_NANOS));
        return startHeight+(targetHeight-startHeight)*ease(progress);
    }

    /** cubic-bezier(.22,1,.36,1), solving its time coordinate before sampling height. */
    private static double ease(double progress) {
        if(progress<=0||progress>=1)return progress;
        double low=0,high=1,t=progress;
        for(int i=0;i<16;i++) {
            double rest=1-t;
            double time=3*rest*rest*t*.22+3*rest*t*t*.36+t*t*t;
            if(time<progress)low=t;else high=t;
            t=(low+high)/2;
        }
        return 1-Math.pow(1-t,3);
    }

    private void finish() {
        motion.stop();animating=false;
        currentHeight=expanded?naturalSize().height:0;
        if(!expanded)setVisible(false);
        Runnable callback=collapsed;collapsed=null;
        revalidate();repaint();
        if(!expanded&&callback!=null)callback.run();
    }

    @Override public void removeNotify() {
        if(animating)finish();
        motion.stop();
        super.removeNotify();
    }
}
