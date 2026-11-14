package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.*;
import java.nio.file.*;
import java.util.*;

/** Headless resize workload; measures EDT paint work rather than native screen FPS. */
public final class LoginResizePerformanceTest {
    public static void main(String[] args)throws Exception {
        boolean baseline=Arrays.asList(args).contains("--baseline");
        Path output=Path.of(args.length==0?"build/login-resize":args[0]);Files.createDirectories(output);
        java.util.List<String> results=new ArrayList<>();
        SwingUtilities.invokeAndWait(()->{try {
            for(double scale:new double[]{1,2}) {
                LoginPanel panel=new LoginPanel(()->{});panel.setSize(1360,850);layout(panel);
                BufferedImage image=new BufferedImage((int)(1560*scale),(int)(950*scale),BufferedImage.TYPE_INT_RGB);
                Graphics2D g=image.createGraphics();g.scale(scale,scale);
                try {
                    panel.printAll(g);
                    Object paper=get(panel,"paper"),surface=get(paper,"cachedSurface"),card=get(paper,"cachedCard");
                    int surfaceRebuilds=0,cardRebuilds=0;
                    double[] elapsed=new double[18];
                    for(int frame=0;frame<elapsed.length;frame++) {
                        int width=1360+frame*7,height=850+frame*3;
                        long start=System.nanoTime();
                        panel.setSize(width,height);layout(panel);panel.printAll(g);
                        elapsed[frame]=(System.nanoTime()-start)/1e6;
                        Object next=get(paper,"cachedSurface"),nextCard=get(paper,"cachedCard");
                        if(next!=surface)surfaceRebuilds++;
                        if(nextCard!=card)cardRebuilds++;
                        surface=next;card=nextCard;
                    }
                    Arrays.sort(elapsed);
                    String result=String.format(Locale.ROOT,"{\"scale\":%.1f,\"medianMs\":%.3f,\"p95Ms\":%.3f,\"surfaceRebuilds\":%d,\"cardRebuilds\":%d}",
                        scale,elapsed[elapsed.length/2],elapsed[(int)((elapsed.length-1)*.95)],surfaceRebuilds,cardRebuilds);
                    results.add(result);System.out.println(result);
                    if(!baseline&&(surfaceRebuilds!=0||cardRebuilds!=0))throw new AssertionError("Live resize must reuse existing raster layers");
                } finally {g.dispose();}
            }
        } catch(Exception failure){throw new RuntimeException(failure);}});
        if(!baseline)verifyAsyncRefresh();
        Files.writeString(output.resolve("resize-times.json"),"[\n"+String.join(",\n",results)+"\n]\n");
        System.exit(0);
    }
    private static void verifyAsyncRefresh()throws Exception {
        CompletableFuture<Void> completed=new CompletableFuture<>();
        LoginPanel[] host=new LoginPanel[1];
        SwingUtilities.invokeAndWait(()->{try {
            LoginPanel panel=new LoginPanel(()->{});host[0]=panel;
            panel.setSize(1000,700);layout(panel);paint(panel);
            Object paper=get(panel,"paper"),before=get(paper,"cachedSurface"),card=get(paper,"cachedCard");
            panel.setSize(1120,760);layout(panel);paint(panel);
            if(get(paper,"cachedSurface")!=before||get(paper,"cachedCard")!=card)
                throw new AssertionError("Dragging must stretch the existing backdrop and reuse the card");
            paint(panel,2);
            Object retinaCard=get(paper,"cachedCard");
            call(paper,"refreshSurfaceAsync");
            SwingWorker<?,?> worker=(SwingWorker<?,?>)get(paper,"surfaceWorker");
            worker.addPropertyChangeListener(event->{
                if(!"state".equals(event.getPropertyName())||event.getNewValue()!=SwingWorker.StateValue.DONE)return;
                try {
                    if(get(paper,"cachedSurface")!=worker.get()||(int)get(paper,"cachedWidth")!=1120||(int)get(paper,"cachedHeight")!=760)
                        throw new AssertionError("Settled size must install the exact new backdrop");
                    BufferedImage updated=(BufferedImage)worker.get();
                    if(updated.getWidth()!=2240||updated.getHeight()!=1520)throw new AssertionError("Settled backdrop must use the new device scale");
                    if(get(paper,"cachedCard")!=retinaCard)throw new AssertionError("Settled backdrop refresh must not rebuild the card");
                    completed.complete(null);
                } catch(Throwable failure){completed.completeExceptionally(failure);}
            });
        } catch(Throwable failure){completed.completeExceptionally(failure);}});
        completed.get(10,TimeUnit.SECONDS);
        CompletableFuture<Void> cancelled=new CompletableFuture<>();
        SwingUtilities.invokeAndWait(()->{try {
            LoginPanel panel=host[0];panel.setSize(1200,800);layout(panel);paint(panel);
            Object paper=get(panel,"paper");call(paper,"refreshSurfaceAsync");
            SwingWorker<?,?> superseded=(SwingWorker<?,?>)get(paper,"surfaceWorker");
            panel.setSize(1240,820);layout(panel);paint(panel);
            if(!superseded.isCancelled())throw new AssertionError("A newer size must cancel the outdated render");
            call(paper,"refreshSurfaceAsync");
            SwingWorker<?,?> worker=(SwingWorker<?,?>)get(paper,"surfaceWorker");
            worker.addPropertyChangeListener(event->{
                if(!"state".equals(event.getPropertyName())||event.getNewValue()!=SwingWorker.StateValue.DONE)return;
                try {
                    if(!worker.isCancelled()||get(paper,"cachedSurface")!=null||((javax.swing.Timer)get(paper,"resizeRefresh")).isRunning())
                        throw new AssertionError("Hidden login must cancel pending work and release its buffers");
                    cancelled.complete(null);
                } catch(Throwable failure){cancelled.completeExceptionally(failure);}
            });
            call(paper,"releaseSurface");
        } catch(Throwable failure){cancelled.completeExceptionally(failure);}});
        cancelled.get(10,TimeUnit.SECONDS);
        System.out.println("PASS: asynchronous settled-size refresh, card reuse and hidden-render cancellation");
    }
    private static Object call(Object object,String name)throws Exception {Method m=object.getClass().getDeclaredMethod(name);m.setAccessible(true);return m.invoke(object);}
    private static void paint(JComponent component){paint(component,1);}
    private static void paint(JComponent component,double scale){
        BufferedImage image=new BufferedImage((int)(component.getWidth()*scale),(int)(component.getHeight()*scale),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();try{g.scale(scale,scale);component.printAll(g);}finally{g.dispose();}
    }
    private static Object get(Object object,String name)throws Exception {Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);}
    private static void layout(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container c)layout(c);}
}
