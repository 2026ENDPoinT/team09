package dev.synesis.poc.pdf;
import java.awt.*;
import javax.swing.*;
import static dev.synesis.poc.pdf.HomeAssistantMotionTest.*;
/** Counts size mutations directly, independent of machine speed or live UI. */
public final class HomeAssistantLayoutPerformanceTest {
 static final class BoundsProbe extends JPanel {
  int changes;
  @Override public void setBounds(int x,int y,int width,int height){if(getWidth()!=width||getHeight()!=height)changes++;super.setBounds(x,y,width,height);}
 }
 public static void main(String[] args)throws Exception{
  SwingUtilities.invokeAndWait(()->{
   HomeAssistant view=new HomeAssistant();
   try{
    view.setSize(1800,1100);set(view,"requestedCardWidth",1400);set(view,"requestedCardHeight",850);view.doLayout();
    JPanel card=(JPanel)get(view,"card");BorderLayout layout=(BorderLayout)card.getLayout();Component previous=layout.getLayoutComponent(BorderLayout.SOUTH);card.remove(previous);
    BoundsProbe probe=new BoundsProbe();probe.setPreferredSize(new Dimension(400,120));card.add(probe,BorderLayout.SOUTH);
    card.doLayout();probe.changes=0;
    for(int i=0;i<200;i++)card.doLayout();
    System.out.println("stable-layout size changes="+probe.changes+" / 200 passes");
    if(!Boolean.getBoolean("synesis.layoutBaseline"))check(probe.changes==0,"stable centered layout must not resize children");
    check(probe.getWidth()==650,"reading column capped at 650px");
    for(int[] sample:new int[][]{{460,16},{579,20},{698,24},{920,135},{1400,375}}){
     card.setSize(sample[0],850);card.doLayout();
     check(probe.getX()==sample[1]&&card.getWidth()-probe.getX()-probe.getWidth()==sample[1],"responsive symmetric gutters");
    }
    probe.changes=0;
    for(int w=1000;w<=1400;w+=10){card.setSize(w,850);card.doLayout();}
    if(!Boolean.getBoolean("synesis.layoutBaseline"))check(probe.changes==0,"wide-card resizing must not reflow the capped column");
    System.out.println("HomeAssistantLayoutPerformanceTest OK");
   }catch(Exception e){throw new RuntimeException(e);}finally{view.close();}
  });
 }
}
