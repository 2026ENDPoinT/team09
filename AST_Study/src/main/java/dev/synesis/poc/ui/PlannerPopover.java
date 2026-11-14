package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;

/** A bounded in-window list. Outside clicks are observed, never intercepted by a full-window cover. */
final class PlannerPopover extends JPanel {
    private static final int OPEN_MS=130;
    private final JComponent anchor,content;
    private final JLayeredPane layer;
    private final Window window;
    private final Runnable closed;
    private final KeyboardFocusManager focus=KeyboardFocusManager.getCurrentKeyboardFocusManager();
    private final KeyEventDispatcher keys=this::key;
    private final AWTEventListener outside=this::outsideEvent;
    private final Timer animation=new Timer(16,e->advance());
    private final ComponentAdapter resize=new ComponentAdapter(){@Override public void componentResized(ComponentEvent e){fit();}};
    private final WindowAdapter windowEvents=new WindowAdapter(){@Override public void windowDeactivated(WindowEvent e){close();}@Override public void windowClosed(WindowEvent e){close();}};
    private final HierarchyListener hierarchy=this::anchorChanged;
    private boolean open;
    private float amount;
    private long started;

    PlannerPopover(JComponent anchor,JComponent content,Runnable closed){
        super(new BorderLayout());this.anchor=anchor;this.content=content;this.closed=closed;
        JRootPane root=SwingUtilities.getRootPane(anchor);if(root==null)throw new IllegalArgumentException("태그 목록을 표시할 창이 없어요.");
        layer=root.getLayeredPane();window=SwingUtilities.getWindowAncestor(anchor);setOpaque(false);setFocusCycleRoot(true);add(content);
        animation.setCoalesce(true);
    }
    void showList(){
        if(open)return;open=true;MenuSelectionManager.defaultManager().clearSelectedPath();
        fit();layer.add(this,JLayeredPane.POPUP_LAYER);layoutTree(this);
        layer.addComponentListener(resize);anchor.addHierarchyListener(hierarchy);focus.addKeyEventDispatcher(keys);
        Toolkit.getDefaultToolkit().addAWTEventListener(outside,AWTEvent.MOUSE_EVENT_MASK);
        if(window!=null)window.addWindowListener(windowEvents);
        amount=0;started=System.nanoTime();setVisible(true);animation.start();repaint();
    }
    private void fit(){
        Dimension wanted=content.getPreferredSize();int w=Math.min(wanted.width,Math.max(1,layer.getWidth()-16)),h=Math.min(wanted.height,Math.max(1,layer.getHeight()-16));
        Point at=SwingUtilities.convertPoint(anchor,0,anchor.getHeight()+4,layer);
        int x=Math.max(8,Math.min(at.x,layer.getWidth()-w-8)),y=at.y;
        if(y+h>layer.getHeight()-8)y=SwingUtilities.convertPoint(anchor,0,-h-4,layer).y;
        y=Math.max(8,Math.min(y,layer.getHeight()-h-8));Rectangle before=getBounds();setBounds(x,y,w,h);
        if(getParent()!=null){layoutTree(this);layer.repaint(before.union(getBounds()));}
    }
    private void advance(){
        float t=Math.min(1,(System.nanoTime()-started)/(OPEN_MS*1_000_000f));amount=1-(1-t)*(1-t)*(1-t);
        if(t>=1)animation.stop();repaint();
    }
    @Override public void paint(Graphics graphics){
        Graphics2D copy=(Graphics2D)graphics.create();
        try{copy.setComposite(AlphaComposite.SrcOver.derive(amount));copy.translate(0,Math.round((1-amount)*4));if(Boolean.TRUE.equals(content.getClientProperty("planner.dropReveal")))copy.clipRect(0,0,getWidth(),Math.round(getHeight()*amount));super.paint(copy);}finally{copy.dispose();}
    }
    private void outsideEvent(AWTEvent event){
        if(!open||!(event instanceof MouseEvent mouse)||mouse.getID()!=MouseEvent.MOUSE_PRESSED)return;
        Component source=mouse.getComponent();if(source==null||SwingUtilities.getWindowAncestor(source)!=window&&source!=window)return;
        Point point=SwingUtilities.convertPoint(source,mouse.getPoint(),layer);
        Rectangle trigger=SwingUtilities.convertRectangle(anchor.getParent(),anchor.getBounds(),layer);
        if(!getBounds().contains(point)&&!trigger.contains(point))close();
    }
    private boolean key(KeyEvent event){
        if(open&&event.getID()==KeyEvent.KEY_PRESSED&&event.getKeyCode()==KeyEvent.VK_ESCAPE&&SwingUtilities.getWindowAncestor(event.getComponent())==window){close();event.consume();return true;}
        if(open&&event.getID()==KeyEvent.KEY_PRESSED&&event.getKeyCode()==KeyEvent.VK_TAB&&SwingUtilities.getWindowAncestor(event.getComponent())==window&&!inside(event.getComponent())){
            Component first=getFocusTraversalPolicy().getDefaultComponent(this);if(first!=null){first.requestFocusInWindow();event.consume();return true;}
        }
        return false;
    }
    private boolean inside(Component child){return child==this||SwingUtilities.isDescendingFrom(child,this);}
    private void anchorChanged(HierarchyEvent event){if((event.getChangeFlags()&(HierarchyEvent.SHOWING_CHANGED|HierarchyEvent.PARENT_CHANGED))!=0&&!anchor.isShowing())close();}
    void close(){
        if(!open)return;open=false;animation.stop();focus.removeKeyEventDispatcher(keys);Toolkit.getDefaultToolkit().removeAWTEventListener(outside);
        layer.removeComponentListener(resize);anchor.removeHierarchyListener(hierarchy);
        Component current=focus.getFocusOwner();if(current!=null&&inside(current))anchor.requestFocusInWindow();
        if(window!=null)window.removeWindowListener(windowEvents);Rectangle dirty=getBounds();layer.remove(this);layer.repaint(dirty);closed.run();
    }
    private static void layoutTree(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container nested)layoutTree(nested);}
}
