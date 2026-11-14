package dev.synesis.poc.pdf;
import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import static dev.synesis.poc.pdf.HomeAssistantMotionTest.*;
/** Offline pointer geometry; no app window, network or persisted positions. */
public final class HomeAssistantOrbDragTest {
 public static void main(String[] args)throws Exception{SwingUtilities.invokeAndWait(()->{
  HomeAssistant view=new HomeAssistant();
  try{
   view.setSize(1600,1000);set(view,"loaded",true);view.doLayout();
   JComponent orb=(JComponent)get(view,"orb");
   event(orb,MouseEvent.MOUSE_PRESSED,178,40);event(orb,MouseEvent.MOUSE_DRAGGED,-964,-712);event(orb,MouseEvent.MOUSE_RELEASED,178,40);event(orb,MouseEvent.MOUSE_CLICKED,178,40);
   Point center=(Point)get(view,"orbCenter");check(center.equals(new Point(400,200)),"orb follows pointer displacement");
   check(!(boolean)get(view,"expanded"),"drag opens chat accidentally");
   event(orb,MouseEvent.MOUSE_PRESSED,178,40);event(orb,MouseEvent.MOUSE_RELEASED,178,40);event(orb,MouseEvent.MOUSE_CLICKED,178,40);
   check((boolean)get(view,"expanded"),"click after drag must open chat");
   set(view,"opening",1f);set(view,"contentOpening",1f);view.doLayout();
   JPanel card=(JPanel)get(view,"card");Rectangle before=card.getBounds();
   check(before.x==444&&before.y==240,"chat opens beside moved orb");
   JComponent corner=(JComponent)get(view,"resizeGripSE");check(corner.isVisible(),"southeast resize handle visible");
   check(view.getComponentAt(corner.getX()+6,corner.getY()+6)==corner,"southeast handle receives pointer");
   event(corner,MouseEvent.MOUSE_PRESSED,5,5);event(corner,MouseEvent.MOUSE_DRAGGED,205,105);event(corner,MouseEvent.MOUSE_RELEASED,5,5);
   check(card.getX()==before.x&&card.getY()==before.y,"southeast resize keeps top left fixed");
   check(card.getWidth()==before.width+200&&card.getHeight()==before.height+100,"southeast resize grows both axes");
   set(view,"orbCenter",new Point(-100,-100));set(view,"cardAnchor",null);view.doLayout();
   check(((Point)get(view,"orbCenter")).equals(new Point(34,34)),"orb clamped inside viewport");
   check(card.getX()>=0&&card.getY()>=0&&card.getX()+card.getWidth()<=view.getWidth()&&card.getY()+card.getHeight()<=view.getHeight(),"chat stays inside viewport");
   for(int centerX:new int[]{34,400,1200,1566}){
    set(view,"orbCenter",new Point(centerX,200));set(view,"cardAnchor",null);view.doLayout();
    if(centerX==400)check(card.getX()>centerX+34,"orb outside chat on the left");
    if(centerX==1200)check(card.getX()+card.getWidth()<centerX-34,"orb outside chat on the right");
    if(centerX==34)check(card.getX()<=centerX,"left-edge corner docks inside the orb edge");
    if(centerX==1566)check(card.getX()+card.getWidth()>=centerX,"right-edge corner docks inside the orb edge");
   }
   var hintMethod=orb.getClass().getDeclaredMethod("hintBounds");hintMethod.setAccessible(true);
   for(int centerX:new int[]{34,400,1566}){
    set(view,"orbCenter",new Point(centerX,200));view.doLayout();
    Rectangle hint=(Rectangle)hintMethod.invoke(orb);
    Rectangle global=SwingUtilities.convertRectangle(orb,hint,view);
    check(global.x>=8&&global.x+global.width<=view.getWidth()-8,"hover hint stays inside padded viewport");
    check(hint.x>=0&&hint.x+hint.width<=orb.getWidth(),"hover hint is not clipped by the orb component");
    if(centerX==34)check(global.x>centerX+30,"left-edge hint opens to the right");
   }
   Rectangle stationary=card.getBounds();Point destination=new Point(stationary.x-120,stationary.y+24);
   set(view,"cardMoveX",(double)stationary.x);set(view,"cardMoveY",(double)stationary.y);set(view,"cardMoveTarget",destination);
   call(view,"advanceCardPosition",new Class[]{float.class},.016f);
   check(card.getX()<stationary.x&&card.getX()>destination.x,"reposition passes through intermediate locations");
   check(card.getSize().equals(stationary.getSize()),"reposition does not resize or reflow chat");
   for(int i=0;i<60;i++)call(view,"advanceCardPosition",new Class[]{float.class},.016f);
   check(card.getLocation().equals(destination)&&get(view,"cardMoveTarget")==null,"reposition settles and stops");
   System.out.println("HomeAssistantOrbDragTest OK: drag/click separation, nearby chat, southeast resize, edge clamping");
  }catch(Exception e){throw new RuntimeException(e);}finally{view.close();}
 });}
 private static void event(JComponent c,int type,int x,int y){c.dispatchEvent(new MouseEvent(c,type,System.currentTimeMillis(),type==MouseEvent.MOUSE_DRAGGED?MouseEvent.BUTTON1_DOWN_MASK:0,x,y,1,false,type==MouseEvent.MOUSE_DRAGGED?MouseEvent.NOBUTTON:MouseEvent.BUTTON1));}
}
