package dev.synesis.poc.pdf;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.concurrent.*;
/** Fake probe only: never contacts a network endpoint. */
public final class AssistantConnectivityTest {
 public static void main(String[] args)throws Exception{
  CountDownLatch changed=new CountDownLatch(1);AssistantConnectivity[] label=new AssistantConnectivity[1];
  SwingUtilities.invokeAndWait(()->{
   label[0]=new AssistantConnectivity(()->{if(SwingUtilities.isEventDispatchThread())throw new AssertionError("probe on EDT");return true;});
   label[0].addPropertyChangeListener("text",e->{if("Online".equals(e.getNewValue()))changed.countDown();});
   label[0].monitor(true);label[0].monitor(true);
  });
  try{
   if(!changed.await(3,TimeUnit.SECONDS))throw new AssertionError("probe did not publish online state");
   SwingUtilities.invokeAndWait(()->{
    check(label[0].getText().equals("Online"),"online label");color(label[0],0x45DA8C);
    label[0].monitor(false);label[0].showOnline(false);
    check(label[0].getText().equals("Offline"),"offline label");color(label[0],0xef6a75);
    label[0].close();label[0].monitor(true);
   });
  }finally{SwingUtilities.invokeAndWait(()->label[0].close());}
  System.out.println("AssistantConnectivityTest OK: asynchronous probe, online/offline labels and dot colors, lifecycle cleanup");
 }
 private static void color(JLabel label,int expected){BufferedImage image=new BufferedImage(label.getIcon().getIconWidth(),label.getIcon().getIconHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();label.getIcon().paintIcon(label,g,0,0);g.dispose();check((image.getRGB(image.getWidth()/2,image.getHeight()/2)&0xffffff)==expected,"dot color");image.flush();}
 private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
