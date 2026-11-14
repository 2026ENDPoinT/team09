package dev.synesis.poc.ui;

import java.awt.Component;
import java.awt.Container;
import java.awt.Point;
import java.awt.AWTEventMulticaster;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.event.MouseWheelEvent;
import java.awt.event.MouseWheelListener;
import javax.swing.JScrollPane;
import javax.swing.SwingUtilities;

/** Shared input only; callers retain their existing viewport/painting behavior. */
public class UnifiedScrollPane extends JScrollPane {
    private final PreciseWheelInput wheel=new PreciseWheelInput();
    private MouseWheelListener inputListener;
    public UnifiedScrollPane(){this(null);}
    public UnifiedScrollPane(Component view){this(view,VERTICAL_SCROLLBAR_AS_NEEDED,HORIZONTAL_SCROLLBAR_AS_NEEDED);}
    public UnifiedScrollPane(int verticalPolicy,int horizontalPolicy){this(null,verticalPolicy,horizontalPolicy);}
    public UnifiedScrollPane(Component view,int verticalPolicy,int horizontalPolicy){
        super(view,verticalPolicy,horizontalPolicy);
        getVerticalScrollBar().setUnitIncrement(ScrollPolicy.PIXELS_PER_UNIT);
        getHorizontalScrollBar().setUnitIncrement(ScrollPolicy.PIXELS_PER_UNIT);
        MouseAdapter resetOnDrag=new MouseAdapter(){
            @Override public void mousePressed(MouseEvent event){resetWheelInput();}
        };
        getVerticalScrollBar().addMouseListener(resetOnDrag);
        getHorizontalScrollBar().addMouseListener(resetOnDrag);
    }
    @Override protected void processMouseWheelEvent(MouseWheelEvent event){
        if(event.isConsumed())return;
        if(!isWheelScrollingEnabled()||event.isControlDown()){
            super.processMouseWheelEvent(event);return;
        }
        double rotation=event.getPreciseWheelRotation();
        if(rotation==0||!Double.isFinite(rotation))return;
        if(!wheel.scroll(this,event))forwardWheel(event,rotation);
        else if(wheel.overflowPixels()!=0)forwardWheel(event,ScrollPolicy.rotationForPixels(event,wheel.overflowPixels()));
        // Do not fall back to Swing's integer-notch handler for an unconsumed
        // fine input: it would drop fractions or apply a different distance.
        wheelInput(event);
        if(inputListener!=null)inputListener.mouseWheelMoved(event);
    }
    private void forwardWheel(MouseWheelEvent event,double rotation){
        for(Container parent=getParent();parent!=null;parent=parent.getParent()){
            if(!(parent instanceof JScrollPane pane)||!pane.isWheelScrollingEnabled())continue;
            Point point=SwingUtilities.convertPoint(this,event.getPoint(),pane);
            MouseWheelEvent forwarded=new MouseWheelEvent(pane,event.getID(),event.getWhen(),event.getModifiersEx(),
                point.x,point.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),event.isPopupTrigger(),
                event.getScrollType(),event.getScrollAmount(),rotation==event.getPreciseWheelRotation()?event.getWheelRotation():(int)rotation,rotation);
            pane.dispatchEvent(forwarded);
            if(forwarded.isConsumed())event.consume();
            return;
        }
    }
    /** User-intent observers run once after movement, without dispatching to Swing's wheel handler twice. */
    protected void wheelInput(MouseWheelEvent event){}
    public void addWheelInputListener(MouseWheelListener listener){inputListener=AWTEventMulticaster.add(inputListener,listener);}
    public void removeWheelInputListener(MouseWheelListener listener){inputListener=AWTEventMulticaster.remove(inputListener,listener);}
    protected final void resetWheelInput(){if(wheel!=null)wheel.reset();}
    @Override public void setViewportView(Component view){resetWheelInput();super.setViewportView(view);}
    @Override public void removeNotify(){resetWheelInput();super.removeNotify();}
}
