package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;

/** Paint-only stagger and artwork hover; bounds, hit targets and drag gestures stay fixed. */
public class LibraryItemMotion extends StudyTheme.RoundedPanel implements LibraryMotionClock.Task {
    private boolean pending,entering,hovered;
    private int order;
    private long entered,hoverStarted;
    private double entrance=1,hover,hoverFrom,hoverTarget;
    public LibraryItemMotion(boolean list) {
        super(new BorderLayout(),list?0:16,list?StudyTheme.PAPER:new Color(0,0,0,0),list?LibraryDesign.LINE:null);
        addHierarchyListener(event->{
            if((event.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&!isShowing())settle();
        });
    }
    public record Entrance(boolean pending,long started,double progress) {}
    private static final Entrance WAITING=new Entrance(true,0,0);
    public Entrance entranceState(){return pending?WAITING:entering?new Entrance(false,entered,entrance):null;}
    public void restoreEntrance(Entrance state) {
        pending=state!=null&&state.pending();entering=false;entrance=1;
        if(state!=null&&!state.pending()) {
            entered=state.started();entrance=state.progress();entering=LibraryMotionClock.add(this);
            if(!entering)entrance=1;
        }
    }
    public void order(int index){order=index;}
    public void entrance(int index,boolean replay){order=index;pending=replay;entering=false;entrance=1;}
    public void installHover() {
        MouseAdapter listener=new MouseAdapter(){
            @Override public void mouseEntered(MouseEvent event){hover(true);}
            @Override public void mouseExited(MouseEvent event){
                Point at=SwingUtilities.convertPoint(event.getComponent(),event.getPoint(),LibraryItemMotion.this);
                if(!contains(at))hover(false);
            }
        };
        install(this,listener);
    }
    private static void install(Component component,MouseAdapter listener) {
        component.addMouseListener(listener);
        if(component instanceof Container container)for(Component child:container.getComponents())install(child,listener);
    }
    private void hover(boolean value) {
        if(hovered==value)return;hovered=value;
        hoverFrom=hover;hoverTarget=value?1:0;hoverStarted=System.nanoTime();
        if(LibraryMotionClock.reduced()||!isShowing()||!LibraryMotionClock.add(this)){hover=hoverTarget;repaint();}
    }
    private int visibleOrder() {
        if(getParent() instanceof JComponent parent&&parent.getLayout() instanceof GridLayout layout) {
            int row=Math.max(0,(parent.getVisibleRect().y-parent.getInsets().top)/Math.max(1,getHeight()+layout.getVgap()));
            return Math.max(0,order-row*layout.getColumns());
        }
        return order%8;
    }
    @Override public boolean advance(long now) {
        if(!isShowing()||getVisibleRect().isEmpty()){settle();return false;}
        if(entering){entrance=LibraryMotionClock.ease((now-entered)/550_000_000d);if(now-entered>=550_000_000L)entering=false;}
        hover=hoverFrom+(hoverTarget-hoverFrom)*LibraryMotionClock.ease((now-hoverStarted)/350_000_000d);
        if(now-hoverStarted>=350_000_000L)hover=hoverTarget;
        repaint();return entering||hover!=hoverTarget;
    }
    public void settle() {
        LibraryMotionClock.remove(this);entering=false;entrance=1;hover=hoverFrom=hoverTarget=0;hovered=false;
    }
    @Override public void paint(Graphics graphics) {
        JRootPane root=SwingUtilities.getRootPane(this);
        if(root!=null && root.getGlassPane() instanceof LoginTransition) {
            // The transition snapshots the destination before revealing it. Keep
            // cards out of that snapshot and start their stagger on the first
            // live paint after the transition restores the original glass pane.
            LibraryMotionClock.remove(this);pending=true;entering=false;entrance=1;
            return;
        }
        if(pending&&isShowing()) {
            pending=false;
            if(!LibraryMotionClock.reduced()) {
                entered=System.nanoTime()+Math.min(8,visibleOrder())*35_000_000L;
                entering=LibraryMotionClock.add(this);if(entering)entrance=0;
            }
        }
        if(!entering){super.paint(graphics);return;}
        if(entrance<=0)return;
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setComposite(AlphaComposite.SrcOver.derive((float)entrance));g.translate(0,14*(1-entrance));
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            super.paint(g);
        } finally {g.dispose();}
    }
    /** Existing artwork and caches are reused; no bitmap is allocated for hover frames. */
    public static JComponent artwork(JComponent artwork) {
        JPanel host=new JPanel(new BorderLayout()) {
            @Override protected void paintChildren(Graphics graphics) {
                LibraryItemMotion card=(LibraryItemMotion)SwingUtilities.getAncestorOfClass(LibraryItemMotion.class,this);
                double t=card==null?0:card.hover;
                if(t==0){super.paintChildren(graphics);return;}
                Graphics2D g=(Graphics2D)graphics.create();
                try {
                    // Translation retains the thumbnail's cached DPI raster. Scaling here would
                    // rebuild area-averaged PDF previews on every hover frame on low-end PCs.
                    g.translate(0,-4*t);
                    g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                    super.paintChildren(g);
                } finally {g.dispose();}
            }
        };
        host.setOpaque(false);host.add(artwork);return host;
    }
    @Override public void removeNotify(){settle();super.removeNotify();}
}
