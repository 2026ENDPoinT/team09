package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.SmoothScrollPane;
import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import java.awt.event.MouseWheelEvent;

/** Fractional trackpad input and opt-in paint reuse; no native input injection. */
public final class TrackpadScrollTest {
    static int checks;
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            JPanel view=new JPanel();view.setPreferredSize(new Dimension(150,5000));SmoothScrollPane pane=new SmoothScrollPane(view);pane.setVerticalScrollReuseEnabled(true);pane.setSize(240,180);pane.doLayout();pane.getViewport().doLayout();
            JScrollBar bar=pane.getVerticalScrollBar();bar.setUnitIncrement(8);
            check(pane.getViewport().getScrollMode()==JViewport.BLIT_SCROLL_MODE,"vertical study scrolling reuses unchanged pixels");
            for(int i=0;i<100;i++)wheel(pane,.01);
            check(bar.getValue()==18,"100 fractional trackpad movements retain the PDF distance despite a local unit override");
            for(int i=0;i<100;i++)wheel(pane,-.01);
            check(bar.getValue()==0,"slow reverse movement does not lose fractional input");
            wheel(pane,1);check(bar.getValue()==18,"ordinary mouse wheel uses the shared PDF distance");
            bar.setValue(300);wheel(pane,.5);check(bar.getValue()==309,"direct navigation resets the fractional accumulator");
            view.setPreferredSize(new Dimension(1000,5000));view.setSize(1000,5000);pane.getViewport().setViewSize(new Dimension(1000,5000));pane.doLayout();
            check(pane.getViewport().getScrollMode()==JViewport.SIMPLE_SCROLL_MODE,"horizontal edge masks retain full redraw to avoid stale shadows");
            pane.setHorizontalScrollBarPolicy(JScrollPane.HORIZONTAL_SCROLLBAR_NEVER);pane.getViewport().setViewPosition(new Point(0,320));
            check(pane.getViewport().getScrollMode()==JViewport.BLIT_SCROLL_MODE,"vertical-only policy resumes pixel reuse");
            pane.setVerticalScrollReuseEnabled(false);check(pane.getViewport().getScrollMode()==JViewport.SIMPLE_SCROLL_MODE,"non-opted-in screens keep existing rendering behavior");
        });
        System.out.println("PASS: "+checks+" trackpad precision and study scroll rendering checks");
    }
    static void wheel(JScrollPane pane,double rotation){pane.dispatchEvent(new MouseWheelEvent(pane,MouseEvent.MOUSE_WHEEL,0,0,40,40,40,40,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,(int)rotation,rotation));}
}
