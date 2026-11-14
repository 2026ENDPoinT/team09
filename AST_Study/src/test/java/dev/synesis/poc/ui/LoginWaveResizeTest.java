package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.util.concurrent.*;

/** Real layout/paint resize paths, no window or user data. */
public final class LoginWaveResizeTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try {
            LoginPanel panel=new LoginPanel(()->{});panel.setSize(1360,850);layout(panel);
            Object paper=get(panel,"paper");for(int i=0;i<160;i++)step(paper);
            Field blend=paper.getClass().getDeclaredField("waveBlend");blend.setAccessible(true);blend.setDouble(paper,.5);
            paint(panel,2);
            Object raster=get(paper,"waveRaster"),surface=get(paper,"cachedSurface"),card=get(paper,"cachedCard");
            int columns=(int)get(paper,"dotColumns");
            double response=((double[])get(paper,"dotResponses"))[10*columns+10],phase=(double)get(paper,"waveTravel");
            for(int n=1;n<=10;n++) {
                panel.setSize(1360+n*4,850+n*4);layout(panel);paint(panel,2);
                if(get(paper,"waveRaster")!=raster)throw new AssertionError("Small resize recreated a Retina buffer");
                int nextColumns=(int)get(paper,"dotColumns");
                if(((double[])get(paper,"dotResponses"))[10*nextColumns+10]!=response || (double)get(paper,"waveTravel")!=phase)
                    throw new AssertionError("Resize reset existing wave response/phase");
                if(get(paper,"cachedSurface")!=surface || get(paper,"cachedCard")!=card)throw new AssertionError("Drag rebuilt static raster layers");
                LoginWaveRaster frame=(LoginWaveRaster)get(paper,"waveRaster");
                if(frame.contentWidth!=panel.getWidth()*2 || (frame.contentHeight>128 || frame.originY+frame.contentHeight!=panel.getHeight()*2))throw new AssertionError("Backing capacity leaked into visible geometry");
            }
            int allocations=0;Object previous=raster;
            for(int n=0;n<80;n++) {
                panel.setSize(1360+n*2,850+n);layout(panel);step(paper);paint(panel,2);
                Object next=get(paper,"waveRaster");if(next==null)throw new AssertionError("Live resize fell back to expensive vector field");
                if(next!=previous)allocations++;previous=next;
            }
            if(allocations>4)throw new AssertionError("Large raster allocated repeatedly during drag: "+allocations);
            call(paper,"releaseSurface");
            if(get(paper,"waveRaster")!=null)throw new AssertionError("Hidden resize retained large buffer");
        }catch(Exception error){throw new RuntimeException(error);}});
        verifyNarrowCardRefresh();
        System.out.println("PASS: resize wave/phase continuity, retained fast path, bounded buffer growth, narrow-card async refresh and cancellation");
    }
    private static void verifyNarrowCardRefresh()throws Exception {
        CompletableFuture<Void> done=new CompletableFuture<>();
        LoginPanel[] host=new LoginPanel[1];
        SwingUtilities.invokeAndWait(()->{try {
            LoginPanel panel=new LoginPanel(()->{});host[0]=panel;panel.setSize(520,700);layout(panel);paint(panel,1);
            Object paper=get(panel,"paper"),card=get(paper,"cachedCard"),shadow=get(paper,"cachedShadow");
            panel.setSize(400,700);layout(panel);paint(panel,1);
            if(get(paper,"cachedCard")!=card || get(paper,"cachedShadow")!=shadow)throw new AssertionError("Narrow drag rebuilt shadow on EDT");
            call(paper,"refreshCardAsync");
            SwingWorker<?,?> worker=(SwingWorker<?,?>)get(paper,"cardWorker");
            worker.addPropertyChangeListener(event->{
                if(!"state".equals(event.getPropertyName()) || event.getNewValue()!=SwingWorker.StateValue.DONE)return;
                try {
                    if(get(paper,"cachedCard")==card || (int)get(paper,"shadowWidth")!=360)throw new AssertionError("Settled card did not get exact new width");
                    done.complete(null);
                }catch(Throwable failure){done.completeExceptionally(failure);}
            });
        }catch(Throwable failure){done.completeExceptionally(failure);}});
        done.get(10,TimeUnit.SECONDS);
        SwingUtilities.invokeAndWait(()->{try {
            Object paper=get(host[0],"paper");host[0].setSize(380,700);layout(host[0]);paint(host[0],1);
            call(paper,"refreshCardAsync");SwingWorker<?,?> old=(SwingWorker<?,?>)get(paper,"cardWorker");
            host[0].setSize(370,700);layout(host[0]);
            if(!old.isCancelled())throw new AssertionError("Outdated card render survived newer size");
            call(paper,"refreshCardAsync");SwingWorker<?,?> latest=(SwingWorker<?,?>)get(paper,"cardWorker");
            call(paper,"releaseSurface");
            if(!latest.isCancelled() || get(paper,"cachedCard")!=null)throw new AssertionError("Hidden login kept a pending card render");
        }catch(Exception error){throw new RuntimeException(error);}});
    }
    private static void step(Object paper)throws Exception{call(paper,"updateDots",new Class<?>[]{double.class},.016);}
    private static Object get(Object obj,String name)throws Exception{Field field=obj.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(obj);}
    private static Object call(Object obj,String name)throws Exception{return call(obj,name,new Class<?>[0]);}
    private static Object call(Object obj,String name,Class<?>[] types,Object...args)throws Exception{Method method=obj.getClass().getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(obj,args);}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static void paint(JComponent c,int scale){BufferedImage image=new BufferedImage(c.getWidth()*scale,c.getHeight()*scale,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();try{g.scale(scale,scale);c.printAll(g);}finally{g.dispose();}}
}
