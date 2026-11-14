package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;

/** Run with -Xmx128m: rapid mixed-mode transitions, bounded memory and vector parity at strip seams. */
public final class LoginTransitionMemoryTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try {
            for(int scale:new int[]{1,2}) {
                LoginPanel panel=new LoginPanel(()->{});panel.setSize(1360,850);layout(panel);
                Object paper=get(panel,"paper");for(int i=0;i<160;i++)call(paper,"updateDots",new Class<?>[]{double.class},.033);
                BufferedImage image=new BufferedImage(1360*scale,850*scale,BufferedImage.TYPE_INT_RGB);
                BufferedImage expected=new BufferedImage(320*scale,400*scale,BufferedImage.TYPE_INT_RGB);
                Graphics2D g=image.createGraphics();g.scale(scale,scale);panel.printAll(g);
                LoginWaveRaster strip=(LoginWaveRaster)get(paper,"waveRaster");
                if(strip==null || (long)strip.width*strip.height*4>2*1024*1024)throw new AssertionError("Wave buffer exceeded 2MiB budget");
                for(int frame=0;frame<160;frame++) {
                    if(frame%40==0)call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
                    if(frame%40==20)call(paper,"followPointer",new Class<?>[]{Point.class},new Point(680,425));
                    call(paper,"updateDots",new Class<?>[]{double.class},.033);panel.printAll(g);
                    if(get(paper,"waveRaster")!=strip)throw new AssertionError("A mode switch recreated the pixel buffer");
                    double blend=(double)get(paper,"waveBlend");
                    if(blend>0 && !(boolean)call(paper,"prepareWaveStamps",new Class<?>[]{double.class,double.class},(double)scale,(double)scale))
                        throw new AssertionError("Mixed mode abandoned the fast renderer");
                    if(frame%10==5) {
                        Graphics2D vector=expected.createGraphics();vector.scale(scale,scale);
                        vector.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                        vector.drawImage((BufferedImage)get(paper,"cachedSurface"),0,0,1360,850,null);
                        call(paper,"paintVectorDots",new Class<?>[]{Graphics2D.class,int.class,int.class,Rectangle.class},vector,1360,850,new Rectangle(0,0,320,400));
                        vector.dispose();
                        for(int y=0;y<expected.getHeight();y++)for(int x=0;x<expected.getWidth();x++) {
                            int a=expected.getRGB(x,y),b=image.getRGB(x,y);
                            for(int channel=0;channel<24;channel+=8)if(Math.abs(((a>>channel)&255)-((b>>channel)&255))>2)
                                throw new AssertionError("Mixed-mode vector mismatch / strip seam at "+x+","+y+" frame="+frame+" scale="+scale);
                        }
                    }
                }
                g.dispose();call(paper,"releaseSurface");
                if(get(paper,"waveRaster")!=null)throw new AssertionError("Hidden login retained strip");
            }
        }catch(Exception error){throw new RuntimeException(error);}});
        System.out.println("PASS: 320 transitions frames at 1x/2x, <=2MiB reused strip, mixed-mode vector parity including seams, hidden-cache release");
    }
    private static Object get(Object obj,String name)throws Exception{Field f=obj.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(obj);}
    private static Object call(Object obj,String name)throws Exception{return call(obj,name,new Class<?>[0]);}
    private static Object call(Object obj,String name,Class<?>[] types,Object...args)throws Exception{Method m=obj.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(obj,args);}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
}
