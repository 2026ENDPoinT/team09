package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.lang.reflect.*;

/** No window or provider: phase direction/period and the real hover animation state. */
public final class LoginDiagonalWaveTest {
    public static void main(String[] args)throws Exception {
        double spacing=LoginPanel.WAVE_SPACING,speed=LoginPanel.WAVE_SPEED;
        for(int i=0;i<200;i++) {
            double x=i*13.7,y=i*3.1,travel=i*.37;
            double value=LoginPanel.diagonalWave(x,y,travel);
            check(value>=0 && value<=1,"response outside existing size/color envelope");
            close(value,LoginPanel.diagonalWave(x,y,travel+spacing),"loop seam");
            double d=speed*.3/Math.sqrt(2);
            close(value,LoginPanel.diagonalWave(x+d,y-d,travel+speed*.3),"crest must travel right/up at fixed speed");
        }
        SwingUtilities.invokeAndWait(()->{try {
            LoginPanel panel=new LoginPanel(()->{});panel.setSize(1000,700);layout(panel);
            Object paper=get(panel,"paper");
            call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
            for(int i=0;i<30;i++)step(paper);
            check(anyOffset(paper),"normal pointer repulsion disappeared");
            Rectangle card=(Rectangle)get(paper,"cardBounds");
            call(paper,"followPointer",new Class<?>[]{Point.class},new Point((int)card.getCenterX(),(int)card.getCenterY()));
            double phase=(double)get(paper,"waveTravel");
            step(paper);close((phase+.016*speed)%spacing,(double)get(paper,"waveTravel"),"nonlinear phase advance");
            for(int i=0;i<130;i++)step(paper);
            check(!anyOffset(paper),"wave moved the dot positions");
            double[] responses=(double[])get(paper,"dotResponses");double[] before=responses.clone();
            for(int i=0;i<20;i++)step(paper);
            boolean changed=false;for(int i=0;i<before.length;i++)changed|=Math.abs(before[i]-responses[i])>.05;
            check(changed,"stationary pointer stopped the travelling size wave");
            call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
            for(int i=0;i<130;i++)step(paper);
            check(anyOffset(paper),"leaving card failed to restore mouse response");
            call(paper,"followPointer",new Class<?>[]{Point.class},new Point(-1000,-1000));
            for(int i=0;i<160;i++)step(paper);
            check(call(paper,"updateDots",new Class<?>[]{double.class},.016)!=null,"leaving window did not keep wave active");
            check(!anyOffset(paper),"outside-window wave translated dots");
            call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
            for(int i=0;i<160;i++)step(paper);
            check(anyOffset(paper),"re-entering window failed to restore pointer response");
            check(call(paper,"updateDots",new Class<?>[]{double.class},.016)==null,"stationary pointer cannot settle after re-entry");
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: seamless phase, linear up-right propagation, fixed dot positions, live hover wave and restored pointer/idle behavior");
    }
    private static boolean anyOffset(Object paper)throws Exception {
        for(String name:new String[]{"dotOffsetX","dotOffsetY"})for(double value:(double[])get(paper,name))if(Math.abs(value)>.001)return true;
        return false;
    }
    private static void step(Object paper)throws Exception{call(paper,"updateDots",new Class<?>[]{double.class},.016);}
    private static void close(double a,double b,String reason){check(Math.abs(a-b)<1e-10,reason);}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static Object get(Object obj,String name)throws Exception{Field field=obj.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(obj);}
    private static Object call(Object obj,String name,Class<?>[] types,Object...args)throws Exception{Method method=obj.getClass().getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(obj,args);}
    private static void layout(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container nested)layout(nested);}
}
