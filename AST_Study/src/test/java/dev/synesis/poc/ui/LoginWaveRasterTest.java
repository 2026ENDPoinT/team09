package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;

/** Exercise the actual paint branch, its lifetime and input cadence without opening an app. */
public final class LoginWaveRasterTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try {
            for(int scale:new int[]{1,2}) {
                LoginPanel panel=new LoginPanel(()->{});panel.setSize(1000,700);layout(panel);
                Object paper=get(panel,"paper");
                call(paper,"followPointer",new Class<?>[]{Point.class},new Point(-1000,-1000));
                for(int i=0;i<160;i++)step(paper);
                set(paper,"waveBlend",.5d); // Exercise the transitional strip as well as the steady atlas.
                BufferedImage optimized=paint(panel,scale);
                Object raster=get(paper,"waveRaster");check(raster!=null,"steady wave did not use optimized paint");
                BufferedImage original=new BufferedImage(1000*scale,700*scale,BufferedImage.TYPE_INT_RGB);
                Graphics2D baseline=original.createGraphics();
                baseline.scale(scale,scale);baseline.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                baseline.drawImage((BufferedImage)get(paper,"cachedSurface"),0,0,1000,700,null);
                call(paper,"paintVectorDots",new Class<?>[]{Graphics2D.class,int.class,int.class,Rectangle.class},baseline,1000,700,new Rectangle(0,0,1000,700));
                baseline.dispose();
                int maxError=0;
                for(int y=0;y<original.getHeight()-60*scale;y++)for(int x=0;x<150*scale;x++) {
                    int a=original.getRGB(x,y),b=optimized.getRGB(x,y);
                    for(int channel=0;channel<24;channel+=8)maxError=Math.max(maxError,Math.abs(((a>>channel)&255)-((b>>channel)&255)));
                }
                check(maxError<=2,"full login render changed: max channel difference "+maxError);
                set(paper,"waveBlend",1d);step(paper);paint(panel,scale);
                check(get(paper,"wavePattern")!=null,"steady wave did not use its reusable row atlas");
                check(get(paper,"waveRaster")==raster,"wave allocated a new screen buffer each frame");
                call(panel,"tick",new Class<?>[0]);
                check(((Timer)get(panel,"animation")).getDelay()==33,"repeating wave did not reduce refresh rate");
                panel.loginButton().getModel().setRollover(true);call(panel,"tick",new Class<?>[0]);
                check(((Timer)get(panel,"animation")).getDelay()==16,"button animation lost responsive cadence");
                call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
                for(int i=0;i<160;i++)step(paper);paint(panel,scale);
                LoginWaveRaster retained=(LoginWaveRaster)get(paper,"waveRaster");
                check(retained==raster && retained.height<=128 && (long)retained.width*retained.height*4<=2*1024*1024,
                    "pointer mode must retain only the bounded reusable strip");
                call(paper,"releaseSurface",new Class<?>[0]);
                for(Object stamp:(Object[])get(paper,"waveStamps"))check(stamp==null,"hidden login retained dot caches");
                check(get(paper,"waveRaster")==null,"hidden login retained wave buffer");
            }
        }catch(Exception error){throw new RuntimeException(error);}});
        System.out.println("PASS: strip/vector parity, reused bounded buffer, 30fps wave / 60fps button, pointer cache reuse and hidden-cache release at 1x/2x");
    }
    private static void step(Object paper)throws Exception{call(paper,"updateDots",new Class<?>[]{double.class},.033);}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static Object get(Object obj,String name)throws Exception{Field field=obj.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(obj);}
    private static void set(Object obj,String name,Object value)throws Exception{Field field=obj.getClass().getDeclaredField(name);field.setAccessible(true);field.set(obj,value);}
    private static Object call(Object obj,String name,Class<?>[] types,Object...args)throws Exception{Method method=obj.getClass().getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(obj,args);}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static BufferedImage paint(JComponent component,int scale){BufferedImage image=new BufferedImage(component.getWidth()*scale,component.getHeight()*scale,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();try{g.scale(scale,scale);component.printAll(g);}finally{g.dispose();}return image;}
}
