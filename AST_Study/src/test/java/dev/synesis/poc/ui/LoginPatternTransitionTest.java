package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Actual login paint/update path, with deterministic pointer transitions and no window or login action. */
public final class LoginPatternTransitionTest {
    public static void main(String[] args)throws Exception {
        Path output=Path.of(args[0]);Files.createDirectories(output);
        boolean baseline=Arrays.asList(args).contains("--baseline");
        java.util.List<String> metrics=new ArrayList<>();
        SwingUtilities.invokeAndWait(()->{try {
            if(!baseline)verifySchedulingAndBrightness();
            for(int scale:new int[]{1,2}) {
                LoginPanel panel=new LoginPanel(()->{throw new AssertionError("No login action in paint test");});
                if(!baseline&&((javax.swing.Timer)get(panel,"animation")).getDelay()!=42)
                    throw new AssertionError("Resting wave must use the 24fps schedule");
                panel.setAnimationPaused(true);panel.setSize(1360,822);layout(panel);
                Object paper=get(panel,"paper");
                BufferedImage image=new BufferedImage(1360*scale,822*scale,BufferedImage.TYPE_INT_RGB);
                Graphics2D g=image.createGraphics();g.scale(scale,scale);
                try {
                    panel.paint(g);
                    Object surface=get(paper,"cachedSurface");
                    for(int i=0;i<35;i++){step(paper,.033);panel.paint(g);}
                    for(String mode:new String[]{"wave","to-pointer","moving-pointer","to-wave"}) {
                        if(mode.equals("to-pointer")) {
                            follow(paper,220,380);
                            if(!baseline&&((javax.swing.Timer)get(panel,"animation")).getDelay()!=16)throw new AssertionError("Pointer must retain 60fps");
                        }
                        if(mode.equals("to-wave")) {
                            follow(paper,-1000,-1000);
                            if(!baseline&&((javax.swing.Timer)get(panel,"animation")).getDelay()!=42)throw new AssertionError("Wave must return to 24fps");
                        }
                        long wall=0,cpu=0;var bean=ManagementFactory.getThreadMXBean();
                        for(int frame=0;frame<36;frame++) {
                            if(mode.equals("moving-pointer"))follow(paper,180+frame*8,360+(frame%8)*5);
                            long start=System.nanoTime(),cpuStart=bean.getCurrentThreadCpuTime();
                            Rectangle dirty=(Rectangle)call(paper,"updateDots",new Class<?>[]{double.class},.033);
                            g.setClip(dirty==null?new Rectangle():dirty);panel.paint(g);g.setClip(null);
                            cpu+=bean.getCurrentThreadCpuTime()-cpuStart;wall+=System.nanoTime()-start;
                            if(frame==0||frame==7||frame==35)ImageIO.write(image,"png",output.resolve(mode+"-"+frame+"-"+scale+"x.png").toFile());
                            if(get(paper,"cachedSurface")!=surface)throw new AssertionError("Motion rebuilt the gradient image");
                        }
                        String row=String.format(Locale.ROOT,"{\"scale\":%d,\"mode\":\"%s\",\"frames\":36,\"edtCpuMs\":%.3f,\"wallMs\":%.3f}",scale,mode,cpu/1e6,wall/1e6);
                        metrics.add(row);System.out.println(row);
                    }
                    call(paper,"releaseSurface",new Class<?>[0]);
                    if(get(paper,"wavePattern")!=null||get(paper,"cachedSurface")!=null)throw new AssertionError("Hidden login retained textures");
                }finally{g.dispose();}
            }
        }catch(Exception failure){throw new RuntimeException(failure);}});
        Files.writeString(output.resolve("metrics.json"),"[\n"+String.join(",\n",metrics)+"\n]\n");
        System.out.println("PASS: wave/pointer/transition geometry, reused static surface and release"+(baseline?" (reference)":", 60fps pointer and 24fps wave"));
    }
    private static void verifySchedulingAndBrightness()throws Exception {
        LoginPanel panel=new LoginPanel(()->{});panel.setAnimationPaused(true);panel.setSize(1360,822);layout(panel);
        Object paper=get(panel,"paper");follow(paper,220,380);
        Field blend=paper.getClass().getDeclaredField("waveBlend");blend.setAccessible(true);blend.setDouble(paper,.8);
        var timer=(javax.swing.Timer)get(panel,"animation");
        var old=RepaintManager.currentManager(panel);
        final int[] counts=new int[2];
        RepaintManager.setCurrentManager(new RepaintManager(){
            @Override public void addDirtyRegion(JComponent component,int x,int y,int width,int height){
                if(component==paper) {
                    if(width==1360&&height==822)counts[0]++;
                    else {counts[1]++;if(width>345||height>345)throw new AssertionError("Non-wave frame repainted beyond the pointer neighborhood");}
                }
            }
        });
        try {
            Field last=LoginPanel.class.getDeclaredField("lastFrame");last.setAccessible(true);
            for(int i=0;i<30;i++){last.setLong(panel,System.nanoTime()-16_000_000);call(panel,"tick",new Class<?>[0]);}
        }finally{RepaintManager.setCurrentManager(old);timer.stop();}
        if(counts[0]>13||counts[0]<10||counts[1]<15)throw new AssertionError("Full-wave vs local-pointer cadence was not separated: "+Arrays.toString(counts));
        Color[] normal=(Color[])get(paper,"DOT_COLORS");Color[][] brighter=(Color[][])get(paper,"BRIGHT_DOT_COLORS");
        for(int i=0;i<normal.length;i++) {
            if(!normal[i].equals(brighter[0][i])||brighter[32][i].getRed()!=Math.round(normal[i].getRed()*1.3)
                ||brighter[32][i].getAlpha()!=normal[i].getAlpha())throw new AssertionError("Wave brightness must rise 30% without changing pointer colors or opacity");
        }
        System.out.println("PASS: 30 pointer ticks => "+counts[0]+" full-wave and "+counts[1]+" local updates; 30% brighter wave palette");
    }
    private static void follow(Object paper,int x,int y)throws Exception{call(paper,"followPointer",new Class<?>[]{Point.class},new Point(x,y));}
    private static void step(Object paper,double dt)throws Exception{call(paper,"updateDots",new Class<?>[]{double.class},dt);}
    private static Object get(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static Object call(Object target,String name,Class<?>[] types,Object...args)throws Exception{Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,args);}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container n)layout(n);}
}
