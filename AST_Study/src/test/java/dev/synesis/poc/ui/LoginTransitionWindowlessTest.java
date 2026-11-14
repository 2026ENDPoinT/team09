package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.HierarchyEvent;
import java.awt.event.KeyEvent;
import java.awt.event.MouseWheelEvent;
import java.awt.geom.AffineTransform;
import java.awt.image.BufferedImage;
import java.awt.image.ColorModel;
import java.lang.management.ManagementFactory;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;

/** No native windows, app launches, provider calls, clicks, screenshots, or live-app inspection. */
public final class LoginTransitionWindowlessTest {
    private static final int WIDTH=1360,HEIGHT=850;

    public static void main(String[] args)throws Exception {
        if(!GraphicsEnvironment.isHeadless())throw new AssertionError("Use -Djava.awt.headless=true");
        boolean reference=List.of(args).contains("--reference");
        List<String> metrics=new ArrayList<>();
        SwingUtilities.invokeAndWait(()->{
            try {
                if(!reference)contracts();
                for(int scale:new int[]{1,2})paintSamples(scale,reference,metrics);
            }catch(Exception failure){throw new RuntimeException(failure);}
        });
        if(args.length>0&&!args[0].startsWith("--")){
            Path output=Path.of(args[0]);Files.createDirectories(output);
            Files.writeString(output.resolve("transition-metrics.json"),"[\n"+String.join(",\n",metrics)+"\n]\n");
        }
        System.out.println("PASS: "+(reference?"reference fixed-frame paint samples":"windowless transition contracts and fixed-frame paint samples")+
            "; no actual app or authentication used");
    }

