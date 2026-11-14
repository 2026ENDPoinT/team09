package dev.synesis.poc.ui;

import com.google.gson.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Identical active-frame workloads; CPU timing is separate from native GPU/screen measurements. */
public final class RenderReusePerformanceTest {
    private static Path output;
    private static boolean baseline;
    private static final JsonArray results=new JsonArray();
    public static void main(String[] args)throws Exception {
        output=Path.of(args[0]);baseline=Arrays.asList(args).contains("--baseline");Files.createDirectories(output);
        SwingUtilities.invokeAndWait(()->{try {
            for(int scale:new int[]{1,2}) {
                LoginPanel login=new LoginPanel(()->{});login.setSize(1360,850);layout(login);
                Object paper=get(login,"paper");call(paper,"followPointer",new Class<?>[]{Point.class},new Point(-1000,-1000));
                BufferedImage image=new BufferedImage(1360*scale,850*scale,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.scale(scale,scale);
                measure("login-wave",scale,140,()->{call(paper,"updateDots",new Class<?>[]{double.class},.033);login.printAll(g);});
                g.dispose();call(paper,"releaseSurface",new Class<?>[]{});image.flush();

                LibraryAdBanner banner=new LibraryAdBanner();banner.setSize(1360,176);banner.doLayout();
                BufferedImage[] photos=(BufferedImage[])get(banner,"images");
                try(var input=RenderReusePerformanceTest.class.getResourceAsStream("/dev/synesis/poc/advertising/ad-0.jpg")) {
                    Arrays.fill(photos,ImageIO.read(input));
                }
                set(banner,"active",1);set(banner,"from",0);set(banner,"progress",.45);
                image=new BufferedImage(1360*scale,176*scale,BufferedImage.TYPE_INT_RGB);Graphics2D b=image.createGraphics();b.scale(scale,scale);
                int[] frame={0};measure("home-carousel",scale,120,()->{set(banner,"progress",(frame[0]++%90)/90d);banner.printAll(b);});
                set(banner,"progress",.45);banner.printAll(b);compare("carousel-"+scale,image);b.dispose();banner.close();image.flush();

                JPanel root=roundedScene();root.setSize(1360,850);layout(root);
                image=new BufferedImage(1360*scale,850*scale,BufferedImage.TYPE_INT_RGB);Graphics2D r=image.createGraphics();r.scale(scale,scale);
                r.setColor(Color.WHITE);r.fillRect(0,0,1360,850);root.printAll(r);compare("rounded-full-"+scale,image);
                r.setClip(120,250,300,30);measure("study-interior-damage",scale,350,()->root.printAll(r));
                compare("rounded-damage-"+scale,image);r.dispose();image.flush();
            }
        }catch(Exception e){throw new RuntimeException(e);}});
        Files.writeString(output.resolve(baseline?"before.json":"after.json"),results.toString());System.out.println(results);System.exit(0);
    }
    private interface Frame{void paint()throws Exception;}
    private static void measure(String scene,int scale,int count,Frame frame)throws Exception {
        for(int i=0;i<45;i++)frame.paint();double[] times=new double[count];
        long cpu=ManagementFactory.getThreadMXBean().getCurrentThreadCpuTime();
        for(int i=0;i<count;i++){long start=System.nanoTime();frame.paint();times[i]=(System.nanoTime()-start)/1e6;}
        cpu=ManagementFactory.getThreadMXBean().getCurrentThreadCpuTime()-cpu;Arrays.sort(times);
        JsonObject row=new JsonObject();row.addProperty("scene",scene);row.addProperty("scale",scale);row.addProperty("frames",count);
        row.addProperty("cpuMsPerFrame",cpu/1e6/count);row.addProperty("medianMs",times[count/2]);row.addProperty("p95Ms",times[(int)(count*.95)]);results.add(row);
    }
    private static JPanel roundedScene() {
        JPanel root=new MistWorkspaceTheme.Panel(new BorderLayout(),18,Color.WHITE,new Color(0xdfe3e8));root.setBorder(BorderFactory.createEmptyBorder(22,22,22,22));
        JPanel middle=new MistWorkspaceTheme.Panel(new BorderLayout(),16,new Color(0xf8f8fa),Color.GRAY);middle.setBorder(BorderFactory.createEmptyBorder(22,22,22,22));
        JPanel inner=new StudyTheme.RoundedPanel(new BorderLayout(),14,Color.WHITE,Color.GRAY);
        inner.add(new JComponent(){@Override protected void paintComponent(Graphics g){
            g.setColor(new Color(0x252629));g.setFont(StudyTheme.font(Font.PLAIN,16));
            for(int line=0;line<40;line++)g.drawString("원문과 강의 해설, 개념 정리의 정적인 본문을 그대로 유지해요.",28,30+line*24);
        }});middle.add(inner);root.add(middle);return root;
    }
    private static void compare(String name,BufferedImage actual)throws Exception {
        Path file=output.resolve(name+".png");
        if(baseline){ImageIO.write(actual,"png",file.toFile());return;}
        BufferedImage expected=ImageIO.read(file.toFile());int maximum=0;
        for(int y=0;y<actual.getHeight();y++)for(int x=0;x<actual.getWidth();x++)for(int channel=0;channel<24;channel+=8)
            maximum=Math.max(maximum,Math.abs(((actual.getRGB(x,y)>>channel)&255)-((expected.getRGB(x,y)>>channel)&255)));
        if(maximum>2)throw new AssertionError(name+" changed appearance: "+maximum+"/255");
    }
    private static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String name,Object value)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    private static Object call(Object o,String name,Class<?>[] types,Object...args)throws Exception{Method m=o.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(o,args);}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
}
