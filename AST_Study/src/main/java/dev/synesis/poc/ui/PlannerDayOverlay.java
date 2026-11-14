package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;

/** The existing window stays fixed; only the modal panel grows into place. */
final class PlannerDayOverlay extends JPanel {
    private static final int OPEN_MS=150;
    private final JRootPane root;
    private final JLayeredPane layer;
    private final JPanel panel;
    private final int width,height;
    private final Window window;
    private final KeyboardFocusManager focus=KeyboardFocusManager.getCurrentKeyboardFocusManager();
    private final Component previousFocus;
    private final JButton previousDefault,defaultButton;
    private final KeyEventDispatcher keys=this::key;
    private final ComponentAdapter resize=new ComponentAdapter(){@Override public void componentResized(ComponentEvent e){fit();}};
    private final HierarchyListener hierarchy=e->{if((e.getChangeFlags()&HierarchyEvent.DISPLAYABILITY_CHANGED)!=0&&!isDisplayable())closeOverlay();};
    final Timer animation=new Timer(16,e->advance());
    float progress=1;
    private long started;
    private boolean open;
    private BufferedImage openingFrame;

    PlannerDayOverlay(JRootPane root,JPanel panel,int width,int height){
        super(null);this.root=root;this.layer=root.getLayeredPane();this.panel=panel;this.width=width;this.height=height;
        window=SwingUtilities.getWindowAncestor(root);previousFocus=focus.getFocusOwner();previousDefault=root.getDefaultButton();
        defaultButton=panel.getClientProperty("planner.defaultButton") instanceof JButton button?button:null;
        setOpaque(false);setFocusCycleRoot(true);add(panel);animation.setCoalesce(true);
        addMouseListener(new MouseAdapter(){@Override public void mousePressed(MouseEvent e){if(SwingUtilities.isLeftMouseButton(e))PlannerDialogs.requestClose(panel);}});
        panel.addMouseListener(new MouseAdapter(){});
    }
    void showOverlay(){
        if(open)return;open=true;MenuSelectionManager.defaultManager().clearSelectedPath();panel.putClientProperty("planner.close",(Runnable)this::closeOverlay);
        progress=0;fit();captureOpeningFrame();layer.add(this,JLayeredPane.MODAL_LAYER);layoutTree(this);layer.addComponentListener(resize);addHierarchyListener(hierarchy);
        root.setDefaultButton(defaultButton);focus.addKeyEventDispatcher(keys);started=System.nanoTime();animation.start();repaint();
        SwingUtilities.invokeLater(()->{if(open)focusPanel();});
    }
    private void fit(){setBounds(0,0,layer.getWidth(),layer.getHeight());layoutTree(this);}
    private void captureOpeningFrame(){
        // Swing's live child buffers do not reliably follow a parent's animated transform.
        // Composite a single transparent rounded image during opening, then resume live controls.
        GraphicsConfiguration config=root.getGraphicsConfiguration();double scale=config==null?1:config.getDefaultTransform().getScaleX();
        openingFrame=new BufferedImage(Math.max(1,(int)Math.ceil(panel.getWidth()*scale)),Math.max(1,(int)Math.ceil(panel.getHeight()*scale)),BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=openingFrame.createGraphics();
        try{g.scale(scale,scale);g.clip(new java.awt.geom.RoundRectangle2D.Double(0,0,panel.getWidth(),panel.getHeight(),32,32));panel.printAll(g);}finally{g.dispose();}
    }
    @Override public void doLayout(){int w=Math.max(1,Math.min(width,getWidth()-32)),h=Math.max(1,Math.min(height,getHeight()-32));panel.setBounds((getWidth()-w)/2,(getHeight()-h)/2,w,h);}
    private void advance(){float t=Math.min(1,(System.nanoTime()-started)/(OPEN_MS*1_000_000f));progress=1-(1-t)*(1-t)*(1-t);if(t>=1)animation.stop();repaint(panel.getBounds());}
    @Override protected boolean isPaintingOrigin(){return true;}
    @Override protected void paintComponent(Graphics graphics){super.paintComponent(graphics);graphics.setColor(new Color(0,6,18,64));graphics.fillRect(0,0,getWidth(),getHeight());}
    @Override protected void paintChildren(Graphics graphics){
        Graphics2D g=PlannerStyle.quality(graphics);
        try{
            if(progress<1&&openingFrame!=null){double scale=.96+.04*progress,cx=panel.getX()+panel.getWidth()/2.0,cy=panel.getY()+panel.getHeight()/2.0;g.translate(cx,cy);g.scale(scale,scale);g.translate(-cx,-cy);g.setComposite(AlphaComposite.SrcOver.derive(progress));g.drawImage(openingFrame,panel.getX(),panel.getY(),panel.getWidth(),panel.getHeight(),null);}
            else super.paintChildren(g);
        }finally{g.dispose();}
    }
    private void focusPanel(){Component target=defaultButton!=null?defaultButton:getFocusTraversalPolicy().getDefaultComponent(this);if(target!=null)target.requestFocusInWindow();}
    boolean key(KeyEvent event){
        if(!open||SwingUtilities.getWindowAncestor(event.getComponent())!=window)return false;
        // Menus and tag pickers above the editor handle their own keys and Escape first.
        if(MenuSelectionManager.defaultManager().getSelectedPath().length>0)return false;
        for(Component child:layer.getComponents())if(child instanceof PlannerPopover&&child.isVisible()&&layer.getLayer(child)>layer.getLayer(this))return false;
        if(event.getID()==KeyEvent.KEY_PRESSED&&event.getKeyCode()==KeyEvent.VK_ESCAPE){PlannerDialogs.requestClose(panel);event.consume();return true;}
        if(!SwingUtilities.isDescendingFrom(event.getComponent(),this)){focusPanel();event.consume();return true;}
        return false;
    }
    void closeOverlay(){
        if(!open)return;open=false;animation.stop();openingFrame=null;focus.removeKeyEventDispatcher(keys);layer.removeComponentListener(resize);removeHierarchyListener(hierarchy);
        if(root.getDefaultButton()==defaultButton)root.setDefaultButton(previousDefault);layer.remove(this);layer.repaint();
        if(previousFocus!=null&&previousFocus.isShowing())previousFocus.requestFocusInWindow();
    }
    private static void layoutTree(Container container){container.doLayout();for(Component child:container.getComponents())if(child instanceof Container nested)layoutTree(nested);}
}