    private static void contracts()throws Exception {
        require((double)getStatic("FILL_MS")==760&&(double)getStatic("HOLD_MS")==380
            &&(double)getStatic("REVEAL_MS")==680,"Transition timings changed");
        AtomicInteger detached=new AtomicInteger();
        LoginTransition.play(new JButton(),detached::incrementAndGet);
        require(detached.get()==1,"Detached button must invoke its destination once");

        ScaleRoot root=root(1);Scene departure=new Scene(0x556677);root.setContentPane(departure);layout(root);
        JPanel previousGlass=new JPanel();root.setGlassPane(previousGlass);previousGlass.setVisible(true);
        FocusButton initial=new FocusButton(),next=new FocusButton();root.setDefaultButton(initial);
        AtomicInteger entered=new AtomicInteger(),duplicate=new AtomicInteger();
        LoginTransition.play(departure.button,()->{
            entered.incrementAndGet();root.setContentPane(new Scene(0x665544));layout(root);root.setDefaultButton(next);
        });
        LoginTransition transition=(LoginTransition)root.getGlassPane();timer(transition).stop();
        require(transition.isOpaque()&&transition.isFocusable()&&!transition.getFocusTraversalKeysEnabled(),"Input overlay configuration changed");
        require(root.getDefaultButton()==null,"Default button remained active under transition");
        require(transition.getMouseListeners().length>0&&transition.getMouseMotionListeners().length>0,"Pointer overlay missing");
        KeyEvent key=new KeyEvent(transition,KeyEvent.KEY_PRESSED,0,0,KeyEvent.VK_ENTER,'\n');
        transition.processKeyEvent(key);require(key.isConsumed(),"Transition did not consume key");
        MouseWheelEvent wheel=new MouseWheelEvent(transition,MouseWheelEvent.MOUSE_WHEEL,0,0,1,1,0,false,
            MouseWheelEvent.WHEEL_UNIT_SCROLL,1,1);
        for(var listener:transition.getMouseWheelListeners())listener.mouseWheelMoved(wheel);
        require(wheel.isConsumed(),"Transition did not consume wheel");
        LoginTransition.play(departure.button,duplicate::incrementAndGet);
        require(root.getGlassPane()==transition&&duplicate.get()==0,"Duplicate transition replaced the running overlay");
        advanceAt(transition,740);require(entered.get()==0,"Destination ran before fill completed");
        advanceAt(transition,780);require(entered.get()==1&&get(transition,"departure")==null,"Departure was retained after switching");
        require(get(transition,"arrival")!=null&&root.getDefaultButton()==null,"Arrival snapshot/default-button block missing");
        advanceAt(transition,1000);require(entered.get()==1,"Destination ran more than once");
        advanceAt(transition,1840);assertReleased(transition);
        require(root.getGlassPane()==previousGlass&&previousGlass.isVisible(),"Previous visible glass was not restored");
        require(root.getDefaultButton()==next&&next.focusCalls==1,"Destination default/focus was not restored");
        call(transition,"finish");advanceAt(transition,1850);
        require(entered.get()==1&&next.focusCalls==1,"Finished transition was not idempotent");

        LoginPanel login=new LoginPanel(()->{throw new AssertionError("No authentication action is allowed");});
        ScaleRoot loginRoot=root(1);loginRoot.setContentPane(login);layout(loginRoot);
        LoginTransition.playLogout(login.loginButton(),()->{});
        transition=(LoginTransition)loginRoot.getGlassPane();timer(transition).stop();
        require((boolean)get(login,"animationPaused")&&!((Timer)get(login,"animation")).isRunning(),"Login background was not paused");
        require((boolean)get(transition,"logout")&&"".equals(get(transition,"title"))
            &&"".equals(get(transition,"subtitle")),"Logout transition must have no visible messages");
        advanceAt(transition,780);require((boolean)get(login,"animationPaused"),"Arrival background resumed behind overlay");
        call(transition,"finish");assertReleased(transition);
        require(!(boolean)get(login,"animationPaused"),"Login background was not resumed");
        call(get(login,"paper"),"releaseSurface");
        require(get(get(login,"paper"),"cachedSurface")==null,"Hidden background cleanup failed");

        for(Throwable failure:new Throwable[]{new IllegalStateException("fixture"),new AssertionError("fixture")}){
            ScaleRoot failedRoot=root(1);Scene scene=new Scene(0x112233);failedRoot.setContentPane(scene);layout(failedRoot);
            FocusButton fallback=new FocusButton();failedRoot.setDefaultButton(fallback);Component glass=failedRoot.getGlassPane();
            LoginTransition.play(scene.button,()->{if(failure instanceof Error error)throw error;throw (RuntimeException)failure;});
            LoginTransition failed=(LoginTransition)failedRoot.getGlassPane();timer(failed).stop();
            try{advanceAt(failed,780);throw new AssertionError("Destination failure was swallowed");}
            catch(InvocationTargetException wrapper){require(wrapper.getCause()==failure,"Wrong destination failure propagated");}
            assertReleased(failed);require(failedRoot.getGlassPane()==glass&&failedRoot.getDefaultButton()==fallback,"Error did not restore glass/default");
        }

        ScaleRoot disposedRoot=root(1);Scene scene=new Scene(0x223344);disposedRoot.setContentPane(scene);layout(disposedRoot);
        Component oldGlass=disposedRoot.getGlassPane();AtomicInteger afterDispose=new AtomicInteger();
        LoginTransition.play(scene.button,afterDispose::incrementAndGet);
        LoginTransition disposed=(LoginTransition)disposedRoot.getGlassPane();timer(disposed).stop();
        HierarchyEvent disposal=new HierarchyEvent(disposed,HierarchyEvent.HIERARCHY_CHANGED,disposed,disposedRoot,
            HierarchyEvent.DISPLAYABILITY_CHANGED);
        for(var listener:disposed.getHierarchyListeners())listener.hierarchyChanged(disposal);
        advanceAt(disposed,780);assertReleased(disposed);
        require(afterDispose.get()==0&&disposedRoot.getGlassPane()==oldGlass,"Disposal ran a destination or retained glass");

        ScaleRoot takeoverRoot=root(1);Scene takeoverScene=new Scene(0x334455);takeoverRoot.setContentPane(takeoverScene);layout(takeoverRoot);
        JPanel replacement=new JPanel();
        LoginTransition.play(takeoverScene.button,()->{takeoverRoot.setGlassPane(replacement);replacement.setVisible(true);});
        LoginTransition takeover=(LoginTransition)takeoverRoot.getGlassPane();timer(takeover).stop();
        advanceAt(takeover,780);assertReleased(takeover);
        require(takeoverRoot.getGlassPane()==replacement&&replacement.isVisible(),"A replacement glass pane was overwritten");
        System.out.println("PASS: one destination, null root, timings, input/default/focus/glass, pause/cleanup, error/disposal/reentrant ownership");
    }

