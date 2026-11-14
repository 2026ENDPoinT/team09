package dev.synesis.poc.pdf;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;

/** No window or API: closing, reversal, shadow and transient-buffer ownership. */
public final class HomeAssistantMotionTest {
    static Object get(Object o,String n)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String n,Object v)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);f.set(o,v);}
    static void call(Object o,String n,Class<?>[] types,Object... args)throws Exception{Method m=o.getClass().getDeclaredMethod(n,types);m.setAccessible(true);m.invoke(o,args);}
    static void check(boolean b,String reason){if(!b)throw new AssertionError(reason);}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{
            HomeAssistant view=new HomeAssistant();
            try{
                view.setSize(1120,800);set(view,"loaded",true);view.doLayout();
                JPanel openingCard=(JPanel)get(view,"card");
                call(view,"toggle",new Class[]{});
                call(view,"advanceCard",new Class[]{float.class},.10f);
                check((float)get(view,"contentOpening")==0,"contents started before background finished");
                call(view,"advanceCard",new Class[]{float.class},.10f);
                check((float)get(view,"opening")==1&&(float)get(view,"contentOpening")==0,"background completion did not precede contents");
                call(view,"advanceCard",new Class[]{float.class},.08f);layout(view);
                BufferedImage openingImage=new BufferedImage(1120,800,BufferedImage.TYPE_INT_ARGB);
                Graphics2D openingGraphics=openingImage.createGraphics();view.printAll(openingGraphics);openingGraphics.dispose();
                Object contentCache=get(openingCard,"contentSnapshot");check(contentCache!=null,"content fade lacks cached frame");
                openingGraphics=openingImage.createGraphics();view.printAll(openingGraphics);openingGraphics.dispose();
                check(get(openingCard,"contentSnapshot")==contentCache,"content snapshot rebuilt each frame");
                call(view,"advanceCard",new Class[]{float.class},.08f);openingImage.flush();
                check((float)get(view,"contentOpening")==1&&get(openingCard,"contentSnapshot")==null,"content fade did not finish and release buffer");
                view.setSize(1120,800);set(view,"loaded",true);set(view,"expanded",true);
                JPanel card=(JPanel)get(view,"card");card.setVisible(true);for(int i=0;i<3;i++)layout(view);
                BufferedImage img=new BufferedImage(1120,800,BufferedImage.TYPE_INT_ARGB);Graphics2D g=img.createGraphics();view.printAll(g);g.dispose();
                check((img.getRGB(card.getX()-6,card.getY()+card.getHeight()/2)>>>24)>0,"shadow absent outside card");img.flush();
                call(view,"toggle",new Class[]{});check(card.isVisible(),"closing instantly hides card");
                Object snapshot=get(card,"closingSnapshot");check(snapshot!=null,"closing snapshot missing");
                int startY=card.getY();call(view,"advanceCard",new Class[]{float.class},.06f);
                check(card.isVisible()&&card.getY()>startY,"close does not move down gradually");
                check(get(card,"closingSnapshot")==snapshot,"frame rebuilt closing snapshot");
                check(view.getComponentAt(card.getX()+20,card.getY()+20)==view,"frozen controls still accept clicks");
                float midway=(float)get(view,"opening");call(view,"toggle",new Class[]{});
                check((float)get(view,"opening")==midway,"reversal jumps opacity");check(get(card,"closingSnapshot")==null,"reopen keeps stale snapshot");
                call(view,"advanceCard",new Class[]{float.class},1f);check((float)get(view,"opening")==1,"reopen never completes");
                call(view,"toggle",new Class[]{});call(view,"advanceCard",new Class[]{float.class},1f);
                check(!card.isVisible()&&get(card,"closingSnapshot")==null,"closed card retains buffer");
                check(!view.contains(card.getX()+20,card.getY()+20),"closed card blocks home");
                for(int i=0;i<12;i++){call(view,"toggle",new Class[]{});call(view,"advanceCard",new Class[]{float.class},1f);call(view,"toggle",new Class[]{});call(view,"advanceCard",new Class[]{float.class},1f);check(get(card,"closingSnapshot")==null,"repeated close leaks snapshots");}
                call(view,"toggle",new Class[]{});call(view,"advanceCard",new Class[]{float.class},1f);call(view,"toggle",new Class[]{});view.setHomeVisible(false);
                check(!card.isVisible()&&get(card,"closingSnapshot")==null,"home departure retains closing buffer");
                System.out.println("HomeAssistantMotionTest OK · shadow, smooth close/reverse, click isolation, 12 cycles, buffer release");
            }catch(Exception e){throw new RuntimeException(e);}finally{view.close();}
        });
    }
}
