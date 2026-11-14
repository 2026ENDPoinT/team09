package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;

/** Floating presentation only. The existing tutor owns its conversation, workers and animations. */
public final class FloatingMentor extends JComponent implements AutoCloseable {
    // The tutor reading column is capped at 960px, including its side padding.
    private static final int MAX_CARD_WIDTH=960+2; // Include the card's 1px border.
    private static final int ORB_EXTENT=(int)Math.ceil(MentorAvatar.HOVER_SIZE*96d/68),ORB_CENTER=ORB_EXTENT/2;
    private static final int ORB_OVERHANG=(ORB_EXTENT-Math.round(MentorAvatar.SIZE*96f/68f))/2;
    private final LayoutMotionPanel body=LayoutMotionPanel.transparentHost(new BorderLayout(),new Insets(0,0,0,0));
    private final Card card=new Card();
    private final JButton orb=new JButton(){
        @Override protected void paintComponent(Graphics graphics){
            MentorAvatar.paint(graphics,getWidth()/2d,getHeight()/2d,hover);
        }
    };
    private final JComponent northwest=grip(Cursor.NW_RESIZE_CURSOR),southeast=grip(Cursor.SE_RESIZE_CURSOR);
    private final Timer motion=new Timer(16,e->tick());
    private boolean open,hovered,dragged;
    private float progress,from,hover;
    private long started,lastTick;
    private Point orbPosition,cardPosition,moveTarget;
    private Point pendingOrb;
    private double moveX,moveY;
    private Dimension requested=new Dimension(460,700);
    private Rectangle pendingBounds;
    private Rectangle resizeOrigin;
    private Point resizeOrbOrigin;
    private boolean orbAtRight,orbAtBottom;
    private BufferedImage snapshot;
    private boolean openingMotion,settling;
    private boolean pointerMoving,capturingBackdrop;
    private BufferedImage backdrop;
    private java.util.List<LayoutMotionPanel> resizeHold=java.util.List.of();
    private Window window;
    private final WindowAdapter activity=new WindowAdapter(){
        @Override public void windowDeactivated(WindowEvent e){settle();}
    };

