package dev.synesis.poc.pdf;

import java.awt.Dimension;
import java.util.function.LongSupplier;
import javax.swing.JComponent;

/** A unit owns its spare height: incoming lines consume it before moving later units. */
final class SummaryStreamSpace extends JComponent {
    static final long MOTION_NANOS=280_000_000L;
    private final LongSupplier clock;
    private boolean draft=true,missing,initialized,finishing,paused;
    private int natural=1,line=24,measuredWidth;
    private double current,start,target;
    private long began;
    SummaryStreamSpace(){this(System::nanoTime);}
    SummaryStreamSpace(LongSupplier clock){this.clock=clock;setOpaque(false);}
    void configure(boolean draft,boolean missing,int font){
        if(finishing){draft=false;missing=false;}
        long now=clock.getAsLong();tick(now);int nextLine=Math.max(16,(int)Math.ceil(font*1.55));
        boolean changed=this.draft!=draft||this.missing!=missing||line!=nextLine;
        if(this.draft&&!draft)current=Math.max(0,current-natural);
        else if(!this.draft&&draft)current+=natural;
        this.draft=draft;this.missing=missing;line=nextLine;
        if(changed)retarget(draft?natural+line*4:missing&&!finishing?line*2:0,now);
    }
    void measured(int height){measured(height,0);}
    void measured(int height,int width){
        if(!draft)return;long now=clock.getAsLong();tick(now);int nextNatural=Math.max(1,height);
        // Width changes reflow the whole paragraph. Preserve spare lines, not
        // a narrow/initial viewport's former, potentially very tall footprint.
        if(initialized&&width>0&&measuredWidth>0&&width!=measuredWidth) {
            int shift=nextNatural-natural;current+=shift;start+=shift;target+=shift;
        }
        if(width>0)measuredWidth=width;natural=nextNatural;
        if(!initialized){initialized=true;current=natural;retarget(natural+line*4,now);return;}
        // Never clip real text. Replenish before the reserved tail is exhausted.
        if(current<natural)current=natural;
        if(!finishing&&target-natural<line*2)retarget(natural+line*4,now);
    }
    void finish(){
        long now=clock.getAsLong();tick(now);
        if(draft)current=Math.max(0,current-natural);
        draft=false;finishing=true;retarget(0,now);
        if(paused)settle(); // Completion must not wait for the reader to stop scrolling.
    }
    void pause(boolean value){
        if(paused==value)return;
        long now=clock.getAsLong();
        if(value)tick(now);
        paused=value;
        if(!value){start=current;began=now;}
    }
    boolean paused(){return paused;}
    private void retarget(double value,long now){
        if(Math.abs(target-value)<.1&&began!=0)return;
        start=current;target=value;began=now;
    }
    boolean tick(long now){
        if(paused)return false;
        int before=height();double fraction=Math.max(0,Math.min(1,(now-began)/(double)MOTION_NANOS));
        current=start+(target-start)*(1-Math.pow(1-fraction,3));
        if(fraction>=1)current=target;
        return before!=height();
    }
    boolean moving(){return Math.abs(current-target)>.5;}
    void settle(){current=target;start=target;began=clock.getAsLong()-MOTION_NANOS;}
    int height(){return Math.max(0,(int)Math.round(current)-(draft?natural:0));}
    int footprint(){return natural+height();}
    @Override public Dimension getPreferredSize(){return new Dimension(1,height());}
}
