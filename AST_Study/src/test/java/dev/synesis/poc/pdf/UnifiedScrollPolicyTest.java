package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.*;
import java.awt.*;
import java.awt.event.*;
import java.util.List;
import javax.swing.*;

/** Identical physical input produces identical pixels across view types, extents and axis. */
public final class UnifiedScrollPolicyTest {
    private static int checks;
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            for(int height:new int[]{180,420})for(int localUnit:new int[]{6,8,24,72}){
                for(JScrollPane pane:List.of(new UnifiedScrollPane(view()),new FadeScrollPane(view()),
                        new SmoothScrollPane(view()),new QuizScrollPane(view(),JScrollPane.VERTICAL_SCROLLBAR_AS_NEEDED,JScrollPane.HORIZONTAL_SCROLLBAR_AS_NEEDED))){
                    pane.setSize(260,height);pane.doLayout();pane.getViewport().doLayout();
                    JScrollBar vertical=pane.getVerticalScrollBar(),horizontal=pane.getHorizontalScrollBar();
                    vertical.setUnitIncrement(localUnit);horizontal.setUnitIncrement(localUnit);
                    for(int i=0;i<100;i++)wheel(pane,.01,0,MouseWheelEvent.WHEEL_UNIT_SCROLL);
                    check(vertical.getValue()==18,"view/local unit altered precise PDF distance: "+pane.getClass());
                    for(int i=0;i<100;i++)wheel(pane,-.01,0,MouseWheelEvent.WHEEL_UNIT_SCROLL);
                    check(vertical.getValue()==0,"fractional reverse distance lost");
                    wheel(pane,1,0,MouseWheelEvent.WHEEL_UNIT_SCROLL);
                    check(vertical.getValue()==18,"coarse wheel is delayed or uses a different scale");
                    vertical.setValue(300);wheel(pane,.5,0,MouseWheelEvent.WHEEL_UNIT_SCROLL);
                    check(vertical.getValue()==309,"manual position did not reset accumulation");
                    vertical.setValue(0);wheel(pane,1,0,MouseWheelEvent.WHEEL_BLOCK_SCROLL);
                    check(vertical.getValue()==18,"block wheel distance varies with viewport height");
                    int y=vertical.getValue();wheel(pane,1,InputEvent.SHIFT_DOWN_MASK,MouseWheelEvent.WHEEL_UNIT_SCROLL);
                    check(horizontal.getValue()==18&&vertical.getValue()==y,"horizontal scale or axis changed");
                    pane.removeNotify();
                }
            }
            check(ScrollPolicy.PIXELS_PER_UNIT==6,"PDF reference unit changed");
            int[] calls={0};
            UnifiedScrollPane observed=new UnifiedScrollPane(view()){
                @Override protected void wheelInput(MouseWheelEvent event){
                    calls[0]++;check(getVerticalScrollBar().getValue()==18,"observer ran before shared movement");
                }
            };
            observed.setSize(260,180);observed.doLayout();observed.getViewport().doLayout();
            wheel(observed,1,0,MouseWheelEvent.WHEEL_UNIT_SCROLL);
            check(calls[0]==1&&observed.getVerticalScrollBar().getValue()==18,"user-intent observer or native handler duplicated movement");
        });
        SmoothScrollPaneTest.run();
        System.out.println("UnifiedScrollPolicyTest passed: "+checks+" cross-pane/extent/local-unit/axis checks plus immediate wheel regression; no windows.");
        System.exit(0);
    }
    private static JPanel view(){JPanel view=new JPanel();view.setPreferredSize(new Dimension(2000,5000));return view;}
    private static void wheel(JScrollPane pane,double rotation,int modifiers,int type){
        pane.dispatchEvent(new MouseWheelEvent(pane,MouseEvent.MOUSE_WHEEL,0,modifiers,40,40,40,40,0,false,type,3,(int)rotation,rotation));
    }
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
}
