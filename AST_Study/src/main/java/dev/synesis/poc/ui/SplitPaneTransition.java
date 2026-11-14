package dev.synesis.poc.ui;

import javax.swing.*;
import java.util.List;

/** Fade content out, move only panel shells, then reveal the final layout. */
public final class SplitPaneTransition extends Timer {
    private final JSplitPane split;
    private final int from,to,duration,width,height;
    private final Runnable afterLayout,completed;
    private final List<LayoutMotionPanel> panels;
    private final int fadeOutWait;
    private final long started=System.nanoTime();
    private boolean released;
    private int lastLocation=Integer.MIN_VALUE;

    public static Timer animate(JSplitPane split,int target,int duration,Runnable afterLayout,Runnable completed) {
        if(!split.isShowing()||split.getWidth()<=0||split.getHeight()<=0
                ||split.getOrientation()!=JSplitPane.HORIZONTAL_SPLIT) {
            split.setDividerLocation(target);afterLayout.run();completed.run();return null;
        }
        if(split.getClientProperty("synesis.splitTransition") instanceof SplitPaneTransition active)active.stop();
        SplitPaneTransition motion=new SplitPaneTransition(split,target,duration,afterLayout,completed);
        split.putClientProperty("synesis.splitTransition",motion);motion.start();return motion;
    }
    private SplitPaneTransition(JSplitPane split,int target,int duration,Runnable afterLayout,Runnable completed) {
        super(16,null);this.split=split;from=split.getDividerLocation();to=target;
        this.duration=Math.max(180,duration);this.afterLayout=afterLayout;this.completed=completed;
        width=split.getWidth();height=split.getHeight();panels=LayoutMotionPanel.holdTree(split);
        fadeOutWait=panels.stream().mapToInt(LayoutMotionPanel::fadeOutMillis).max().orElse(0);
        setCoalesce(true);addActionListener(e->advance());
    }
    private void advance() {
        if(released)return;
        if(!split.isShowing()){stop();return;}
        if(width!=split.getWidth()||height!=split.getHeight()){finish();return;}
        float t=Math.max(0,Math.min(1,((System.nanoTime()-started)/1_000_000f-fadeOutWait)/duration));
        float eased=t*t*(3-2*t);int location=Math.round(from+(to-from)*eased);
        if(location!=lastLocation){lastLocation=location;split.setDividerLocation(location);split.doLayout();split.repaint();}
        if(t>=1)finish();
    }
    private void finish() {
        if(released)return;
        split.setDividerLocation(to);split.doLayout();afterLayout.run();
        super.stop();released=true;split.putClientProperty("synesis.splitTransition",null);
        try {completed.run();} finally {LayoutMotionPanel.releaseTree(panels);}
    }
    /** An interruption retains current geometry so the next transition can take over. */
    @Override public void stop() {
        super.stop();if(released)return;released=true;
        split.putClientProperty("synesis.splitTransition",null);LayoutMotionPanel.releaseTree(panels);
    }
}
