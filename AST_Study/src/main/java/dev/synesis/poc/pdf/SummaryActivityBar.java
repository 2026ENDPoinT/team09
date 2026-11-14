package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.AnimationWindow;

import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import java.util.function.LongSupplier;
import java.util.function.BooleanSupplier;
import javax.swing.*;

/** Separate activity and measured progress; animate only the upper strip while visible. */
final class SummaryActivityBar extends JComponent implements AutoCloseable {
    enum State { IDLE, RUNNING, STOPPED }
    static final long CYCLE_NANOS=500_000_000L;
    // Ease-out exponent equals its initial slope: 10x the previous launch velocity.
    private static final double EASE_OUT_POWER=10*3*.25*500/700;
    private final LongSupplier clock;
    private static final Color TRACK=MistWorkspaceTheme.SOFT, HEAD=Color.BLACK,
        TAIL=new Color(0,true), BLUE=new Color(0x1688ff), RED=new Color(0xe45252);
    private final Timer timer=new Timer(16,event->frame());
    private final BooleanSupplier windowActive;
    private final Runnable stopObserving;
    private State state=State.IDLE;
    private int progress;
    private long started;
    private boolean closed;
    private boolean fitToBounds;

    SummaryActivityBar(){this(System::nanoTime);}
    SummaryActivityBar(LongSupplier clock) {
        this(clock,null);
    }
    SummaryActivityBar(LongSupplier clock,BooleanSupplier windowActive) {
        this.clock=clock;setOpaque(false);setPreferredSize(new Dimension(640,20));
        this.windowActive=windowActive==null?()->AnimationWindow.active(this):windowActive;
        timer.setCoalesce(true);
        stopObserving=AnimationWindow.watch(this,this::syncTimer);
        getAccessibleContext().setAccessibleName("강의 해설 생성 활동 표시");
    }
    @Override public javax.accessibility.AccessibleContext getAccessibleContext() {
        if(accessibleContext==null)accessibleContext=new AccessibleJComponent(){};
        return accessibleContext;
    }
    State state(){return state;}
    int progress(){return progress;}
    void setFitToBounds(boolean value){fitToBounds=value;repaint();}
    void setProgress(int percent) {
        int next=Math.max(0,Math.min(100,percent));
        if(progress==next)return;
        progress=next;updateDescription();repaint();
    }
    void setState(State next) {
        if(state==next)return;
        state=next;if(next==State.RUNNING)started=clock.getAsLong();
        updateDescription();
        syncTimer();repaint();
    }
    private void updateDescription() {
        getAccessibleContext().setAccessibleDescription(state==State.IDLE?"":
            (state==State.RUNNING?"강의 해설 생성 작업 중":"강의 해설 생성 중단")+" · 진행도 "+progress+"%");
    }
    private void frame(){if(closed||!isShowing()||!windowActive.getAsBoolean()){syncTimer();return;}repaint(0,0,getWidth(),getHeight()/2);}
    private void syncTimer(){if(!closed&&state==State.RUNNING&&isShowing()&&windowActive.getAsBoolean())timer.start();else timer.stop();}
    @Override public void removeNotify(){timer.stop();super.removeNotify();}
    @Override public void addNotify(){super.addNotify();syncTimer();}
    @Override protected void paintComponent(Graphics graphics) {
        if(state==State.IDLE)return;
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            int width=Math.max(1,fitToBounds?getWidth():Math.min(400,Math.round(getWidth()*.85f)));
            float scale=fitToBounds?Math.min(1,Math.max(0,getHeight()-2)/12f):1;
            float height=4*scale,y=(getHeight()-12*scale)/2,progressY=y+8*scale;
            RoundRectangle2D progressTrack=new RoundRectangle2D.Float(0,progressY,width,height,4,4);
            g.setColor(TRACK);g.fill(progressTrack);
            Shape clip=g.getClip();g.clip(progressTrack);
            g.setColor(state==State.STOPPED?RED:BLUE);
            g.fill(new java.awt.geom.Rectangle2D.Float(0,progressY,width*progress/100f,height));
            g.setClip(clip);
            RoundRectangle2D activityTrack=new RoundRectangle2D.Float(0,y,width,height,4,4);
            g.setColor(TRACK);g.fill(activityTrack);g.clip(activityTrack);
            if(state==State.STOPPED) {g.setColor(RED);g.fill(activityTrack);return;}
            double phase=Math.floorMod(clock.getAsLong()-started,CYCLE_NANOS)/(double)CYCLE_NANOS;
            int length=Math.max(24,Math.min(100,width/4));
            // Fast launch, then continuous deceleration to rest without reversing. Time-based positions
            // avoid slowing the sweep when a frame is skipped; float geometry avoids pixel snapping.
            float x=(float)((1-Math.pow(1-phase,EASE_OUT_POWER))*(width+length)-length);
            g.setPaint(new GradientPaint(x,y,TAIL,x+length,y,HEAD));
            g.fill(new RoundRectangle2D.Float(x,y,length,height,4,4));
        } finally {g.dispose();}
    }
    @Override public void close(){if(closed)return;closed=true;timer.stop();stopObserving.run();}
}
