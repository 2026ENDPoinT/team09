package dev.synesis.poc.pdf;
import javax.swing.*;
import java.awt.*;
import static dev.synesis.poc.pdf.HomeAssistantMotionTest.*;
/** The actual assistant scroll pane must retain fractional input and animation modes. */
public final class HomeAssistantScrollTest {
 public static void main(String[] args)throws Exception{
  SwingUtilities.invokeAndWait(()->{
   HomeAssistant assistant=new HomeAssistant();
   try{
    JScrollPane pane=(JScrollPane)get(assistant,"scroll");JPanel view=new JPanel();view.setPreferredSize(new Dimension(150,5000));pane.setViewportView(view);pane.setSize(240,180);pane.doLayout();pane.getViewport().doLayout();
    JScrollBar bar=pane.getVerticalScrollBar();check(bar.getUnitIncrement(1)==6,"chat matches home wheel speed");int mode=pane.getViewport().getScrollMode();
    for(int i=0;i<100;i++)TrackpadScrollTest.wheel(pane,.01);
    check(bar.getValue()==18,"chat preserves subpixel trackpad distance at home speed");
    for(int i=0;i<100;i++)TrackpadScrollTest.wheel(pane,-.01);
    check(bar.getValue()==0,"chat preserves reverse distance");
    bar.setValue(300);TrackpadScrollTest.wheel(pane,.5);check(bar.getValue()==309,"manual scroll resets accumulator");
    check(pane.getViewport().getScrollMode()==mode,"normal painting mode unchanged");
    pane.getViewport().setScrollMode(JViewport.SIMPLE_SCROLL_MODE);TrackpadScrollTest.wheel(pane,.5);
    check(pane.getViewport().getScrollMode()==JViewport.SIMPLE_SCROLL_MODE,"temporary bubble animation mode unchanged");
    System.out.println("HomeAssistantScrollTest OK · fractional/reverse input, manual position, animation paint modes");
   }catch(Exception e){throw new RuntimeException(e);}finally{assistant.close();}
  });
 }
}
