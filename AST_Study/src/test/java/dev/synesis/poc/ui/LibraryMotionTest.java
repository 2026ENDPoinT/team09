package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.MouseEvent;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.util.concurrent.atomic.AtomicInteger;

/** Native-free lifecycle, cache reuse, bounded work and real scene-paint checks. */
public final class LibraryMotionTest {
    private static int checks;
    private static final class Card extends LibraryItemMotion {
        boolean visible=true;int layouts;
        Card(){super(false);setSize(240,260);}
        @Override public boolean isShowing(){return visible;}
        @Override public Rectangle getVisibleRect(){return visible?new Rectangle(0,0,getWidth(),getHeight()):new Rectangle();}
        @Override public void doLayout(){layouts++;super.doLayout();}
    }
    public static void main(String[] args)throws Exception {
        try {SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception failure){throw new RuntimeException(failure);}});}
        catch(Throwable failure){failure.printStackTrace();System.exit(1);}
        System.out.println("PASS: "+checks+" library motion / cache / navigation / memory checks");System.exit(0);
    }
    private static void run()throws Exception {
        check(LibraryMotionClock.ease(0)==0&&LibraryMotionClock.ease(1)==1,"ease endpoints");
        for(int i=1;i<101;i++)check(LibraryMotionClock.ease(i/100d)>=LibraryMotionClock.ease((i-1)/100d),"ease monotonicity");
        Card card=new Card();JPanel solid=new JPanel();solid.setBackground(Color.BLUE);card.add(solid);card.doLayout();
        card.entrance(0,true);BufferedImage initial=paint(card);long entered=(Long)get(card,LibraryItemMotion.class,"entered");
        check((initial.getRGB(100,100)&0xffffff)==0xffffff,"entrance begins transparent");
        int layouts=card.layouts;Rectangle bounds=solid.getBounds();
        LibraryMotionClock.tick(entered+150_000_000L);BufferedImage middle=paint(card);
        check((middle.getRGB(100,100)&0xffffff)!=0xffffff,"entrance becomes visible");
        LibraryMotionClock.tick(entered+900_000_000L);paint(card);
        check(card.layouts==layouts&&solid.getBounds().equals(bounds),"entrance never reflows children or hit bounds");
        check(LibraryMotionClock.activeCount()==0,"clock stops after entrance");
        Card loading=new Card();loading.entrance(0,true);paint(loading);
        long firstStart=(Long)get(loading,LibraryItemMotion.class,"entered");
        LibraryMotionClock.tick(firstStart+120_000_000L);
        LibraryItemMotion.Entrance inFlight=loading.entranceState();loading.settle();
        Card refreshed=new Card();refreshed.restoreEntrance(inFlight);
        check(((Long)get(refreshed,LibraryItemMotion.class,"entered"))==firstStart,"async metadata refresh preserves entrance timeline");
        check(refreshed.entranceState().progress()==inFlight.progress(),"refresh does not flash back to invisible or skip entrance");
        LibraryMotionClock.tick(firstStart+1_000_000_000L);
        check(LibraryMotionClock.activeCount()==0,"refreshed entrance settles cleanly");

        Card offscreen=new Card();offscreen.visible=false;offscreen.entrance(0,true);paint(offscreen);
        check(LibraryMotionClock.activeCount()==0,"offscreen cards allocate no active effect");

        Card hover=new Card();BufferedImage art=new BufferedImage(192,192,BufferedImage.TYPE_INT_ARGB);
        Graphics2D brush=art.createGraphics();brush.setColor(Color.BLUE);brush.fillRect(0,0,192,192);brush.dispose();
        DeviceImageIcon icon=DeviceImageIcon.thumbnail(art,64,64);JLabel label=new JLabel(icon);
        JComponent wrapper=LibraryItemMotion.artwork(label);hover.add(wrapper);hover.doLayout();wrapper.doLayout();hover.installHover();paint(hover);
        Object raster=get(icon,DeviceImageIcon.class,"raster");
        label.dispatchEvent(new MouseEvent(label,MouseEvent.MOUSE_ENTERED,0,0,10,10,0,false));
        long start=(Long)get(hover,LibraryItemMotion.class,"hoverStarted");
        for(int ms:new int[]{60,120,190,280,400}){LibraryMotionClock.tick(start+ms*1_000_000L);paint(hover);check(get(icon,DeviceImageIcon.class,"raster")==raster,"hover reuses original thumbnail raster");}
        check(LibraryMotionClock.activeCount()==0,"steady hover has no running timer");
        hover.visible=false;hover.advance(System.nanoTime());check(LibraryMotionClock.activeCount()==0,"hidden hover is released");
        LibraryMotionClock.Task[] tasks=new LibraryMotionClock.Task[49];
        for(int i=0;i<49;i++){tasks[i]=new LibraryMotionClock.Task(){public boolean advance(long now){return true;}};check(LibraryMotionClock.add(tasks[i])==(i<48),"active-effect work budget");}
        for(var task:tasks)LibraryMotionClock.remove(task);
        check(LibraryMotionClock.activeCount()==0,"budget test releases clock references");

        JPanel view=new JPanel(new BorderLayout());view.setBackground(Color.WHITE);view.add(new JLabel("Original"));
        LibrarySectionMotion scene=new LibrarySectionMotion(view);
        JPanel host=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return true;}};
        host.add(scene.component());host.setSize(1800,1200);host.addNotify();layout(host);
        AtomicInteger original=new AtomicInteger(),latest=new AtomicInteger();
        scene.change(original::incrementAndGet,false);check(scene.active(),"sidebar departure uses real layer");
        BufferedImage picture=(BufferedImage)get(scene,LibrarySectionMotion.class,"picture");
        check((long)picture.getWidth()*picture.getHeight()<=400_000,"scene preview stays under 1.6MB");
        scene.change(()->{latest.incrementAndGet();view.add(new JLabel("Latest"));},false);
        long begin=(Long)get(scene,LibrarySectionMotion.class,"started");
        LibraryMotionClock.tick(begin+200_000_000L);
        check(original.get()==0&&latest.get()==1,"rapid sidebar selection switches only to latest destination");
        check(scene.active(),"destination enters from bounded preview");
        LibraryMotionClock.tick(begin+900_000_000L);
        check(!scene.active()&&get(scene,LibrarySectionMotion.class,"picture")==null,"completed sidebar motion frees pixels");
        check(LibraryMotionClock.activeCount()==0,"no background timer survives menu transition");
        scene.change(original::incrementAndGet,false);scene.cancel();
        check(original.get()==0&&!scene.active(),"cancelled navigation never runs after close");
        java.util.concurrent.atomic.AtomicBoolean selected=new java.util.concurrent.atomic.AtomicBoolean(true);
        LibrarySidebar sidebar=new LibrarySidebar(selected::get);host.add(sidebar,BorderLayout.WEST);layout(host);
        JButton nav=null;
        for(Component component:sidebar.getComponents())if(component instanceof JButton button&&button.getText().equals("내 문서"))nav=button;
        check(nav!=null&&nav.isShowing(),"sidebar hover test uses real button hierarchy");
        Rectangle navBounds=nav.getBounds();nav.getModel().setRollover(true);
        LibraryMotionClock.tick(System.nanoTime()+100_000_000L);paint(sidebar);
        check(LibraryMotionClock.activeCount()>0,"sidebar hover eases instead of jumping");
        LibraryMotionClock.tick(System.nanoTime()+1_000_000_000L);paint(sidebar);
        check(nav.getBounds().equals(navBounds)&&LibraryMotionClock.activeCount()==0,"sidebar hover keeps hit target fixed and settles");
        selected.set(false);paint(sidebar);LibraryMotionClock.tick(System.nanoTime()+1_000_000_000L);
        check(LibraryMotionClock.activeCount()==0,"sidebar active color transition settles");
        nav.getModel().setRollover(false);LibraryMotionClock.tick(System.nanoTime()+1_000_000_000L);
        host.removeNotify();
    }
    private static BufferedImage paint(JComponent component){
        BufferedImage image=new BufferedImage(component.getWidth(),component.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());component.paint(g);g.dispose();return image;
    }
    private static void layout(Container parent){parent.doLayout();for(Component child:parent.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    private static Object get(Object instance,Class<?> type,String name)throws Exception{Field f=type.getDeclaredField(name);f.setAccessible(true);return f.get(instance);}
    private static void check(boolean ok,String reason){checks++;if(!ok)throw new AssertionError(reason);}
}
