package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.event.MouseWheelEvent;

/** Fractional wheel accumulation without changing a viewport's painting mode. */
public final class PreciseWheelInput {
    private JScrollBar verticalBar,horizontalBar;
    private int verticalExpected,horizontalExpected;
    private double verticalRemainder,horizontalRemainder;
    private double overflowPixels;

    /** False means no travel remains here; the caller may forward the precise input. */
    public boolean scroll(JScrollPane pane,MouseWheelEvent event){
        overflowPixels=0;
        if(event.isConsumed()||!pane.isWheelScrollingEnabled()||event.isControlDown())return false;
        JScrollBar bar=ScrollPolicy.bar(pane,event);
        int minimum=bar.getMinimum(),maximum=Math.max(minimum,bar.getMaximum()-bar.getVisibleAmount());
        if(!bar.isVisible()||!bar.isEnabled()||maximum<=minimum){reset();return false;}
        double delta=ScrollPolicy.distance(event);
        if(!Double.isFinite(delta))return false;
        if(delta==0)return true;
        boolean horizontal=bar.getOrientation()==SwingConstants.HORIZONTAL;
        int current=bar.getValue();
        JScrollBar remembered=horizontal?horizontalBar:verticalBar;
        int expected=horizontal?horizontalExpected:verticalExpected;
        double remainder=remembered==bar&&current==expected
            ?(horizontal?horizontalRemainder:verticalRemainder):0;
        // Keep two independent fractional residues, rather than adding tiny
        // deltas to a potentially large absolute document offset.
        if((delta<0&&current==minimum&&remainder<=0)||(delta>0&&current==maximum&&remainder>=0)){
            remember(horizontal,bar,current,0);return false;
        }
        double pending=remainder+delta;
        int next=(int)Math.max(minimum,Math.min(maximum,(double)current+Math.round(pending)));
        remainder=pending-(next-(long)current);
        if((next==minimum&&remainder<0)||(next==maximum&&remainder>0)){overflowPixels=remainder;remainder=0;}
        remember(horizontal,bar,next,remainder);
        if(next!=current)bar.setValue(next);
        event.consume();return true;
    }
    public double overflowPixels(){return overflowPixels;}
    private void remember(boolean horizontal,JScrollBar bar,int expected,double remainder){
        if(horizontal){horizontalBar=bar;horizontalExpected=expected;horizontalRemainder=remainder;}
        else {verticalBar=bar;verticalExpected=expected;verticalRemainder=remainder;}
    }
    public void reset(){verticalBar=horizontalBar=null;verticalRemainder=horizontalRemainder=overflowPixels=0;}
}
