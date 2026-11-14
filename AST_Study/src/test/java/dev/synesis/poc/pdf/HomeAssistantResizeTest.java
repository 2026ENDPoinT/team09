package dev.synesis.poc.pdf;
import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import static dev.synesis.poc.pdf.HomeAssistantMotionTest.*;
/** Geometry and mouse routing only; no live window, network or generated content. */
public final class HomeAssistantResizeTest {
 public static void main(String[] args)throws Exception{
  SwingUtilities.invokeAndWait(()->{
   HomeAssistant view=new HomeAssistant();
   try{
    view.setSize(1600,1000);set(view,"expanded",true);set(view,"loaded",true);
    JPanel card=(JPanel)get(view,"card");card.setVisible(true);view.doLayout();
    JComponent grip=(JComponent)get(view,"resizeGrip");Rectangle initial=card.getBounds();
    check(initial.width==460&&initial.height==640,"default size");check(grip.isVisible(),"grip visible");
    check(view.getComponentAt(grip.getX()+6,grip.getY()+6)==grip,"grip receives mouse above card");
    event(grip,MouseEvent.MOUSE_PRESSED,5,5);event(grip,MouseEvent.MOUSE_DRAGGED,-195,-95);event(grip,MouseEvent.MOUSE_RELEASED,5,5);
    Rectangle enlarged=card.getBounds();check(enlarged.width==660&&enlarged.height==740,"grow up and left");
    check(enlarged.x+enlarged.width==initial.x+initial.width&&enlarged.y+enlarged.height==initial.y+initial.height,"bottom right stays anchored");
    event(grip,MouseEvent.MOUSE_PRESSED,5,5);event(grip,MouseEvent.MOUSE_DRAGGED,2005,2005);event(grip,MouseEvent.MOUSE_RELEASED,5,5);
    check(card.getWidth()==460&&card.getHeight()==640,"minimum size enforced");
    event(grip,MouseEvent.MOUSE_PRESSED,5,5);event(grip,MouseEvent.MOUSE_DRAGGED,-9999,-9999);event(grip,MouseEvent.MOUSE_RELEASED,5,5);
    check(card.getX()>=0&&card.getY()>=0&&card.getWidth()==750&&card.getHeight()<=888,"clamped within host");
    view.setSize(1800,1400);view.doLayout();
    event(grip,MouseEvent.MOUSE_PRESSED,5,5);event(grip,MouseEvent.MOUSE_DRAGGED,-9999,-9999);event(grip,MouseEvent.MOUSE_RELEASED,5,5);
    check(card.getWidth()==750&&card.getHeight()==940,"maximum dimensions enforced on large host");
    set(view,"orbCenter",new Point(900,1100));set(view,"cardAnchor",new Point(200,100));view.doLayout();
    JComponent southeast=(JComponent)get(view,"resizeGripSE"),orb=(JComponent)get(view,"orb");
    Point orbBefore=orb.getLocation();Rectangle cardBefore=card.getBounds();
    event(southeast,MouseEvent.MOUSE_PRESSED,5,5);event(southeast,MouseEvent.MOUSE_DRAGGED,-95,-75);event(southeast,MouseEvent.MOUSE_RELEASED,5,5);
    check(orb.getX()==orbBefore.x-100&&orb.getY()==orbBefore.y-80,"orb follows southeast corner");
    check(card.getLocation().equals(cardBefore.getLocation()),"southeast drag preserves top left");
    event(southeast,MouseEvent.MOUSE_PRESSED,5,5);event(southeast,MouseEvent.MOUSE_DRAGGED,900,900);event(southeast,MouseEvent.MOUSE_RELEASED,5,5);
    check(orb.getLocation().equals(orbBefore),"orb follows actual movement at size limit");
    set(view,"expanded",false);view.doLayout();check(!grip.isVisible(),"closed grip hidden");
    System.out.println("HomeAssistantResizeTest OK · drag, minimum, anchor, bounds, input routing");
   }catch(Exception e){throw new RuntimeException(e);}finally{view.close();}
  });
 }
 private static void event(JComponent c,int type,int x,int y){c.dispatchEvent(new MouseEvent(c,type,System.currentTimeMillis(),type==MouseEvent.MOUSE_DRAGGED?MouseEvent.BUTTON1_DOWN_MASK:0,x,y,1,false,type==MouseEvent.MOUSE_DRAGGED?MouseEvent.NOBUTTON:MouseEvent.BUTTON1));}
}