    public FloatingMentor(){
        body.setMotionBudget(60,90,524_288);
        body.putClientProperty("synesis.smoothSnapshot",true);
        setLayout(null);setOpaque(false);card.add(body);add(card);add(orb);add(northwest);add(southeast);
        setComponentZOrder(northwest,0);setComponentZOrder(southeast,0);setComponentZOrder(orb,0);
        card.setVisible(false);northwest.setVisible(false);southeast.setVisible(false);
        orb.setBorder(null);orb.setOpaque(false);orb.setContentAreaFilled(false);orb.setFocusPainted(false);
        orb.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));orb.setToolTipText("AI멘토 열기 · 드래그해서 이동");
        orb.getAccessibleContext().setAccessibleName("AI멘토 열기 또는 접기");
        orb.addActionListener(e->{if(!dragged)setOpen(!open);});
        MouseAdapter orbDrag=new MouseAdapter(){
            private Point press,initial;
            @Override public void mouseEntered(MouseEvent e){hovered=true;wake();}
            @Override public void mouseExited(MouseEvent e){hovered=false;wake();}
            @Override public void mousePressed(MouseEvent e){
                if(!SwingUtilities.isLeftMouseButton(e))return;
                dragged=false;press=point(e);initial=orb.getLocation();
            }
            @Override public void mouseDragged(MouseEvent e){
                if(press==null)return;Point now=point(e);if(!dragged&&now.distance(press)<5)return;
                dragged=true;beginPointerMovement();
                pendingOrb=new Point(initial.x+now.x-press.x,initial.y+now.y-press.y);wake();e.consume();
            }
            @Override public void mouseReleased(MouseEvent e){
                press=null;applyPendingOrb();pointerMoving=false;finishMovement();SwingUtilities.invokeLater(()->dragged=false);
            }
        };
        orb.addMouseListener(orbDrag);orb.addMouseMotionListener(orbDrag);
        installGesture(northwest,-1);installGesture(southeast,1);
        motion.setCoalesce(true);
        addHierarchyListener(e->{if((e.getChangeFlags()&HierarchyEvent.SHOWING_CHANGED)!=0&&!isShowing())settle();});
    }
    public void setContent(JPanel tutor){
        settle();body.removeAll();body.add(MistWorkspaceTheme.shadows(tutor),BorderLayout.CENTER);tutor.setVisible(true);
        if(tutor.getClientProperty("synesis.floatingDragHandle") instanceof JComponent handle)installDragHandle(handle);
        body.revalidate();body.repaint();
    }
    private void installDragHandle(JComponent handle){
        if(Boolean.TRUE.equals(handle.getClientProperty("synesis.mentorDragInstalled")))return;
        handle.putClientProperty("synesis.mentorDragInstalled",true);installGesture(handle,0);
        for(Component child:handle.getComponents())if(child instanceof JLabel label)installGesture(label,0);
    }
    public boolean isOpen(){return open;}
    /** Independent of the study tabs; both entry points share the same chat and open state. */
    public JToggleButton createNavigationToggle(){
        JToggleButton button=new StudyTabStrip.Tab("AI멘토");
        button.setPreferredSize(new Dimension(100,40));
        button.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        Runnable sync=()->{
            button.setSelected(open);
            String action=open?"AI멘토 채팅 닫기":"AI멘토 채팅 열기";
            button.setToolTipText(action);button.getAccessibleContext().setAccessibleName(action);
        };
        button.addActionListener(e->setOpen(button.isSelected()));
        addPropertyChangeListener("open",e->sync.run());sync.run();
        return button;
    }
    public void setOpen(boolean value){setOpen(value,true);}
    public void setOpen(boolean value,boolean animated){
        if(open==value&&!openingMotion)return;
        boolean previous=open;open=value;
        firePropertyChange("open",previous,value);
        orb.getAccessibleContext().setAccessibleName(value?"AI멘토 접기":"AI멘토 열기");
        if(!animated||!isShowing()||Boolean.getBoolean("synesis.reduceMotion")){
            progress=value?1:0;LayoutMotionPanel.prepareNavigation(card,this::settle);repaintCard();return;
        }
        releaseSnapshot();card.setVisible(true);
        // Closing uses the already laid out pixels; walking all chat rows again delays the first frame.
        if(value)LayoutMotionPanel.prepareNavigation(card,this::doLayout);
        else doLayout();
        capture();from=progress;started=System.nanoTime();openingMotion=true;wake();repaintCard();
    }
    private void wake(){if(!motion.isRunning()&&isShowing()){lastTick=System.nanoTime();motion.start();}}
    private void tick(){
        if(!isShowing()){settle();return;}
        long now=System.nanoTime();float dt=Math.min(.05f,(now-lastTick)/1_000_000_000f);lastTick=now;
        applyPendingOrb();applyPendingBounds();
        float target=hovered?1:0;
        if(hover!=target){hover=HoverMotion.advance(hover,hovered,dt);orb.repaint();}
        if(openingMotion){
            float t=Math.min(1,(now-started)/180_000_000f),eased=t*t*(3-2*t);
            progress=from+((open?1:0)-from)*eased;repaintCard();
            if(t>=1){openingMotion=false;releaseSnapshot();card.setVisible(open);doLayout();}
        }
        if(moveTarget!=null){
            Rectangle old=card.getBounds();double blend=1-Math.exp(-dt/.065);
            moveX+=(moveTarget.x-moveX)*blend;moveY+=(moveTarget.y-moveY)*blend;
            if(Math.abs(moveTarget.x-moveX)<.5&&Math.abs(moveTarget.y-moveY)<.5){moveX=moveTarget.x;moveY=moveTarget.y;moveTarget=null;}
            card.setLocation((int)Math.round(moveX),(int)Math.round(moveY));layoutGrips();damage(old,card.getBounds());
        }
        finishMovement();
        if(!openingMotion&&hover==target&&pendingOrb==null&&pendingBounds==null&&moveTarget==null)motion.stop();
    }
    private void settle(){
        motion.stop();moveTarget=null;openingMotion=false;progress=open?1:0;hover=hovered?1:0;
        settling=true;
        try{applyPendingOrb();applyPendingBounds();}finally{settling=false;}
        pointerMoving=false;releaseBackdrop();
        releaseResize();
        releaseSnapshot();card.setVisible(open);settling=true;
        try{doLayout();}finally{settling=false;}
    }
    private void applyPendingOrb(){
        if(pendingOrb==null)return;
        Rectangle old=orb.getBounds();orbPosition=pendingOrb;pendingOrb=null;cardPosition=null;doLayout();
        damage(old,orb.getBounds());
    }
    /** Reuse only the stationary workspace. Chat children keep painting their live animations. */
    private void beginPointerMovement(){
        pointerMoving=true;
        if(backdrop!=null||!card.isVisible()||getParent()==null||getWidth()<1||getHeight()<1)return;
        double scale=Math.min(1,Math.sqrt(2_097_152d/(getWidth()*(double)getHeight())));
        BufferedImage image=new BufferedImage(Math.max(1,(int)(getWidth()*scale)),Math.max(1,(int)(getHeight()*scale)),BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();capturingBackdrop=true;
        try{g.scale(scale,scale);g.translate(-getX(),-getY());getParent().printAll(g);}
        finally{capturingBackdrop=false;g.dispose();}
        backdrop=image;setOpaque(true);
    }
    private void finishMovement(){if(!pointerMoving&&pendingOrb==null&&pendingBounds==null&&moveTarget==null)releaseBackdrop();}
    private void releaseBackdrop(){
        if(backdrop==null)return;
        backdrop.flush();backdrop=null;setOpaque(false);
        // Generation/model updates behind the moving card become visible again at rest.
        repaint();
    }
    @Override public void setBounds(int x,int y,int width,int height){
        if(width!=getWidth()||height!=getHeight())releaseBackdrop();
        super.setBounds(x,y,width,height);
    }
    private void releaseResize(){
        java.util.List<LayoutMotionPanel> panels=resizeHold;resizeHold=java.util.List.of();
        LayoutMotionPanel.releaseTree(panels);
    }
    @Override public void doLayout(){
        int w=getWidth(),h=getHeight();if(w<=0||h<=0)return;
        int ox=orbPosition==null?w-ORB_EXTENT-12:orbPosition.x,oy=orbPosition==null?h-ORB_EXTENT-12:orbPosition.y;
        orb.setBounds(clamp(ox,-ORB_OVERHANG,w-ORB_EXTENT+ORB_OVERHANG),
            clamp(oy,-ORB_OVERHANG,h-ORB_EXTENT+ORB_OVERHANG),ORB_EXTENT,ORB_EXTENT);
        if(!card.isVisible()){northwest.setVisible(false);southeast.setVisible(false);return;}
        int cw=Math.min(requested.width,maximumCardWidth()),ch=Math.min(requested.height,Math.max(1,h-100));
        Point center=orbPosition==null?null:new Point(orb.getX()+ORB_CENTER,orb.getY()+ORB_CENTER);
        Point placement=FloatingChatPlacement.place(w,h,cw,ch,center,cardPosition,MentorAvatar.SIZE);
        Rectangle next=new Rectangle(placement.x,placement.y,cw,ch);
        if(!next.equals(card.getBounds())){
            if(open&&!openingMotion&&!settling&&progress==1&&pendingBounds==null&&cardPosition==null&&isShowing()
                    &&card.getWidth()==cw&&card.getHeight()==ch&&!Boolean.getBoolean("synesis.reduceMotion")){
                if(moveTarget==null){moveX=card.getX();moveY=card.getY();}
                moveTarget=placement;wake();
            }else{moveTarget=null;card.setBounds(next);card.doLayout();}
        }else moveTarget=null;
        layoutGrips();
        northwest.setVisible(open&&!openingMotion);southeast.setVisible(open&&!openingMotion);
    }
    private void layoutGrips(){
        Rectangle bounds=card.getBounds();
        northwest.setBounds(bounds.x+2,bounds.y+2,14,14);southeast.setBounds(bounds.x+bounds.width-16,bounds.y+bounds.height-16,14,14);
    }
    private void applyPendingBounds(){
        if(pendingBounds==null)return;
        Rectangle next=pendingBounds;pendingBounds=null;
        Rectangle old=card.getBounds().union(orb.getBounds());
        cardPosition=next.getLocation();requested=next.getSize();doLayout();
        if(resizeOrigin!=null){
            Rectangle actual=card.getBounds();
            int dx=orbAtRight?actual.x+actual.width-resizeOrigin.x-resizeOrigin.width:actual.x-resizeOrigin.x;
            int dy=orbAtBottom?actual.y+actual.height-resizeOrigin.y-resizeOrigin.height:actual.y-resizeOrigin.y;
            orbPosition=new Point(resizeOrbOrigin.x+dx,resizeOrbOrigin.y+dy);
            orb.setLocation(clamp(orbPosition.x,-ORB_OVERHANG,getWidth()-ORB_EXTENT+ORB_OVERHANG),
                clamp(orbPosition.y,-ORB_OVERHANG,getHeight()-ORB_EXTENT+ORB_OVERHANG));
        }
        damage(old,card.getBounds().union(orb.getBounds()));
    }
    private static int clamp(int n,int min,int max){return Math.max(Math.min(min,max),Math.min(Math.max(min,max),n));}
    private int maximumCardWidth(){return Math.min(MAX_CARD_WIDTH,Math.max(1,getWidth()-32));}
    private Point point(MouseEvent e){return SwingUtilities.convertPoint(e.getComponent(),e.getPoint(),this);}
    private void installGesture(JComponent handle,int resize){
        handle.setCursor(Cursor.getPredefinedCursor(resize==0?Cursor.MOVE_CURSOR:resize<0?Cursor.NW_RESIZE_CURSOR:Cursor.SE_RESIZE_CURSOR));
        MouseAdapter gesture=new MouseAdapter(){
            private Point press;private Rectangle initial;
            @Override public void mousePressed(MouseEvent e){
                if(!SwingUtilities.isLeftMouseButton(e))return;settle();press=point(e);initial=card.getBounds();
                resizeOrigin=resize==0?null:new Rectangle(initial);resizeOrbOrigin=orb.getLocation();
                orbAtRight=orb.getX()+ORB_CENTER>=initial.getCenterX();orbAtBottom=orb.getY()+ORB_CENTER>=initial.getCenterY();
                if(resize!=0){releaseResize();resizeHold=LayoutMotionPanel.holdTree(body);}
            }
            @Override public void mouseDragged(MouseEvent e){
                if(press==null)return;Point p=point(e);int dx=p.x-press.x,dy=p.y-press.y;
                beginPointerMovement();
                Rectangle next=new Rectangle(initial);
                if(resize==0)next.translate(dx,dy);
                else {
                    int maxWidth=maximumCardWidth();
                    next.width=Math.max(Math.min(360,maxWidth),Math.min(maxWidth,initial.width+resize*dx));
                    next.height=Math.max(Math.min(360,getHeight()-100),Math.min(getHeight()-100,initial.height+resize*dy));
                    if(resize<0){next.x=initial.x+initial.width-next.width;next.y=initial.y+initial.height-next.height;}
                }
                pendingBounds=next;wake();e.consume();
            }
            @Override public void mouseReleased(MouseEvent e){press=null;if(pendingBounds!=null)tick();resizeOrigin=null;resizeOrbOrigin=null;releaseResize();pointerMoving=false;finishMovement();}
        };
        handle.addMouseListener(gesture);handle.addMouseMotionListener(gesture);
    }
    private static JComponent grip(int cursor){return new JComponent(){
        {setCursor(Cursor.getPredefinedCursor(cursor));setToolTipText("드래그해서 AI멘토 크기 조절");}
        @Override protected void paintComponent(Graphics g){g.setColor(MistWorkspaceTheme.MUTED);g.drawLine(3,11,11,3);g.drawLine(7,11,11,7);}
    };}
    @Override public boolean contains(int x,int y){return isVisible()&&(orb.getBounds().contains(x,y)||(card.isVisible()&&card.getBounds().contains(x,y)));}
    @Override public boolean isOptimizedDrawingEnabled(){return false;}
    @Override public void paint(Graphics graphics){if(!capturingBackdrop)super.paint(graphics);}
    @Override protected void paintComponent(Graphics graphics){
        if(backdrop!=null)graphics.drawImage(backdrop,0,0,getWidth(),getHeight(),null);
        if(!card.isVisible())return;Graphics2D g=(Graphics2D)graphics.create();
        try{g.setComposite(AlphaComposite.SrcOver.derive(progress));MistWorkspaceTheme.paintMentorShadow(g,card.getBounds());}finally{g.dispose();}
    }
    private void repaintCard(){Rectangle b=card.getBounds();b.grow(24,24);repaint(b);}
    private void damage(Rectangle a,Rectangle b){Rectangle r=a.union(b);r.grow(24,24);repaint(r);}
    private void capture(){
        if(card.getWidth()<1||card.getHeight()<1)return;
        double scale=Math.min(1,Math.sqrt(524_288d/(card.getWidth()*(double)card.getHeight())));
        snapshot=new BufferedImage(Math.max(1,(int)(card.getWidth()*scale)),Math.max(1,(int)(card.getHeight()*scale)),BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=snapshot.createGraphics();try{g.scale(scale,scale);body.printAll(g);}finally{g.dispose();}
    }
    private void releaseSnapshot(){if(snapshot!=null)snapshot.flush();snapshot=null;}
    private final class Card extends JPanel {
        Card(){super(new BorderLayout());setOpaque(false);}
        @Override public boolean isValidateRoot(){return true;}
        @Override public Component findComponentAt(int x,int y){return openingMotion?this:super.findComponentAt(x,y);}
        @Override public void paint(Graphics graphics){
            if(!openingMotion||snapshot==null){super.paint(graphics);return;}
            Graphics2D g=(Graphics2D)graphics.create();
            try{g.setComposite(AlphaComposite.SrcOver.derive(progress));double inset=6*(1-progress);
                g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
                g.translate(inset,inset);g.scale((getWidth()-2*inset)/getWidth(),(getHeight()-2*inset)/getHeight());
                g.drawImage(snapshot,0,0,getWidth(),getHeight(),null);
            }finally{g.dispose();}
        }
    }
    @Override public void addNotify(){super.addNotify();window=SwingUtilities.getWindowAncestor(this);if(window!=null)window.addWindowListener(activity);}
    @Override public void removeNotify(){settle();if(window!=null)window.removeWindowListener(activity);window=null;super.removeNotify();}
    @Override public void close(){settle();body.removeAll();}
}
