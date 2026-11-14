package dev.synesis.poc.ui;

import dev.synesis.poc.pdf.HomeAssistant;
import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.util.Arrays;

/** Real offscreen icon paints: fractional growth, bounded textures and no idle orb repaint loop. */
public final class AvatarHoverMotionTest {
    public static void main(String[] args)throws Exception {
        System.setProperty("synesis.dataRoot",Files.createTempDirectory("avatar-hover-").toString());
        SwingUtilities.invokeAndWait(()->{try{deceleration();fractionalPaints();homeIdle();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS AvatarHoverMotion: deceleration/reversal, fractional icon growth, fixed device textures, idle home timer and hover restart");
        System.exit(0);
    }
    private static void deceleration(){
        float value=0,previousStep=Float.MAX_VALUE;
        for(int i=0;i<12;i++){
            float next=HoverMotion.advance(value,true,1/60f),step=next-value;
            check(step>0&&step<previousStep&&next<1,"hover does not decelerate continuously");previousStep=step;value=next;
        }
        float reversed=HoverMotion.advance(value,false,1/60f);
        check(reversed>0&&reversed<value,"hover reversal jumps directly to endpoint");
        for(int i=0;i<120;i++)value=HoverMotion.advance(value,true,1/60f);
        check(value==1,"hover never settles at full size");
        for(int i=0;i<120;i++)value=HoverMotion.advance(value,false,1/60f);
        check(value==0,"hover never settles at rest");
    }
    private static void fractionalPaints()throws Exception {
        FloatingMentor mentor=new FloatingMentor();mentor.setSize(1200,800);mentor.doLayout();
        try{
            JComponent orb=(JComponent)field(mentor,FloatingMentor.class,"orb");
            BufferedImage canvas=new BufferedImage(orb.getWidth()*2,orb.getHeight()*2,BufferedImage.TYPE_INT_ARGB);
            Graphics2D g=canvas.createGraphics();g.scale(2,2);
            set(mentor,FloatingMentor.class,"hover",.400f);orb.paint(g);int[] first=canvas.getRGB(0,0,canvas.getWidth(),canvas.getHeight(),null,0,canvas.getWidth());
            g.setComposite(AlphaComposite.Clear);g.fillRect(0,0,orb.getWidth(),orb.getHeight());g.setComposite(AlphaComposite.SrcOver);
            set(mentor,FloatingMentor.class,"hover",.401f);orb.paint(g);int[] next=canvas.getRGB(0,0,canvas.getWidth(),canvas.getHeight(),null,0,canvas.getWidth());
            check(!Arrays.equals(first,next),"fractional hover still rounds to the same integer-size frame");
            Object art=staticField(MentorAvatar.class,"ART"),texture=field(art,AvatarRaster.class,"raster");
            for(int i=0;i<=100;i++){set(mentor,FloatingMentor.class,"hover",i/100f);orb.paint(g);check(field(art,AvatarRaster.class,"raster")==texture,"mentor allocates a texture at every hover size");}
            AssistantAvatar.paint(g,53,53,48);Object assistant=staticField(AssistantAvatar.class,"ART"),assistantTexture=field(assistant,AvatarRaster.class,"raster");
            for(int i=0;i<=100;i++){AssistantAvatar.paint(g,53,53,48+30*i/100d);check(field(assistant,AvatarRaster.class,"raster")==assistantTexture,"assistant allocates a texture at every hover size");}
            check(((BufferedImage)texture).getWidth()<=384&&((BufferedImage)assistantTexture).getWidth()<=384,"avatar texture is unbounded");
            g.dispose();canvas.flush();
        }finally{mentor.close();}
    }
    private static void homeIdle()throws Exception {
        JPanel root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};
        HomeAssistant home=new HomeAssistant();root.add(home);root.setSize(1200,800);root.addNotify();root.doLayout();
        RepaintManager previous=RepaintManager.currentManager(home);
        try{
            home.setSize(1200,800);home.doLayout();set(home,HomeAssistant.class,"loaded",true);
            JComponent orb=(JComponent)field(home,HomeAssistant.class,"orb");Timer timer=(Timer)field(home,HomeAssistant.class,"motion");
            int[] paints={0};RepaintManager.setCurrentManager(new RepaintManager(){@Override public void addDirtyRegion(JComponent c,int x,int y,int w,int h){if(c==orb)paints[0]++;}});
            hoverEvent(orb,MouseEvent.MOUSE_ENTERED);check(timer.isRunning(),"hover did not wake the idle assistant");
            for(int i=0;i<100;i++)tick(home);
            check(!timer.isRunning(),"closed assistant keeps an idle frame timer");
            int settled=paints[0];for(int i=0;i<10;i++)tick(home);
            check(paints[0]==settled,"unchanged assistant still requests icon paints");
            hoverEvent(orb,MouseEvent.MOUSE_EXITED);check(timer.isRunning(),"hover exit did not restart shrinking");
            for(int i=0;i<100;i++)tick(home);check(!timer.isRunning(),"shrinking leaves an idle frame timer");
        }finally{home.close();root.removeNotify();RepaintManager.setCurrentManager(previous);}
    }
    private static void tick(HomeAssistant home)throws Exception {
        set(home,HomeAssistant.class,"lastTick",System.nanoTime()-16_000_000L);
        Method method=HomeAssistant.class.getDeclaredMethod("animate");method.setAccessible(true);method.invoke(home);
    }
    private static void hoverEvent(JComponent c,int id){MouseEvent e=new MouseEvent(c,id,System.currentTimeMillis(),0,20,20,20,20,0,false,MouseEvent.NOBUTTON);for(MouseListener listener:c.getMouseListeners()){if(id==MouseEvent.MOUSE_ENTERED)listener.mouseEntered(e);else listener.mouseExited(e);}}
    private static Object staticField(Class<?> type,String name)throws Exception {Field f=type.getDeclaredField(name);f.setAccessible(true);return f.get(null);}
    private static Object field(Object owner,Class<?> type,String name)throws Exception {Field f=type.getDeclaredField(name);f.setAccessible(true);return f.get(owner);}
    private static void set(Object owner,Class<?> type,String name,Object value)throws Exception {Field f=type.getDeclaredField(name);f.setAccessible(true);f.set(owner,value);}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}
