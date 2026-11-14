package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.*;
import java.awt.*;
import java.awt.event.*;
import java.util.List;
import javax.swing.*;

/** Tiny, interleaved-axis and nested gestures; no timer, app window, or native input injection. */
public final class NanoTrackpadScrollTest {
    private static int checks;
    private static final class CountingBar extends JScrollBar {
        int writes;
        CountingBar(){super(JScrollBar.VERTICAL);}
        @Override public void setValue(int value){writes++;super.setValue(value);}
    }
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            for(UnifiedScrollPane pane:List.of(new UnifiedScrollPane(view()),new SmoothScrollPane(view()),
                    new FadeScrollPane(view()),new QuizScrollPane(view(),JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED))){
                layout(pane);JScrollBar vertical=pane.getVerticalScrollBar(),horizontal=pane.getHorizontalScrollBar();
                for(int i=0;i<500;i++){wheel(pane,.001,false);wheel(pane,.001,true);}
                check(vertical.getValue()==9&&horizontal.getValue()==9,"alternating axes lost fractional input: "+pane.getClass());
                for(int i=0;i<500;i++){wheel(pane,-.001,false);wheel(pane,-.001,true);}
                check(vertical.getValue()==0&&horizontal.getValue()==0,"micro reversal lost distance");
                for(int i=0;i<10000;i++)wheel(pane,.00001,false);
                check(vertical.getValue()==2,"subpixel input was discarded before reaching a pixel");
                vertical.setValue(300);wheel(pane,.01,false);vertical.setValue(600);wheel(pane,.01,false);
                check(vertical.getValue()==600,"manual navigation reused old subpixel residue");
                pane.setViewportView(view());layout(pane);vertical.setValue(0);wheel(pane,.02,false);
                pane.removeNotify();wheel(pane,.02,false);
                check(vertical.getValue()==0,"removed pane retained the previous gesture residue");
            }
            counting();nested();boundaryRemainder();
        });
        System.out.println("NanoTrackpadScrollTest passed: "+checks+" tiny-input/axis/reversal/nesting checks; integer writes only when pixels change.");
        System.exit(0);
    }
    private static void counting(){
        UnifiedScrollPane pane=new UnifiedScrollPane(view());CountingBar bar=new CountingBar();pane.setVerticalScrollBar(bar);layout(pane);bar.writes=0;
        for(int i=0;i<10000;i++)wheel(pane,.00001,false);
        check(bar.getValue()==2&&bar.writes==2,"micro input performs redundant model writes or loses total displacement");
    }
    private static void nested(){
        for(boolean overflow:new boolean[]{false,true}){
            UnifiedScrollPane inner=new UnifiedScrollPane(view());
            JPanel surface=new JPanel(null);surface.setPreferredSize(new Dimension(800,4000));surface.add(inner);inner.setBounds(10,200,240,160);
            UnifiedScrollPane outer=new UnifiedScrollPane(surface);layout(outer);inner.doLayout();inner.getViewport().doLayout();
            if(!overflow){JPanel fitting=new JPanel();fitting.setPreferredSize(new Dimension(50,40));inner.setViewportView(fitting);inner.doLayout();inner.getViewport().doLayout();}
            else inner.getVerticalScrollBar().setValue(Integer.MAX_VALUE);
            int[] seen={0};outer.addWheelInputListener(event->{check(event.getPreciseWheelRotation()==.001,"forwarding rounded the precise delta");seen[0]++;});
            for(int i=0;i<500;i++)wheel(inner,.001,false);
            check(outer.getVerticalScrollBar().getValue()==9,"fitting/edge inner area swallowed a tiny gesture");
            check(seen[0]==500,"gesture was delivered more than once or skipped");
            inner.removeNotify();outer.removeNotify();
        }
    }
    private static void boundaryRemainder(){
        UnifiedScrollPane inner=new UnifiedScrollPane(view());JPanel surface=new JPanel(null);surface.setPreferredSize(new Dimension(500,4000));surface.add(inner);inner.setBounds(0,150,240,160);
        UnifiedScrollPane outer=new UnifiedScrollPane(surface);layout(outer);inner.doLayout();inner.getViewport().doLayout();
        JScrollBar bar=inner.getVerticalScrollBar();int maximum=bar.getMaximum()-bar.getVisibleAmount();bar.setValue(maximum-1);
        wheel(inner,.04,false); // .72 px rounds to the final pixel but has not reached the logical edge.
        check(bar.getValue()==maximum,"fixture did not round to edge");
        for(int i=0;i<10;i++)wheel(inner,.001,false);
        check(outer.getVerticalScrollBar().getValue()==0,"rounded integer boundary prematurely forwarded a subpixel remainder");
        for(int i=0;i<6;i++)wheel(inner,.001,false);
        wheel(inner,.0274,false);
        check(outer.getVerticalScrollBar().getValue()==1,"fractional spillover was lost when the gesture crossed the inner edge");
        inner.removeNotify();outer.removeNotify();
    }
    private static JPanel view(){JPanel view=new JPanel();view.setPreferredSize(new Dimension(2000,5000));return view;}
    private static void layout(JScrollPane pane){pane.setSize(260,180);pane.doLayout();pane.getViewport().doLayout();}
    private static void wheel(JScrollPane pane,double rotation,boolean horizontal){pane.dispatchEvent(new MouseWheelEvent(pane,MouseEvent.MOUSE_WHEEL,0,
        horizontal?InputEvent.SHIFT_DOWN_MASK:0,40,40,40,40,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,(int)rotation,rotation));}
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
}
