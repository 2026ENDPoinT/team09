package dev.synesis.poc.ui;

import dev.synesis.poc.pdf.PdfWorkspace;
import javax.swing.*;
import java.awt.*;
import java.awt.event.KeyEvent;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/** Native-free checks: one navigation, bounded captures, paint-only motion, and input cleanup. */
public final class LibraryDepartureTest {
    private static int checks;
    private static boolean benchmark;
    private static class Scene extends JPanel {
        int paints,layouts;
        Scene(){super(null);setBackground(Color.WHITE);}
        @Override protected void paintComponent(Graphics g){paints++;super.paintComponent(g);}
        @Override public void doLayout(){layouts++;super.doLayout();}
    }
    public static void main(String[] args)throws Exception {
        benchmark=java.util.Arrays.asList(args).contains("--benchmark");
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});
        for(Dimension size:List.of(new Dimension(1100,700),new Dimension(1920,1080))) {
            RealDestination[] fixture={null};
            SwingUtilities.invokeAndWait(()->{try{fixture[0]=new RealDestination(size);}catch(Exception failure){throw new RuntimeException(failure);}});
            // Let component-resize and invokeLater callbacks run before checking the handoff.
            SwingUtilities.invokeAndWait(()->{});
            SwingUtilities.invokeAndWait(()->{try{fixture[0].complete();}catch(Exception failure){throw new RuntimeException(failure);}});
        }
        System.out.println("PASS: "+checks+" library departure lifecycle / memory / paint checks");
    }
    private static void run()throws Exception {
        check(LibraryDeparture.pixelBudget(128L*1024*1024)==699_050,"small-heap raster budget");
        check(LibraryDeparture.pixelBudget(4L*1024*1024*1024)==900_000,"large heap still capped");
        check(LibraryDeparture.pixelBudget(16L*1024*1024)==120_000,"minimum usable motion raster");
        check(LibraryDeparture.arrivalPixelBudget(128L*1024*1024)==4_000_000,"sharp destination remains bounded");
        check(Math.abs(LibraryDeparture.arrivalScale(0)-.92)<.00001,"arrival starts smaller");
        check(Math.abs(LibraryDeparture.arrivalScale(1)-1)<.00001,"arrival settles at exact live size");
        check(java.util.stream.IntStream.rangeClosed(0,100).allMatch(i->LibraryDeparture.arrivalScale(i/100d)>=.92 && LibraryDeparture.arrivalScale(i/100d)<1.01),"zoom stays within a restrained overshoot");
        checkFlushShell();
        for(Dimension size:List.of(new Dimension(1100,700),new Dimension(2800,1700))) {
            JRootPane root=new JRootPane();Scene scene=new Scene();root.setContentPane(scene);
            root.setSize(size);root.doLayout();scene.setSize(size);
            Component old=root.getGlassPane();old.setVisible(false);
            JButton original=new JButton("original"),destination=new JButton("destination");root.setDefaultButton(original);
            List<LibraryDeparture.Part> parts=new ArrayList<>();
            JPanel header=new JPanel();header.setBounds(0,0,size.width,50);scene.add(header);
            JPanel sidebar=new JPanel();sidebar.setBounds(0,50,160,size.height-50);scene.add(sidebar);
            for(int i=0;i<40;i++) {
                JPanel card=new JPanel();card.setBounds(170+(i%8)*100,65+(i/8)*110,90,100);scene.add(card);
                parts.add(new LibraryDeparture.Part(card,LibraryDeparture.Kind.CARD));
            }
            JPanel offscreen=new JPanel();offscreen.setBounds(10,size.height+50,90,100);scene.add(offscreen);
            parts.add(new LibraryDeparture.Part(offscreen,LibraryDeparture.Kind.CARD));
            parts.add(new LibraryDeparture.Part(header,LibraryDeparture.Kind.HEADER));
            parts.add(new LibraryDeparture.Part(sidebar,LibraryDeparture.Kind.SIDEBAR));
            AtomicInteger prepared=new AtomicInteger(),entered=new AtomicInteger(),bodyPaints=new AtomicInteger();
            LayoutMotionPanel pane=new LayoutMotionPanel(new BorderLayout());
            pane.setBounds(167,59,size.width-174,size.height-66);
            JComponent body=new JComponent(){@Override protected void paintComponent(Graphics g){
                bodyPaints.incrementAndGet();g.setColor(Color.MAGENTA);g.fillRect(0,0,getWidth(),getHeight());
            }};
            pane.add(body,BorderLayout.CENTER);
            LibraryDeparture motion=LibraryDeparture.start(root,parts,()->{
                prepared.incrementAndGet();scene.removeAll();scene.add(pane);root.setDefaultButton(destination);
            },entered::incrementAndGet);
            Rectangle finalBounds=pane.getBounds(),bodyBounds=body.getBounds();
            check(motion!=null && prepared.get()==1 && entered.get()==0,"real workspace prepared once; document opening deferred");
            check(bodyBounds.width>0 && bodyBounds.height>0,"actual destination children laid out before motion");
            check(bodyPaints.get()==0,"rich destination body excluded from preview capture");
            BufferedImage arrival=(BufferedImage)field(motion,"arrival");
            double scale=(Double)field(motion,"arrivalRasterScale");
            int shellPixel=arrival.getRGB((int)((pane.getX()+80)*scale),(int)((pane.getY()+80)*scale));
            check((shellPixel&0xffffff)==0xffffff,"arrival preview paints shell at real destination bounds");
            boolean cleanEdges=true;
            for(int x=0;x<arrival.getWidth();x++)cleanEdges&=(arrival.getRGB(x,0)&0xffffff)==0xffffff&&(arrival.getRGB(x,arrival.getHeight()-1)&0xffffff)==0xffffff;
            for(int y=0;y<arrival.getHeight();y++)cleanEdges&=(arrival.getRGB(0,y)&0xffffff)==0xffffff&&(arrival.getRGB(arrival.getWidth()-1,y)&0xffffff)==0xffffff;
            check(cleanEdges,"destination has no black fringe on any raster edge");
            AtomicInteger deferred=new AtomicInteger();
            check(LayoutMotionPanel.defer(body,"load",deferred::incrementAndGet),"rich rebuilds deferred during shell motion");
            check(root.getGlassPane()==motion && motion.isVisible(),"input overlay installed");
            check(root.getDefaultButton()==null,"default action blocked during flight");
            List<?> sprites=(List<?>)field(motion,"sprites");
            check(sprites.size()==2,"only header/sidebar move; all supplied cards are ignored");
            BufferedImage source=(BufferedImage)field(motion,"departure");
            check((long)source.getWidth()*source.getHeight()<=904_000,"raster budget includes ceil rounding");
            long started=(Long)field(motion,"started");
            int layouts=scene.layouts;
            BufferedImage frame=new BufferedImage(size.width,size.height,BufferedImage.TYPE_INT_RGB);
            Graphics2D graphics=frame.createGraphics();
            try {
                for(int ms:new int[]{0,49,105,140,175,231,301,371}) {
                    motion.advance(started+ms*1_000_000L);motion.paint(graphics);
                }
            }finally{graphics.dispose();}
            check(scene.paints==2 && bodyPaints.get()==0,"one source and one empty destination capture; no live content paints");
            check(scene.layouts==layouts,"animation frames never lay out live scene");
            check(entered.get()==0,"all animation frames finish before document opening starts");
            if(benchmark) {
                long[] costs=new long[48];Graphics2D target=frame.createGraphics();
                try {
                    for(int i=-8;i<costs.length;i++) {
                        motion.advance(started+(98+Math.floorMod(i,32)*7)*1_000_000L);
                        long begin=System.nanoTime();motion.paint(target);
                        if(i>=0)costs[i]=System.nanoTime()-begin;
                    }
                }finally{target.dispose();}
                java.util.Arrays.sort(costs);
                System.out.printf(java.util.Locale.ROOT,"paint %dx%d mean=%.3fms p95=%.3fms%n",size.width,size.height,
                    java.util.Arrays.stream(costs).average().orElse(0)/1_000_000d,costs[45]/1_000_000d);
            }
            motion.advance(started+392_000_000L);
            check(field(motion,"departure")==null && field(motion,"arrival")!=null && !sprites.isEmpty(),
                "source pixels released after fade while destination and outgoing chrome remain");
            motion.advance(started+518_000_000L);
            check(sprites.isEmpty() && field(motion,"arrival")!=null && entered.get()==0,
                "chrome pixels released before destination animation finishes");
            Graphics2D late=frame.createGraphics();
            try {motion.paint(late);} finally {late.dispose();}
            check(scene.paints==2 && bodyPaints.get()==0 && scene.layouts==layouts,
                "late frames paint safely after source images have been released");
            check(((Timer)field(motion,"timer")).getDelay()>=16,"callbacks never exceed 60Hz budget");
            motion.advance(started+2_000_000_000L);
            check(entered.get()==1 && prepared.get()==1,"completion loads content without preparing workspace again");
            check(pane.getBounds().equals(finalBounds) && body.getBounds().equals(bodyBounds)
                && scene.layouts==layouts,"handoff preserves exact shell and child bounds without another layout");
            check(deferred.get()==1,"deferred rich rebuild starts once after motion");
            check(root.getGlassPane()==old && !old.isVisible(),"completion restores original overlay");
            check(root.getDefaultButton()==destination,"destination default action restored");
            check(field(motion,"departure")==null && field(motion,"arrival")==null && sprites.isEmpty(),"all transition images released");
            check(!((Timer)field(motion,"timer")).isRunning(),"timer stopped");
            motion.finish();check(root.getGlassPane()==old && entered.get()==1,"cleanup never duplicates deferred opening");
            LibraryDeparture cancel=LibraryDeparture.start(root,parts,()->{},()->{});
            cancel.processKeyEvent(new KeyEvent(cancel,KeyEvent.KEY_PRESSED,0,0,KeyEvent.VK_ESCAPE,(char)27));
            check(root.getGlassPane()==old,"Escape reveals destination and releases input");
            LibraryDeparture resize=LibraryDeparture.start(root,parts,()->{},()->{});
            scene.setSize(size.width-1,size.height);
            for(var listener:scene.getComponentListeners())listener.componentResized(new java.awt.event.ComponentEvent(scene,java.awt.event.ComponentEvent.COMPONENT_RESIZED));
            check(root.getGlassPane()==old,"resize cancels stale-size snapshots");
            AtomicInteger closedOpen=new AtomicInteger();
            LibraryDeparture disposed=LibraryDeparture.start(root,parts,()->{},closedOpen::incrementAndGet);
            disposed.removeNotify();
            check(closedOpen.get()==0 && root.getGlassPane()==old,"closing the window never starts deferred document work");
            LibraryDeparture failing=LibraryDeparture.start(root,parts,()->{},()->{throw new IllegalStateException("fixture");});
            try {failing.finish();throw new AssertionError("missing failure");}
            catch(IllegalStateException expected){check(root.getGlassPane()==old,"navigation failure restores input overlay");}
            try {LibraryDeparture.start(root,parts,()->{throw new IllegalStateException("prepare");},()->{
                throw new AssertionError("failed preparation must not load content");
            });throw new AssertionError("missing preparation failure");}
            catch(IllegalStateException expectedFailure){check(root.getGlassPane()==old,"preparation failure also restores input overlay");}
        }
    }

    private static void checkFlushShell()throws Exception {
        JRootPane root=new JRootPane();Scene scene=new Scene();root.setContentPane(scene);
        root.setSize(313,199);root.doLayout();scene.setSize(313,199);
        Color line=new Color(0x5274a6);
        LayoutMotionPanel panel=new LayoutMotionPanel(new BorderLayout(),12,Color.WHITE,line);
        LibraryDeparture motion=LibraryDeparture.start(root,List.of(),()->{
            scene.removeAll();scene.add(panel);panel.setBounds(0,0,313,199);
        },()->{});
        try {
            ((Timer)field(motion,"timer")).stop();
            BufferedImage arrival=(BufferedImage)field(motion,"arrival");
            int w=arrival.getWidth(),h=arrival.getHeight(),rgb=line.getRGB()&0xffffff;
            check((arrival.getRGB(1,h/2)&0xffffff)==rgb,"flush shell keeps its complete left outline");
            check((arrival.getRGB(w-2,h/2)&0xffffff)==rgb,"flush shell keeps its complete right outline");
            check((arrival.getRGB(w/2,1)&0xffffff)==rgb,"flush shell keeps its complete top outline");
            check((arrival.getRGB(w/2,h-2)&0xffffff)==rgb,"flush shell keeps its complete bottom outline");
            check((arrival.getRGB(0,h-1)&0xffffff)!=0,"raster gutter has no uninitialized black pixels");
        }finally{motion.finish();}
    }

    /** Real empty PDF/summary/tutor hierarchy, with queued Swing layout events included. */
    private static final class RealDestination {
        final JRootPane root=new JRootPane();
        final JPanel scene=new JPanel(new BorderLayout());
        final PdfWorkspace view=new PdfWorkspace(false);
        final ProportionalSplitPane outer=new ProportionalSplitPane(JSplitPane.HORIZONTAL_SPLIT);
        final JSplitPane inner;
        final LibraryDeparture motion;
        final List<Rectangle> bounds;
        final AtomicInteger loaded=new AtomicInteger();
        RealDestination(Dimension size)throws Exception {
            root.setContentPane(scene);root.setSize(size);root.doLayout();
            scene.add(new JLabel("library"));
            JPanel navigation=view.moveLearningNavigation();
            LayoutMotionPanel tutor=LayoutMotionPanel.transparentHost(new BorderLayout(),new Insets(0,0,0,0));
            tutor.add(view.moveTutorToSidePanel(()->{}));tutor.setMinimumSize(new Dimension(280,1));
            outer.setBorder(null);outer.setDividerSize(4);outer.setLeftComponent(view);outer.setRightComponent(tutor);
            inner=(JSplitPane)field(view,"studySplit");
            motion=LibraryDeparture.start(root,List.of(),()->{
                scene.removeAll();scene.add(navigation,BorderLayout.NORTH);scene.add(outer,BorderLayout.CENTER);
                LayoutMotionPanel.layoutNow(scene);
                outer.setDividerLocation((int)Math.round(outer.getWidth()*.727)-4);
                LayoutMotionPanel.layoutNow(scene);
                view.setSidePanelVisible(true,false);view.settleSidePanelLayout();
                LayoutMotionPanel.layoutNow(scene);
                outer.monitorRatio("destination",false);view.monitorStudyRatio(false);
            },loaded::incrementAndGet);
            ((Timer)field(motion,"timer")).stop();
            bounds=panelBounds();
            check(field(view,"source")==null && loaded.get()==0,"real workspace shell needs no PDF opening");
            check(inner.getLeftComponent().getWidth()>=300 && inner.getRightComponent().getWidth()>=340,
                "real PDF/summary panes have final usable widths before transition");
            check(!((Timer)field(inner.getLeftComponent(),"fade")).isRunning()
                && motionQuiet(inner.getRightComponent()),
                "initial real layout starts no independent panel resize motion");
        }
        List<Rectangle> panelBounds() {
            return List.of(outer.getBounds(),view.getBounds(),inner.getBounds(),inner.getLeftComponent().getBounds(),
                inner.getRightComponent().getBounds(),outer.getRightComponent().getBounds());
        }
        void complete()throws Exception {
            try {
                outer.monitorRatio("destination",false);view.monitorStudyRatio(false);
                check(bounds.equals(panelBounds()),"queued Swing events keep captured real pane geometry");
                motion.advance((Long)field(motion,"started")+2_000_000_000L);
                LayoutMotionPanel.layoutNow(scene);
                outer.monitorRatio("destination",false);view.monitorStudyRatio(false);
                check(loaded.get()==1 && bounds.equals(panelBounds()),"real pane geometry survives content activation and layout validation");
                check(!LayoutMotionPanel.isImmediateLayout(),"initial-layout scope always ends");
            } finally {motion.finish();view.close();}
        }
    }
    private static boolean motionQuiet(Component component)throws Exception {
        if(component instanceof LayoutMotionPanel)
            for(String name:List.of("fade","settled","entrance","contentChange"))
                if(((Timer)field(component,name)).isRunning())return false;
        if(component instanceof Container container)
            for(Component child:container.getComponents())if(child.isVisible()&&!motionQuiet(child))return false;
        return true;
    }
    private static Object field(Object object,String name)throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }
    private static void check(boolean ok,String message){checks++;if(!ok)throw new AssertionError(message);}
}