    private static void paintSamples(int scale,boolean reference,List<String> metrics)throws Exception {
        ScaleRoot root=root(scale);Scene from=new Scene(0x456789);root.setContentPane(from);layout(root);
        Constructor<LoginTransition> constructor=LoginTransition.class.getDeclaredConstructor(JRootPane.class,Point.class,Runnable.class,String.class,String.class,boolean.class);
        constructor.setAccessible(true);
        LoginTransition transition=constructor.newInstance(root,new Point(WIDTH/2,560),(Runnable)()->{},"Approved","환영합니다.",false);
        transition.setSize(WIDTH,HEIGHT);
        Scene to=new Scene(0x796543);root.setContentPane(to);layout(root);
        set(transition,"arrival",call(transition,"snapshot"));
        BufferedImage image=new BufferedImage(WIDTH*scale,HEIGHT*scale,BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.scale(scale,scale);
        try{
            set(transition,"elapsed",0.0);transition.paintComponent(g);
            BufferedImage original=(BufferedImage)get(transition,"departure");
            for(int y=0;y<80*scale;y++)for(int x=0;x<160*scale;x++)
                require(image.getRGB(x,y)==original.getRGB(x,y),"Frozen-scene pixels changed at "+scale+"x");
            set(transition,"entered",true);set(transition,"elapsed",1820.0);transition.paintComponent(g);
            BufferedImage destination=(BufferedImage)get(transition,"arrival");
            for(int y=0;y<HEIGHT*scale;y+=17)for(int x=0;x<WIDTH*scale;x+=19)
                require(image.getRGB(x,y)==destination.getRGB(x,y),"Reveal changed destination pixels at "+scale+"x");
            int sourcePaints=from.paints,destinationPaints=to.paints;
            BufferedImage before=(BufferedImage)get(transition,"departure"),after=(BufferedImage)get(transition,"arrival");
            String[] stages={"fill","hold","reveal"};double[] times={380,950,1480};
            var bean=ManagementFactory.getThreadMXBean();
            if(!bean.isCurrentThreadCpuTimeSupported())throw new AssertionError("EDT CPU clock unavailable");
            if(!bean.isThreadCpuTimeEnabled())bean.setThreadCpuTimeEnabled(true);
            for(int stage=0;stage<stages.length;stage++){
                set(transition,"entered",stage>0);set(transition,"elapsed",times[stage]);
                for(int frame=0;frame<6;frame++)transition.paintComponent(g);
                long cpu=0,wall=0;
                for(int frame=0;frame<18;frame++){
                    long cpuStart=bean.getCurrentThreadCpuTime(),wallStart=System.nanoTime();
                    transition.paintComponent(g);
                    wall+=System.nanoTime()-wallStart;cpu+=bean.getCurrentThreadCpuTime()-cpuStart;
                }
                String row=String.format(Locale.ROOT,
                    "{\"scale\":%d,\"stage\":\"%s\",\"elapsedMs\":%.0f,\"frames\":18,\"edtCpuMsPerFrame\":%.4f,\"wallMsPerFrame\":%.4f}",
                    scale,stages[stage],times[stage],cpu/18e6,wall/18e6);
                metrics.add(row);System.out.println(row);
                if(!reference&&stage==1)require((image.getRGB(0,0)&0xffffff)==0x242424,"Hold must use solid charcoal");
                require(get(transition,"departure")==before&&get(transition,"arrival")==after,"A paint recreated a scene snapshot");
            }
            require(from.paints==sourcePaints&&to.paints==destinationPaints,"A frame repainted a live scene");
            if(!reference){
                int largeBuffers=0;for(Field field:LoginTransition.class.getDeclaredFields())if(field.getType()==BufferedImage.class)largeBuffers++;
                require(largeBuffers==2,"Unexpected full-screen backdrop/cache added");
            }
            if(!reference) {
                int wider=WIDTH+120,taller=HEIGHT+80;
                transition.setSize(wider,taller);set(transition,"entered",true);set(transition,"elapsed",1820.0);
                BufferedImage resized=new BufferedImage(wider*scale,taller*scale,BufferedImage.TYPE_INT_RGB);
                BufferedImage expected=new BufferedImage(wider*scale,taller*scale,BufferedImage.TYPE_INT_RGB);
                Graphics2D actualGraphics=resized.createGraphics(),expectedGraphics=expected.createGraphics();
                try {
                    actualGraphics.scale(scale,scale);expectedGraphics.scale(scale,scale);
                    transition.paintComponent(actualGraphics);expectedGraphics.drawImage(destination,0,0,wider,taller,null);
                }finally{actualGraphics.dispose();expectedGraphics.dispose();}
                for(int y=0;y<taller*scale;y+=17)for(int x=0;x<wider*scale;x+=19)
                    require(resized.getRGB(x,y)==expected.getRGB(x,y),"Resized reveal left a charcoal strip");
                resized.flush();expected.flush();
            }
        }finally{g.dispose();call(transition,"finish");image.flush();}
    }

    private static void advanceAt(LoginTransition transition,double millis)throws Exception{
        set(transition,"started",System.nanoTime()-(long)(millis*1e6));call(transition,"advance");
    }
    private static void assertReleased(LoginTransition transition)throws Exception{
        require((boolean)get(transition,"finished")&&!timer(transition).isRunning(),"Transition timer/lifecycle not finished");
        require(get(transition,"departure")==null&&get(transition,"arrival")==null,"Finished transition retained snapshots");
    }
    private static Timer timer(LoginTransition transition)throws Exception{return (Timer)get(transition,"timer");}
    private static ScaleRoot root(int scale){ScaleRoot root=new ScaleRoot(scale);root.setSize(WIDTH,HEIGHT);layout(root);return root;}
    private static void layout(Container parent){parent.doLayout();for(Component child:parent.getComponents())if(child instanceof Container nested)layout(nested);}
    private static void require(boolean okay,String message){if(!okay)throw new AssertionError(message);}
    private static Field field(Class<?> type,String name)throws Exception{Field f=type.getDeclaredField(name);f.setAccessible(true);return f;}
    private static Object get(Object target,String name)throws Exception{return field(target.getClass(),name).get(target);}
    private static Object getStatic(String name)throws Exception{return field(LoginTransition.class,name).get(null);}
    private static void set(Object target,String name,Object value)throws Exception{field(target.getClass(),name).set(target,value);}
    private static Object call(Object target,String name)throws Exception{Method m=target.getClass().getDeclaredMethod(name);m.setAccessible(true);return m.invoke(target);}

    private static final class FocusButton extends JButton{
        int focusCalls;
        @Override public boolean requestFocusInWindow(){focusCalls++;return true;}
    }
    private static final class Scene extends JPanel{
        final JButton button=new JButton("Fixture");final Color color;int paints;
        Scene(int rgb){super(null);color=new Color(rgb);button.setBounds(WIDTH/2-80,540,160,40);add(button);}
        @Override protected void paintComponent(Graphics graphics){
            paints++;graphics.setColor(color);graphics.fillRect(0,0,getWidth(),getHeight());
            graphics.setColor(Color.WHITE);for(int x=0;x<getWidth();x+=17)graphics.drawLine(x,0,x,getHeight());
            graphics.setColor(Color.BLACK);for(int y=0;y<getHeight();y+=19)graphics.drawLine(0,y,getWidth(),y);
        }
    }
    private static final class ScaleRoot extends JRootPane{
        private final GraphicsConfiguration configuration;
        ScaleRoot(int scale){configuration=new ScaleConfiguration(scale);}
        @Override public GraphicsConfiguration getGraphicsConfiguration(){return configuration;}
    }
    private static final class ScaleConfiguration extends GraphicsConfiguration{
        private final int scale;
        private final GraphicsDevice device=new GraphicsDevice(){
            @Override public int getType(){return TYPE_RASTER_SCREEN;}
            @Override public String getIDstring(){return "windowless-software-fixture";}
            @Override public GraphicsConfiguration[] getConfigurations(){return new GraphicsConfiguration[]{ScaleConfiguration.this};}
            @Override public GraphicsConfiguration getDefaultConfiguration(){return ScaleConfiguration.this;}
        };
        ScaleConfiguration(int scale){this.scale=scale;}
        @Override public GraphicsDevice getDevice(){return device;}
        @Override public ColorModel getColorModel(){return ColorModel.getRGBdefault();}
        @Override public ColorModel getColorModel(int transparency){return ColorModel.getRGBdefault();}
        @Override public AffineTransform getDefaultTransform(){return AffineTransform.getScaleInstance(scale,scale);}
        @Override public AffineTransform getNormalizingTransform(){return new AffineTransform();}
        @Override public Rectangle getBounds(){return new Rectangle(0,0,WIDTH*scale,HEIGHT*scale);}
    }
}
