package dev.synesis.poc.ui;

import javax.swing.JComponent;
import javax.swing.JLayer;
import javax.swing.JSplitPane;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.plaf.LayerUI;
import java.awt.AWTEvent;
import java.awt.Component;
import java.awt.Color;
import java.awt.Cursor;
import java.awt.Graphics;
import java.awt.Point;
import java.awt.Rectangle;
import java.awt.event.MouseEvent;

/** Wide drag target; only lightweight shells follow the pointer during a drag. */
public final class SplitDividerHitLayer extends LayerUI<JSplitPane> {
    private static final int HIT_PADDING = 6;
    private final int dividerPaintInset;
    private final Color dividerEndBackground;
    private boolean dragging;
    private int dragOffset, pendingLocation;
    private JSplitPane activeSplit;
    private java.util.List<LayoutMotionPanel> motionPanels=java.util.List.of();
    private final Timer dragTimer = new Timer(16, event -> applyPendingLocation());

    public SplitDividerHitLayer() { this(0, Color.WHITE); }

    /** Inset only the visible divider; layout, proportions and the drag target stay intact. */
    public SplitDividerHitLayer(int dividerPaintInset, Color dividerEndBackground) {
        this.dividerPaintInset = Math.max(0, dividerPaintInset);
        this.dividerEndBackground = dividerEndBackground;
    }

    @Override public void paint(Graphics graphics, JComponent component) {
        super.paint(graphics, component);
        if(dividerPaintInset==0 || !(component instanceof JLayer<?> layer)
            || !(layer.getView() instanceof JSplitPane split) || split.getDividerSize()==0
            || !(split.getUI() instanceof javax.swing.plaf.basic.BasicSplitPaneUI ui))return;
        Component divider=ui.getDivider();
        if(divider==null || !divider.isVisible() || divider.getParent()==null)return;
        Rectangle bounds=SwingUtilities.convertRectangle(divider.getParent(),divider.getBounds(),layer);
        Graphics g=graphics.create();
        try {
            g.setColor(dividerEndBackground);
            if(split.getOrientation()==JSplitPane.HORIZONTAL_SPLIT) {
                int inset=Math.min(dividerPaintInset,bounds.height/2);
                g.fillRect(bounds.x,bounds.y,bounds.width,inset);
                g.fillRect(bounds.x,bounds.y+bounds.height-inset,bounds.width,inset);
            } else {
                int inset=Math.min(dividerPaintInset,bounds.width/2);
                g.fillRect(bounds.x,bounds.y,inset,bounds.height);
                g.fillRect(bounds.x+bounds.width-inset,bounds.y,inset,bounds.height);
            }
        } finally {g.dispose();}
    }

    private void applyPendingLocation() {
        if(activeSplit==null)return;
        int minimum=activeSplit.getMinimumDividerLocation(),maximum=activeSplit.getMaximumDividerLocation();
        int location=Math.max(minimum,Math.min(Math.max(minimum,maximum),pendingLocation));
        if(activeSplit.getDividerLocation()!=location) {
            activeSplit.setDividerLocation(location);
            activeSplit.doLayout();
        }
    }

    private void stopDragging() {
        dragTimer.stop();
        if(activeSplit!=null) {
            // BasicSplitPaneDivider ignores consumed events. The layer owns
            // this gesture, so its native drag listener is disabled temporarily.
            activeSplit.setEnabled(true);
            activeSplit.putClientProperty("synesis.dividerDragging",Boolean.FALSE);
            activeSplit.putClientProperty("synesis.dividerRevision",System.nanoTime());
        }
        LayoutMotionPanel.releaseTree(motionPanels);motionPanels=java.util.List.of();
        activeSplit=null;dragging=false;
    }

    @Override public void installUI(JComponent component) {
        super.installUI(component);
        ((JLayer<?>)component).setLayerEventMask(AWTEvent.MOUSE_EVENT_MASK | AWTEvent.MOUSE_MOTION_EVENT_MASK);
    }

    @Override public void uninstallUI(JComponent component) {
        stopDragging();
        ((JLayer<?>)component).setLayerEventMask(0);
        super.uninstallUI(component);
    }

    @Override protected void processMouseEvent(MouseEvent event,JLayer<? extends JSplitPane> layer) {
        JSplitPane split=layer.getView();
        if(split==null)return;
        Point point=SwingUtilities.convertPoint(event.getComponent(),event.getPoint(),split);
        if(event.getID()==MouseEvent.MOUSE_PRESSED && SwingUtilities.isLeftMouseButton(event)
            && split.isEnabled() && !event.isConsumed() && inHitTarget(split,point)) {
            dragging=true;activeSplit=split;
            motionPanels=LayoutMotionPanel.holdTree(split);
            split.putClientProperty("synesis.dividerDragging",Boolean.TRUE);
            dragOffset=coordinate(split,point)-split.getDividerLocation();
            pendingLocation=split.getDividerLocation();
            split.setEnabled(false);
            dragTimer.start();
            event.consume();
        } else if(event.getID()==MouseEvent.MOUSE_RELEASED && dragging) {
            pendingLocation=coordinate(split,point)-dragOffset;
            applyPendingLocation();
            stopDragging();
            event.consume();
        }
    }

    @Override protected void processMouseMotionEvent(MouseEvent event,JLayer<? extends JSplitPane> layer) {
        JSplitPane split=layer.getView();
        if(split==null)return;
        Point point=SwingUtilities.convertPoint(event.getComponent(),event.getPoint(),split);
        if(event.getID()==MouseEvent.MOUSE_DRAGGED && dragging) {
            pendingLocation=coordinate(split,point)-dragOffset;
            event.consume();
        } else if(event.getID()==MouseEvent.MOUSE_MOVED) {
            split.setCursor(Cursor.getPredefinedCursor(inHitTarget(split,point)
                ?split.getOrientation()==JSplitPane.HORIZONTAL_SPLIT?Cursor.E_RESIZE_CURSOR:Cursor.N_RESIZE_CURSOR
                :Cursor.DEFAULT_CURSOR));
        }
    }

    private static int coordinate(JSplitPane split,Point point) {
        return split.getOrientation()==JSplitPane.HORIZONTAL_SPLIT?point.x:point.y;
    }

    private static boolean inHitTarget(JSplitPane split,Point point) {
        if(split.getDividerSize()==0 || split.getLeftComponent()==null || split.getRightComponent()==null)
            return false;
        Component divider=split.getUI() instanceof javax.swing.plaf.basic.BasicSplitPaneUI ui
            ?ui.getDivider():null;
        if(divider==null || !divider.isVisible())return false;
        Rectangle hit=new Rectangle(divider.getBounds());
        if(split.getOrientation()==JSplitPane.HORIZONTAL_SPLIT)hit.grow(HIT_PADDING,0);
        else hit.grow(0,HIT_PADDING);
        return split.contains(point) && hit.contains(point);
    }
}
