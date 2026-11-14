package dev.synesis.poc.ui;
import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.lang.reflect.*;
/** No native window: count rich content captures during a slow resize and time menu commit. */
public final class MotionWorkBudgetTest {
 static FloatingMentor mentor;static JPanel root;static JComponent grip;static Counter content;static StudyColumns columns;static JPanel a,b;static long start,commit;static boolean baseline;
 static class Counter extends JPanel {int paints;protected void paintComponent(Graphics g){paints++;super.paintComponent(g);}}
 public static void main(String[] args)throws Exception{
  baseline=args.length>0;
  edt(()->{root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};mentor=new FloatingMentor();root.add(mentor);root.setSize(1300,1000);root.addNotify();content=new Counter();content.add(new JLabel("unchanged rich content"));mentor.setContent(content);layout(root);mentor.setOpen(true,false);layout(root);content.paints=0;grip=(JComponent)get(mentor,"southeast");mouse(MouseEvent.MOUSE_PRESSED,5,5);});
  for(int i=1;i<=4;i++){final int step=i;edt(()->{mouse(MouseEvent.MOUSE_DRAGGED,5-step*12,5-step*15);call(mentor,"tick");});Thread.sleep(100);}
  edt(()->mouse(MouseEvent.MOUSE_RELEASED,-43,-55));Thread.sleep(320);
  edt(()->{System.out.println("resizeContentPaints="+content.paints);if(!baseline&&content.paints>2)throw new AssertionError("rich content recaptured before release");mentor.close();root.removeNotify();
   root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};columns=new StudyColumns();a=new JPanel();b=new JPanel();columns.register("A","A",a);columns.register("B","B",b);root.add(columns);root.setSize(900,650);root.addNotify();layout(root);columns.open("A");layout(root);start=System.nanoTime();columns.select(0,"B");Timer poll=new Timer(2,null);poll.addActionListener(e->{if(b.getParent()!=null){commit=System.nanoTime();poll.stop();}});poll.start();});
  Thread.sleep(350);edt(()->{System.out.printf("menuCommitMs=%.2f%n",(commit-start)/1e6);columns.dispose();root.removeNotify();});System.exit(0);
 }
 static Object get(Object o,String k){try{Field f=o.getClass().getDeclaredField(k);f.setAccessible(true);return f.get(o);}catch(Exception e){throw new RuntimeException(e);}}
 static void call(Object o,String k){try{Method m=o.getClass().getDeclaredMethod(k);m.setAccessible(true);m.invoke(o);}catch(Exception e){throw new RuntimeException(e);}}
 static void mouse(int id,int x,int y){grip.dispatchEvent(new MouseEvent(grip,id,System.currentTimeMillis(),0,x,y,x,y,1,false,MouseEvent.BUTTON1));}
 static void edt(Runnable r)throws Exception{SwingUtilities.invokeAndWait(r);}
 static void layout(Container c){c.doLayout();for(Component x:c.getComponents())if(x.isVisible()&&x instanceof Container n)layout(n);}
}
